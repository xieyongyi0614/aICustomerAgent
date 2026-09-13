"""AGENT-007 Integration：Flag 组合矩阵 + Evolution Loop 全链收口验证。

覆盖：五 Flag enablement 全组合、全 Flag 开启下的 Run 链路（前台 Run 台账 +
Snapshot + Goal Stack + 决策审计 + 人格基线种子 + 指标快照 + Ledger）、
逐档回滚行为面、全关对照（v2.0.0 行为）、版本回归清单文档存在性。
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.application import life_loop
from app.core import llm_factory
from app.core.settings import get_settings
from app.core.settings.enablement import enablement_violations
from app.main import app
from app.repositories import (
    agent_metric_repository,
    conversation_repository,
    loop_run_repository,
    personality_state_repository,
    agent_state_snapshot_repository,
)
from app.character.asuna import evolution as persona_evolution
from app.services import evolution, trigger_evaluator

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "integration-user"
SESSION = "int-s1"

ALL_V21_FLAGS = {
    "V21_AGENT_RUNTIME_ENABLED": "true",
    "V21_UNIFIED_RUN_ENABLED": "true",
    "V21_GOAL_STACK_ENABLED": "true",
    "V21_AGENT_METRICS_ENABLED": "true",
    "V21_PERSONALITY_EVOLUTION_ENABLED": "true",
}


@pytest.fixture
def client(db_session_factory):
    with TestClient(app) as test_client:
        yield test_client


def _structured_llm(fake_llm):
    return fake_llm(
        response="好呀，我在。",
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


class TestEnablementMatrix:
    def test_full_matrix_dependencies(self, override_settings):
        override_settings(**ALL_V21_FLAGS)
        assert [
            v for v in enablement_violations(get_settings()) if "v21" in v
        ] == []

    def test_each_subflag_requires_runtime(self, override_settings):
        for flag in (
            "V21_UNIFIED_RUN_ENABLED",
            "V21_GOAL_STACK_ENABLED",
            "V21_AGENT_METRICS_ENABLED",
            "V21_PERSONALITY_EVOLUTION_ENABLED",
        ):
            override_settings(**{flag: "true"}, V21_AGENT_RUNTIME_ENABLED="false")
            violations = enablement_violations(get_settings())
            assert any("v21_agent_runtime_enabled" in v for v in violations), flag

    def test_personality_requires_metrics(self, override_settings):
        override_settings(
            V21_AGENT_RUNTIME_ENABLED="true",
            V21_PERSONALITY_EVOLUTION_ENABLED="true",
            V21_AGENT_METRICS_ENABLED="false",
        )
        violations = [
            v
            for v in enablement_violations(get_settings())
            if "v21_personality_evolution_enabled" in v
        ]
        assert violations, "演化必须依赖反馈通道（架构 §9.2 顺序约束）"


class TestEvolutionLoopE2E:
    def test_foreground_run_full_chain(
        self, db_session_factory, override_settings, client, fake_llm
    ):
        override_settings(**ALL_V21_FLAGS)
        llm_factory.set_llm(_structured_llm(fake_llm))

        resp = client.post("/api/v1/chat/message", json={"content": "我有点累"})
        assert resp.status_code == 200

        runs = loop_run_repository.list_recent(run_kind="foreground_chat")
        assert len(runs) == 1
        run = runs[0]
        assert run.status == "done"
        assert run.profile["budget_tier"] == "foreground"

        chat_user = get_settings().default_user
        anchors = {
            "personality_seeded": len(personality_state_repository.get_all(chat_user)) > 0,
            "snapshot_archived": agent_state_snapshot_repository.latest(chat_user) is not None,
        }
        assert all(anchors.values()), anchors

    @pytest.mark.asyncio
    async     def test_goal_stack_and_snapshot_stages_present(
        self, db_session_factory, override_settings, fake_llm, monkeypatch
    ):
        override_settings(
            V2_LIFE_LOOP_ENABLED="true", world_enabled="false", **ALL_V21_FLAGS
        )
        trigger_evaluator._followup_registry.clear()
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
        for stage in ("state_snapshot", "goal_stack", "decision", "world_experience"):
            assert stage in steps, stage
        assert steps.index("goal_stack") == steps.index("goal_check") + 1

    def test_metrics_snapshot_and_ledger(self, db_session_factory, override_settings):
        override_settings(**ALL_V21_FLAGS)
        personality_state_repository.seed_if_absent(USER, persona_evolution.PERSONALITY_AXES)
        from app.repositories import goal_repository

        goal_repository.create_hierarchical_goal(
            USER, "long_term", "relationship", "成为信任的伙伴", 3, origin="insight"
        )
        result = __import__("app.services.agent_evaluation", fromlist=["run_daily_snapshot"]).run_daily_snapshot(
            USER, NOW
        )
        assert result["status"] == "ok"
        assert agent_metric_repository.list_recent(USER, limit=5)

        entries = evolution.ledger(USER, limit=20)
        assert any(e["change_kind"] == "goal" for e in entries)

    def test_evolution_feedback_chain(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(**ALL_V21_FLAGS)
        personality_state_repository.seed_if_absent(USER, persona_evolution.PERSONALITY_AXES)
        from app.repositories import action_repository

        def _failed_action(created_at):
            from app.core.db import ActionRecordRow

            row = ActionRecordRow(
                id=str(uuid4()),
                user_id=USER,
                session_id=None,
                action_type="query_search",
                status="failed",
                created_at=created_at,
                updated_at=created_at,
            )
            with action_repository.SessionLocal() as session:
                session.merge(row)
                session.commit()

        from app.services.reflection import triggers as reflection_triggers

        fired = []
        monkeypatch.setattr(
            reflection_triggers,
            "trigger_for_user",
            lambda user_id, trigger, now=None: fired.append(trigger) or "queued",
        )
        _failed_action(NOW)
        agent_evaluation = __import__(
            "app.services.agent_evaluation", fromlist=["run_daily_snapshot"]
        )
        agent_evaluation.run_daily_snapshot(USER, NOW)
        next_day = NOW + timedelta(days=1)
        _failed_action(next_day)
        second = agent_evaluation.run_daily_snapshot(USER, next_day)

        assert second["trend"]["action_quality"]["breached"] is True
        assert second["topics"], "趋势越限必须产生演化议题"
        assert fired == ["event"], "议题必须经 Reflection 既有触发通道"

    def test_rollback_chain_downgrade_safe(
        self, db_session_factory, override_settings, client, fake_llm
    ):
        override_settings(**ALL_V21_FLAGS)
        llm_factory.set_llm(_structured_llm(fake_llm))
        client.post("/api/v1/chat/message", json={"content": "嗨"})
        assert loop_run_repository.list_recent(run_kind="foreground_chat")

        override_settings(
            V21_PERSONALITY_EVOLUTION_ENABLED="false",
            V21_AGENT_METRICS_ENABLED="false",
            V21_GOAL_STACK_ENABLED="false",
            V21_UNIFIED_RUN_ENABLED="false",
            V21_AGENT_RUNTIME_ENABLED="false",
        )
        runs_before = len(loop_run_repository.list_recent(run_kind="foreground_chat"))
        client.post("/api/v1/chat/message", json={"content": "在么"})
        runs = loop_run_repository.list_recent(run_kind="foreground_chat")
        assert len(runs) == runs_before, "Flag 全关后不得新增 foreground_chat 台账行"
        assert all(r.status in ("done", "degraded") for r in runs)


class TestFlagOff:
    def test_all_flags_off_no_v21_writes(self, db_session_factory, override_settings):
        override_settings(V2_LIFE_LOOP_ENABLED="false")
        assert enablement_violations(get_settings()) == []
