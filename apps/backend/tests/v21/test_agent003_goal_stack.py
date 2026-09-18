"""AGENT-003 Goal Stack 测试。

覆盖：栈裁决（主目标选举/能量抑制）、L2/L1 超时退役、对齐度评分契约、
供给 origin 落库与 commitment 来源、上下文栈段（Flag on/off）、
_select_goal 层级扩展、enablement 依赖。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.application import life_loop
from app.models.goal import GoalRecord, validate_parent_chain
from app.repositories import (
    conversation_repository,
    goal_repository,
    loop_run_repository,
)
from app.services import goal_alignment, goal_stack, trigger_evaluator

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "goal-stack-user"
SESSION = "gs-s1"


def _goal(layer, description, priority=3, type_="conversation", age_days=0):
    return GoalRecord(
        user_id=USER,
        type=type_,
        description=description,
        priority=priority,
        horizon="persistent",
        created_turn=0,
        layer=layer,
        created_at=NOW - timedelta(days=age_days),
        updated_at=NOW - timedelta(days=age_days),
        origin="insight",
    )


@pytest.fixture()
def stack_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings(
        AGENT_RUNTIME_ENABLED="true",
        GOAL_STACK_ENABLED="true",
        world_enabled="false")
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


class TestGoalStackEvaluator:
    def test_empty_stack_when_flag_off(self, db_session_factory, override_settings):
        override_settings(GOAL_STACK_ENABLED="false")
        stack = goal_stack.evaluate_stack(USER, NOW)
        assert stack.primary() is None and stack.drives == {}

    def test_primary_selection_and_drives(self, db_session_factory, stack_on):
        goal_repository.create_hierarchical_goal(
            USER, "long_term", "relationship", "成为信任的伙伴", 2, origin="insight"
        )
        goal_repository.create_hierarchical_goal(
            USER, "short_term", "world", "今晚问候用户", 4, origin="insight"
        )
        stack = goal_stack.evaluate_stack(USER, NOW)
        assert stack.long_term.description == "成为信任的伙伴"
        assert stack.short_term.description == "今晚问候用户"
        assert stack.drives[stack.short_term.id] == round(1.0 * 0.8, 4)
        assert stack.primary() is stack.short_term

    def test_same_layer_priority_wins(self, db_session_factory, stack_on):
        goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "整理资料", 2, origin="insight"
        )
        goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "了解用户新工作", 5, origin="insight"
        )
        stack = goal_stack.evaluate_stack(USER, NOW)
        assert stack.medium.description == "了解用户新工作"

    def test_medium_timeout_retires(self, db_session_factory, stack_on):
        goal = goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "早已过期的中期目标", 3, origin="insight"
        )
        with goal_repository.SessionLocal() as session:
            from app.core.db import GoalRow

            row = session.get(GoalRow, goal.id)
            row.created_at = NOW - timedelta(days=8)
            session.commit()
        goal_stack.evaluate_stack(USER, NOW)
        record = goal_repository.get_goal(goal.id)
        assert record.status == "abandoned"
        assert record.failure_reason == "timeout"


class TestAlignmentScorer:
    def _stack(self, long=None, medium=None, short=None):
        stack = goal_stack.GoalStack()
        stack.long_term = long
        stack.medium = medium
        stack.short_term = short
        return stack

    def test_empty_stack_is_zero(self):
        assert goal_alignment.score({"type": "user_care"}, goal_stack.GoalStack()) == 0.0
        assert goal_alignment.score(None, None) == 0.0

    def test_l1_type_match_beats_l3(self):
        long = _goal("long_term", "L3", type_="relationship")
        short = _goal("short_term", "L1", type_="user_care")
        stack = self._stack(long=long, short=short)
        score = goal_alignment.score({"type": "user_care"}, stack)
        assert score == 1.0

    def test_capability_hint_scores_partial(self):
        short = _goal("short_term", "L1", type_="user_care")
        score = goal_alignment.score({"capability": "reminder"}, self._stack(short=short))
        assert 0.0 < score <= 1.0


class TestSupplyOrigin:
    def test_commitment_memory_creates_medium_goal(self, db_session_factory, stack_on, monkeypatch):
        import app.services.goal_planning as planning

        monkeypatch.setattr(
            planning.memory_repository,
            "list_top_salience",
            lambda *args, **kwargs: [
                SimpleNamespace(type="commitment", content="帮用户查资料")
            ],
        )
        candidates = planning.collect_candidates(USER, {})
        origins = {c["origin"] for c in candidates}
        assert "commitment" in origins
        layers = {c["layer"] for c in candidates if c["origin"] == "commitment"}
        assert "medium" in layers

    def test_materialize_persists_origin(self, db_session_factory, stack_on, override_settings):
        override_settings( ACTION_ENABLED="true"
        )
        override = {"salient_events": [{"importance": "high", "title": "面试日"}]}
        result = __import__("app.services.goal_planning", fromlist=["materialize"]).materialize(
            USER, world_facts=override, now=NOW
        )
        created = result["created"]
        assert created, "应至少创建一个目标"
        for goal_id in created:
            record = goal_repository.get_goal(goal_id)
            assert record.origin is not None


class TestParentChain:
    def test_chain_rules(self):
        assert validate_parent_chain("long_term", "medium") is True
        assert validate_parent_chain("long_term", "short_term") is True
        assert validate_parent_chain("medium", "short_term") is True
        assert validate_parent_chain("medium", "long_term") is False
        assert validate_parent_chain("short_term", "medium") is False
        assert validate_parent_chain(None, None) is True
        assert validate_parent_chain(None, "medium") is False


class TestRunIntegration:
    @pytest.mark.asyncio
    async def test_cycle_records_goal_stack_stage(
        self, db_session_factory, stack_on, monkeypatch
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
        assert "goal_stack" in steps
        assert steps.index("goal_stack") == steps.index("goal_check") + 1
        stack_step = next(s for s in run.steps if s["step"] == "goal_stack")
        assert "primary_goal" in stack_step
        assert "suppressed" in stack_step


class TestEnablement:
    def test_goal_stack_requires_runtime(self, override_settings):
        from app.core.settings import get_settings
        from app.core.settings.enablement import enablement_violations

        override_settings(GOAL_STACK_ENABLED="true")
        assert any(
            "goal_stack_enabled" in v for v in enablement_violations(get_settings())
        )
