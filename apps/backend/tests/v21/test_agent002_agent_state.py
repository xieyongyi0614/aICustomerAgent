"""AGENT-002 Character State 测试。

覆盖：人格轴种子幂等与边界物化、Interest 四来源加权与降级、Focus 组合、
存档策略（显著变化/最小间隔/每日保底/保留期）、后台 Run 的 state_snapshot
阶段与快照存档、前台 prompt 兴趣段、Flag off 零写入。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.application import agent_state_assembler, life_loop
from app.application.agent_state_archiver import archive_if_significant
from app.character.asuna import evolution
from app.models.agent_state import (
    AgentStateSnapshot,
    CurrentFocus,
    InterestTopic,
)
from app.models.goal import GoalRecord
from app.repositories import (
    agent_state_snapshot_repository as snapshot_repo,
    conversation_repository,
    loop_run_repository,
    personality_state_repository,
)
from app.services import trigger_evaluator

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "agent-state-user"
SESSION = "as-s1"


def _goal(description="陪用户准备面试", priority=5, layer="short_term"):
    return GoalRecord(
        user_id=USER,
        type="user_care",
        description=description,
        priority=priority,
        horizon="persistent",
        created_turn=0,
        layer=layer,
        created_at=NOW,
        updated_at=NOW,
    )


def _snapshot(mood="calm", goal_id="g1", top="面试"):
    return AgentStateSnapshot(
        mood=mood,
        energy=0.9,
        interest_focus=[InterestTopic(topic=top, score=1.0)],
        current_focus=CurrentFocus(goal_id=goal_id),
    )


@pytest.fixture
def client(db_session_factory):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def runtime_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings(
        V2_LIFE_LOOP_ENABLED="true",
        V21_AGENT_RUNTIME_ENABLED="true",
        world_enabled="false",
    )
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


class TestPersonalitySeed:
    def test_seed_creates_axes_with_materialized_bounds(self, db_session_factory):
        created = personality_state_repository.seed_if_absent(
            USER, evolution.PERSONALITY_AXES
        )
        assert created is True
        rows = {r.axis: r for r in personality_state_repository.get_all(USER)}
        assert set(rows) == set(evolution.PERSONALITY_AXES)
        a = rows["assertiveness"]
        assert a.baseline == 0.30 and a.current == 0.30
        assert a.bound_min == 0.10 and a.bound_max == 0.50
        p = rows["patience"]
        assert p.bound_min == 0.45 and p.bound_max == 0.75

    def test_seed_is_idempotent(self, db_session_factory):
        assert personality_state_repository.seed_if_absent(USER, evolution.PERSONALITY_AXES)
        assert personality_state_repository.seed_if_absent(
            USER, evolution.PERSONALITY_AXES
        ) is False
        assert len(personality_state_repository.get_all(USER)) == 4


class TestInterestComposition:
    def test_sources_weighted_and_ranked(self, override_settings):
        override_settings(V21_INTEREST_WEIGHT_MEMORY="2.0")
        settings = __import__("app.core.settings", fromlist=["get_settings"]).get_settings()
        goals = [_goal()]
        preferences = [
            SimpleNamespace(kind="preference", key="聊工作项目", strength=0.8)
        ]
        memories = [SimpleNamespace(content="用户在准备一场重要的面试", salience=0.9)]
        world = {"salient_events": [{"title": "面试日临近"}]}
        topics = agent_state_assembler._compose_interest(
            goals, preferences, world, memories, settings
        )
        assert topics, "有来源时榜单不应为空"
        assert topics[0].topic == "用户在准备一场重要的面试"[:24]
        assert len(topics) <= settings.v21_interest_top_n

    def test_empty_sources_give_empty_board(self, override_settings):
        settings = __import__("app.core.settings", fromlist=["get_settings"]).get_settings()
        assert agent_state_assembler._compose_interest([], [], {}, [], settings) == []

    def test_missing_source_does_not_block(self, override_settings):
        settings = __import__("app.core.settings", fromlist=["get_settings"]).get_settings()
        topics = agent_state_assembler._compose_interest(
            [_goal()], [], {}, [SimpleNamespace(content="面试", salience=0.9)], settings
        )
        assert len(topics) == 2


class TestFocusComposition:
    def test_prefers_short_term_goal(self):
        short = _goal(layer="short_term", description="今晚问候用户")
        long = _goal(layer="long_term", description="成为用户信任的伙伴", priority=5)
        focus = agent_state_assembler._compose_focus(
            SimpleNamespace(current_topic="面试"), [long, short], USER
        )
        assert focus.goal_description == "今晚问候用户"
        assert focus.topic == "面试"

    def test_no_goals_yields_empty_focus_fields(self):
        focus = agent_state_assembler._compose_focus(
            SimpleNamespace(current_topic=""), [], USER
        )
        assert focus.goal_id is None and focus.action == ""


class TestArchiver:
    def test_first_archive_always_writes(self, db_session_factory):
        assert archive_if_significant(USER, "asuna", _snapshot(), now=NOW) is True
        assert snapshot_repo.latest(USER).version == 1

    def test_unchanged_within_interval_skipped(self, db_session_factory):
        archive_if_significant(USER, "asuna", _snapshot(), now=NOW)
        later = NOW + timedelta(minutes=5)
        assert archive_if_significant(USER, "asuna", _snapshot(), now=later) is False
        assert len(snapshot_repo.list_recent(USER, limit=10)) == 1

    def test_daily_fallback_writes_without_change(self, db_session_factory):
        archive_if_significant(USER, "asuna", _snapshot(), now=NOW)
        next_day = NOW + timedelta(days=1)
        assert archive_if_significant(USER, "asuna", _snapshot(), now=next_day) is True

    def test_mood_change_after_interval_bumps_version(self, db_session_factory):
        archive_if_significant(USER, "asuna", _snapshot(), now=NOW)
        later = NOW + timedelta(minutes=16)
        changed = _snapshot(mood="happy", goal_id="g1")
        assert archive_if_significant(USER, "asuna", changed, now=later) is True
        assert snapshot_repo.latest(USER).version == 2

    def test_retention_cleanup(self, db_session_factory):
        archive_if_significant(USER, "asuna", _snapshot(), now=NOW)
        stale = snapshot_repo.latest(USER)
        with snapshot_repo.SessionLocal() as session:
            row = session.get(type(stale), stale.id)
            row.created_at = NOW - timedelta(days=91)
            session.commit()
        deleted = snapshot_repo.cleanup_expired(90, NOW)
        assert deleted == 1


class TestBackgroundRunIntegration:
    @pytest.mark.asyncio
    async def test_cycle_records_snapshot_stage_and_archive(
        self, db_session_factory, runtime_on, monkeypatch
    ):
        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_evaluator.register_followup(USER, NOW - timedelta(minutes=1), "下午面试")
        from app.application import autonomy_engine

        async def fake_tick(user_ids=None, llm=None, now=None):
            return []

        monkeypatch.setattr(autonomy_engine, "tick", fake_tick)
        stats = await life_loop.run_life_loop_tick(now=NOW)

        assert stats["user_cycles"] == 1
        run = loop_run_repository.list_recent(user_id=USER, run_kind="autonomous_tick")[0]
        steps = [s["step"] for s in run.steps]
        assert "state_snapshot" in steps
        assert steps.index("state_snapshot") == steps.index("state_update") + 1
        snap_row = snapshot_repo.latest(USER)
        assert snap_row is not None and snap_row.run_id == run.id
        assert len(personality_state_repository.get_all(USER)) == 4


class TestForegroundContextSegment:
    def test_prompt_carries_interest_section(
        self, db_session_factory, override_settings, client, fake_llm, monkeypatch
    ):
        from app.application import agent_state_assembler as assembler_mod
        from app.core import llm_factory

        override_settings(
            V21_AGENT_RUNTIME_ENABLED="true",
            V21_UNIFIED_RUN_ENABLED="true",
        )
        monkeypatch.setattr(
            assembler_mod,
            "_load_preferences",
            lambda user_id, character_id: [
                SimpleNamespace(kind="preference", key="面试准备", strength=0.8)
            ],
        )
        llm = fake_llm(
            response="好呀。",
            structured_responses={
                "RoleMode": {
                    "mode": "default",
                    "intent": "casual",
                    "confidence": 0.9,
                    "reason": "r",
                },
                "TurnAnalysis": {
                    "user_emotion": {"emotion": "sad", "event": "setback"},
                    "behavior": {"behavior": "comfort", "reason": "r"},
                },
                "IntentionDecision": {
                    "intention": "comfort_user",
                    "confidence": 0.9,
                    "reason": "r",
                },
            },
        )
        llm_factory.set_llm(llm)
        resp = client.post("/api/v1/chat/message", json={"content": "我有点累"})
        assert resp.status_code == 200

        answer_prompts = [m for m in llm.seen_messages if len(m) > 1]
        assert answer_prompts, "未捕获 answer 链 prompt"
        joined = "\n".join(str(msg.content) for msg in answer_prompts[-1])
        assert "【当前感兴趣】" in joined
        assert "面试准备" in joined

    def test_snapshot_archived_for_foreground_run(
        self, db_session_factory, override_settings, client, fake_llm
    ):
        from app.core import llm_factory

        override_settings(
            V21_AGENT_RUNTIME_ENABLED="true",
            V21_UNIFIED_RUN_ENABLED="true",
        )
        llm = fake_llm(
            response="好呀。",
            structured_responses={
                "RoleMode": {
                    "mode": "default",
                    "intent": "casual",
                    "confidence": 0.9,
                    "reason": "r",
                },
                "TurnAnalysis": {
                    "user_emotion": {"emotion": "sad", "event": "setback"},
                    "behavior": {"behavior": "comfort", "reason": "r"},
                },
            },
        )
        llm_factory.set_llm(llm)
        resp = client.post("/api/v1/chat/message", json={"content": "嗨"})
        assert resp.status_code == 200
        assert snapshot_repo.latest("default-user") is not None


class TestFlagOff:
    @pytest.mark.asyncio
    async def test_legacy_cycle_has_no_snapshot_stage_or_rows(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(V2_LIFE_LOOP_ENABLED="true", world_enabled="false")
        trigger_evaluator._followup_registry.clear()
        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_evaluator.register_followup(USER, NOW - timedelta(minutes=1), "下午面试")
        from app.application import autonomy_engine

        async def fake_tick(user_ids=None, llm=None, now=None):
            return []

        monkeypatch.setattr(autonomy_engine, "tick", fake_tick)
        await life_loop.run_life_loop_tick(now=NOW)

        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert "state_snapshot" not in [s["step"] for s in run.steps]
        assert personality_state_repository.get_all(USER) == []
        assert snapshot_repo.latest(USER) is None
        trigger_evaluator._followup_registry.clear()
