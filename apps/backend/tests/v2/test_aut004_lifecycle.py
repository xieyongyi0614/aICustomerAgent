"""AUT-004 冲突与生命周期测试。

状态机转换表全路径（v1 行/层级行 + 非法转换拒绝）、优先级计算调制项、
同域互斥仲裁（suspended 留痕+级联）、keeper 终态复活、仲裁幂等、
abandonment 双信号置信边界、lifecycle 决策记录、迁移 0032 往返。
"""

from datetime import datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.models.goal import GoalPlanRecord, IllegalGoalTransition
from app.repositories import goal_repository
from app.services.goal import arbitration as goal_arbitration

pytestmark = pytest.mark.xdist_group("migration")

NOW = datetime(2026, 9, 8, 12, 0, 0)
USER = "aut4-user"


@pytest.fixture()
def aut_on(override_settings, monkeypatch):
    override_settings()
    monkeypatch.setattr(
        "app.services.goal.arbitration.development_aggregate.read_overlay",
        lambda user_id, character_id="asuna": None,
    )
    yield
    goal_arbitration.reset_throttle_state()


def _goal(domain="personal", layer="long_term", description="目标", priority=3, user=USER):
    return goal_repository.create_hierarchical_goal(
        user, layer, domain, description, priority
    )


def _child(parent_id, description="子目标"):
    return goal_repository.create_hierarchical_goal(
        USER, "short_term", "personal", description, 3, parent_id=parent_id
    )


def _facts(**overrides):
    facts = {
        "now": NOW,
        "action_results": [],
        "action_history": [],
        "world": {},
        "state": {"tension": 0.1, "intimacy": 0.3, "mood": "calm"},
        "memory": {"salient_memory_count": 0},
        "salient_memories": [],
    }
    facts.update(overrides)
    return facts


class TestStateMachine:
    def test_layered_full_paths(self):
        from app.models.goal import goal_transitions

        assert set(goal_transitions("long_term", "active")) == {
            "completed", "failed", "abandoned", "suspended",
        }
        assert set(goal_transitions("short_term", "suspended")) == {"active", "abandoned"}
        assert goal_transitions("long_term", "failed") == ("active",)
        assert goal_transitions("long_term", "completed") == ()
        assert goal_transitions("long_term", "abandoned") == ()

    def test_v1_rows_keep_legacy_exits(self):
        from app.models.goal import goal_transitions

        assert set(goal_transitions(None, "active")) == {"completed", "expired", "cancelled"}
        assert goal_transitions(None, "expired") == ()
        assert goal_transitions(None, "suspended") == ()

    def test_set_status_guard_rejects_illegal(self, aut_on):
        goal = _goal()
        with pytest.raises(ValueError):
            goal_repository.set_status(goal.id, "suspended_from_nowhere")

    def test_v1_goal_cannot_be_suspended_or_failed(self, aut_on):
        from tests.v2.test_aut001_goal_hierarchy import _v1_record

        v1 = goal_repository.create_goal(_v1_record())
        with pytest.raises(ValueError):
            goal_repository.set_status(v1.id, "suspended")
        with pytest.raises(ValueError):
            goal_repository.fail_goal(v1.id, "exec_period_exceeded")

    def test_set_status_writes_arbitration_state(self, aut_on):
        goal = _goal()
        record = goal_repository.set_status(
            goal.id, "suspended", {"conflict_with": "other", "decided_at": NOW.isoformat()}
        )
        assert record.status == "suspended"
        assert record.arbitration_state["conflict_with"] == "other"


class TestPriority:
    def test_long_term_layer_bonus(self, override_settings):
        override_settings( autonomy_priority_layer_weight_long="1.0")
        from app.core.settings import get_settings

        goal = _goal(layer="long_term", priority=3)
        score = goal_arbitration.compute_priority(goal, None, {}, get_settings())
        assert score == pytest.approx(4.0)

    def test_relationship_tension_bonus_and_conflict_penalty(self, override_settings):
        override_settings(
            autonomy_priority_layer_weight_long="0",
            rel_tension_freeze="0.5")
        from app.core.settings import get_settings

        goal = _goal(domain="relationship", layer="short_term", priority=3)
        base = goal_arbitration.compute_priority(
            goal, None, {"tension": 0.8}, get_settings()
        )
        assert base == pytest.approx(3.5)
        penalized = goal_arbitration.compute_priority(
            goal, None, {"tension": 0.1, "conflict_status": "conflict"}, get_settings()
        )
        assert penalized == pytest.approx(2.0)


class TestConflictArbitration:
    def test_same_domain_conflict_suspends_loser_with_trace(self, aut_on, monkeypatch):
        keeper = _goal(description="高分目标", priority=5)
        loser = _goal(description="低分目标", priority=2)
        captured: list = []
        original = goal_repository.set_status

        def _spy(goal_id, target, arbitration=None):
            record = original(goal_id, target, arbitration)
            if record is not None and record.status == target:
                captured.append((goal_id, target))
            return record

        monkeypatch.setattr(goal_repository, "set_status", _spy)
        result = goal_arbitration.arbitrate_user(USER, NOW)
        assert result["status"] == "ok"
        assert goal_repository.get_goal(keeper.id).status == "active"
        loser_record = goal_repository.get_goal(loser.id)
        assert loser_record.status == "suspended"
        assert loser_record.arbitration_state["conflict_with"] == keeper.id
        assert any(change["goal_id"] == loser.id for change in result["changes"])

    def test_cross_domain_no_conflict(self, aut_on):
        personal = _goal(domain="personal", priority=5)
        relationship = _goal(domain="relationship", priority=2)
        goal_arbitration.arbitrate_user(USER, NOW)
        assert goal_repository.get_goal(personal.id).status == "active"
        assert goal_repository.get_goal(relationship.id).status == "active"

    def test_revival_when_keeper_terminal(self, aut_on):
        keeper = _goal(description="将完成的目标", priority=5)
        loser = _goal(description="被挂起目标", priority=2)
        goal_arbitration.arbitrate_user(USER, NOW)
        assert goal_repository.get_goal(loser.id).status == "suspended"
        goal_repository.complete_goal(keeper.id)
        result = goal_arbitration.arbitrate_user(USER, NOW)
        assert goal_repository.get_goal(loser.id).status == "active"
        assert any(change["reason"] == "revived" for change in result["changes"])

    def test_arbitration_idempotent(self, aut_on):
        _goal(description="甲", priority=5)
        _goal(description="乙", priority=2)
        first = goal_arbitration.arbitrate_user(USER, NOW)
        second = goal_arbitration.arbitrate_user(USER, NOW)
        assert len(first["changes"]) == 1
        assert second["changes"] == []

    def test_cascade_children_follow_parent(self, aut_on):
        keeper = _goal(description="保active", priority=5)
        loser = _goal(description="被挂起", priority=2)
        child = _child(loser.id)
        goal_arbitration.arbitrate_user(USER, NOW)
        assert goal_repository.get_goal(child.id).status == "suspended"
        goal_arbitration.arbitrate_user(USER, NOW)
        assert goal_repository.get_goal(child.id).status == "suspended"


def _spy_set_status(goal_id, target, arbitration, captured):
    record = goal_repository.set_status(goal_id, target, arbitration)
    if record is not None and record.status == target:
        captured.append((goal_id, target))
    return record


class TestAbandonment:
    def _long_term_goal(self):
        goal = _goal(description="长期目标", layer="long_term")
        goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal.id,
                version=1,
                status="active",
                sub_goals=[],
                created_at=NOW - timedelta(days=30),
                updated_at=NOW - timedelta(days=30),
            )
        )
        return goal

    def test_dual_signal_abandons(self, aut_on, override_settings):
        override_settings(autonomy_abandon_min_progress_days="14")
        goal = self._long_term_goal()
        result = goal_arbitration.check_abandonment(USER, _facts(), NOW)
        assert len(result["abandoned"]) == 1
        record = goal_repository.get_goal(goal.id)
        assert record.status == "abandoned"
        assert record.arbitration_state["confidence"] >= 0.6
        assert record.arbitration_state["low_relevance"] == {"memory": True, "action": True}

    def test_single_signal_caps_below_threshold(self, aut_on, override_settings):
        override_settings(autonomy_abandon_min_progress_days="14")
        goal = self._long_term_goal()
        facts = _facts(
            salient_memories=[_memory(f"{goal.description[:4]}相关记忆")],
        )
        result = goal_arbitration.check_abandonment(USER, facts, NOW)
        assert result["abandoned"] == []
        assert goal_repository.get_goal(goal.id).status == "active"

    def test_recent_progress_keeps_goal(self, aut_on, override_settings):
        override_settings(autonomy_abandon_min_progress_days="14")
        goal = _goal(description="长期目标", layer="long_term")
        goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal.id,
                version=1,
                status="active",
                sub_goals=[],
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            )
        )
        result = goal_arbitration.check_abandonment(USER, _facts(), NOW)
        assert result["abandoned"] == []

    def test_recent_action_blocks_low_relevance(self, aut_on, override_settings):
        override_settings(autonomy_abandon_min_progress_days="14")
        goal = self._long_term_goal()
        facts = _facts(
            action_history=[{"capability": "create_reminder", "created_at": NOW - timedelta(days=1)}]
        )
        result = goal_arbitration.check_abandonment(USER, facts, NOW)
        assert result["abandoned"] == []

    def test_abandonment_cascades_children(self, aut_on, override_settings):
        override_settings(autonomy_abandon_min_progress_days="14")
        goal = self._long_term_goal()
        child = _child(goal.id)
        goal_arbitration.check_abandonment(USER, _facts(), NOW)
        assert goal_repository.get_goal(child.id).status == "abandoned"

    def test_short_term_goals_exempt(self, aut_on, override_settings):
        override_settings(autonomy_abandon_min_progress_days="14")
        _goal(description="短期目标", layer="short_term")
        result = goal_arbitration.check_abandonment(USER, _facts(), NOW)
        assert result["abandoned"] == []


def _memory(content: str):
    from app.models.memory import UserMemory

    return UserMemory(
        id="mem-1",
        user_id=USER,
        character_id="asuna",
        type="experience",
        content=content,
        importance=0.9,
        created_at=NOW,
        updated_at=NOW,
    )


class TestOrchestration:


    def test_lifecycle_decision_recorded(self, aut_on, monkeypatch):
        keeper = _goal(description="高分", priority=5)
        _goal(description="低分", priority=2)
        captured: list = []
        import app.application.observability as observability

        monkeypatch.setattr(observability, "on_decision", lambda record: captured.append(record))
        goal_arbitration.arbitrate_user(USER, NOW)
        assert captured
        assert all(record.kind == "goal_lifecycle" for record in captured)
        assert keeper is not None


def test_trace_step_registered():
    from app.services.observability.collector import TRACE_STEP_NAMES

    assert "goal_arbitration" in TRACE_STEP_NAMES


@pytest.fixture(scope="module")
def sqlite_round_trip(tmp_path_factory):
    url = f"sqlite:///{(tmp_path_factory.mktemp('aut004') / 'arbitration.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield cfg, url


def test_head_schema_admits_failed_status_and_arbitration_state(sqlite_round_trip):
    """原 0030 逆放用例随迁移链折叠退役；保留 head 态值域与列断言。"""
    cfg, url = sqlite_round_trip
    del cfg
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO character_goals (id, user_id, character_id, type,"
                " description, priority, status, horizon, source, created_turn,"
                " created_at, updated_at, layer, domain, arbitration_state)"
                " VALUES ('g-failed', 'u-rt', 'asuna', 'user_care', '失败目标', 3,"
                " 'failed', 'persistent', 'policy', 0, '2026-09-01 00:00:00',"
                " '2026-09-01 00:00:00', 'long_term', 'personal', '{}')"
            )
        )
    inspector = inspect(engine)
    goal_columns = {c["name"] for c in inspector.get_columns("character_goals")}
    assert "arbitration_state" in goal_columns
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM character_goals WHERE status = 'failed'")
        ).scalar()
    assert count == 1
    engine.dispose()
