"""TASK-007 System Integration 测试。"""

from types import SimpleNamespace

import pytest

from app.models.action import ActionEffect, ActionIntent, ActionResult
from app.services.action import integration, manager


class TestPlanningIntegration:
    def test_create_from_plan_intent(self):
        intent = ActionIntent(
            action_type="create_reminder",
            confidence="confident",
            params={"content": "计划提醒", "due_at": "明天"},
            dedupe_key="plankey000000001",
        )
        action = integration.create_from_plan_intent(
            intent,
            user_id="u_plan",
            goal_id="goal_1",
            plan_step="step_0",
        )
        assert action.source == "plan"
        assert action.type == "create_reminder"
        assert action.goal_id == "goal_1"
        assert action.status == "created"

    def test_to_plan_step_outcome_success(self):
        result = ActionResult(
            status="succeeded",
            effects=[ActionEffect(kind="world", ref="evt_1", detail="ok")],
            observations={"world_event_id": "evt_1"},
        )
        outcome = integration.to_plan_step_outcome(result, action_id="a1")
        assert outcome.status == "succeeded"
        assert outcome.action_id == "a1"
        assert outcome.observations["world_event_id"] == "evt_1"

    def test_to_plan_step_outcome_failure(self):
        result = ActionResult(status="failed", error="x", failure_kind="transient")
        outcome = integration.to_plan_step_outcome(result, action_id="a2")
        assert outcome.status == "failed"
        assert outcome.failure_kind == "transient"


class TestEffectRouting:
    def test_route_four_channels(self):
        result = ActionResult(
            status="succeeded",
            effects=[
                ActionEffect(kind="world", ref="w"),
                ActionEffect(kind="memory", ref="m"),
                ActionEffect(kind="relationship", ref="r"),
                ActionEffect(kind="note", ref="n"),
            ],
        )
        routed = integration.route_effects(result)
        assert set(routed.keys()) == {"world", "memory", "relationship", "note"}
        assert len(routed["world"]) == 1
        assert integration.world_effects_pending(result)[0].ref == "w"
        assert integration.memory_effects_pending(result)[0].ref == "m"
        assert integration.relationship_effects_pending(result)[0].ref == "r"

    def test_temporary_vs_important(self):
        query_action = manager.create(
            user_id="u_t",
            action_type="query_environment",
            params={},
        )
        record = manager.query(query_action.id)
        # temporary: query_environment not in memory policy deposit table
        from app.repositories import action_repository

        raw = action_repository.get_record(query_action.id)
        assert integration.is_temporary_execution(raw) is True

        remember = manager.create(
            user_id="u_t2",
            action_type="remember_fact",
            params={"fact": "重要事实"},
        )
        raw2 = action_repository.get_record(remember.id)
        assert integration.is_temporary_execution(raw2) is False


class TestFeedbackLoop:
    def test_apply_feedback_flag_on_enriched(self, monkeypatch):
        from app.core.settings import get_settings

        settings = get_settings()
        action = manager.create(
            user_id="u_fb2",
            action_type="create_reminder",
            params={"content": "反馈"},
        )
        from app.repositories import action_repository

        record = action_repository.get_record(action.id)
        record.status = "succeeded"
        action_repository.save_record(record)
        result = ActionResult(
            status="succeeded",
            effects=[ActionEffect(kind="world", ref="evt_fb", detail="ok")],
            output={"world_event_id": "evt_fb"},
        )
        summary = integration.apply_result_feedback(record, result)
        assert summary["mode"] == "v26"
        assert summary["feedback"]["feedback_kinds"] == ["world"]
        assert summary["feedback"]["world_event_id"] == "evt_fb"


class TestStaticBoundaries:
    def test_planning_does_not_call_executor_directly(self):
        source = open(
            integration.__file__, encoding="utf-8"
        ).read()
        assert "ActionExecutor" not in source
        assert "world_engine." not in source
        assert "relationship_bridge." not in source
        assert "memory_repository." not in source

    def test_module_delegates_to_integrate_result(self):
        source = open(integration.__file__, encoding="utf-8").read()
        assert "integrate_result" in source
