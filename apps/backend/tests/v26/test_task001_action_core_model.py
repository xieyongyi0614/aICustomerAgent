"""TASK-001 Action Core Model 单测。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.action import (
    ACTION_EXECUTION_MAP,
    ACTION_SOURCES,
    ACTION_STATUS_SEMANTICS,
    ACTION_STATUSES,
    ACTION_TYPES,
    FAILURE_KINDS,
    GATE_REASONS,
    RETRY_BACK_EDGE,
    TERMINAL_STATUSES,
    Action,
    ActionEffect,
    ActionResult,
    ActionRecord,
    make_dedupe_key,
    transition_action,
)


class TestValueSetFreeze:
    def test_action_types_nine_values(self):
        assert len(ACTION_TYPES) == 9
        assert set(ACTION_TYPES) == {
            "create_reminder",
            "cancel_reminder",
            "remember_fact",
            "create_object",
            "move_object",
            "use_object",
            "query_environment",
            "query_search",
            "send_notification",
        }

    def test_action_statuses_six_values(self):
        assert len(ACTION_STATUSES) == 6
        assert set(ACTION_STATUSES) == {
            "created",
            "planned",
            "executing",
            "succeeded",
            "failed",
            "cancelled",
        }

    def test_terminal_and_gates_frozen(self):
        assert set(TERMINAL_STATUSES) == {"succeeded", "failed", "cancelled"}
        assert len(GATE_REASONS) == 10
        assert len(FAILURE_KINDS) == 4


class TestActionValueObject:
    def test_six_questions_answerable(self):
        now = datetime.now(timezone.utc)
        result = ActionResult(
            status="succeeded",
            effects=[ActionEffect(kind="world", ref="evt_1", detail="ok")],
        )
        action = Action(
            id="act_1",
            type="create_reminder",
            target="user_1",
            parameters={"content": "开会", "due": "明天"},
            status="succeeded",
            result=result,
            created_at=now,
            scheduled_at=now,
            executed_at=now,
            source="plan",
            goal_id="goal_1",
            plan_step="step_1",
            dedupe_key="abc",
            run_id="run_1",
        )
        assert action.type == "create_reminder"
        assert action.target == "user_1" and action.parameters["content"] == "开会"
        assert action.status == "succeeded"
        assert action.result is not None and action.result.status == "succeeded"
        assert action.created_at == now
        assert action.scheduled_at == now and action.executed_at == now
        assert action.is_terminal()

    def test_defaults(self):
        action = Action(id="act_2", type="query_environment")
        assert action.priority == 100
        assert action.status == "created"
        assert action.source == "conversation"
        assert action.parameters == {}
        assert action.result is None
        assert not action.is_terminal()

    def test_serialization_roundtrip(self):
        action = Action(
            id="act_3",
            type="send_notification",
            parameters={"content": "hi"},
            source="event_driven",
        )
        payload = action.model_dump()
        restored = Action.model_validate(payload)
        assert restored == action

    def test_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            Action(id="act_x", type="fly_to_moon")


class TestExecutionMap:
    def test_full_coverage(self):
        assert set(ACTION_EXECUTION_MAP.keys()) == set(ACTION_TYPES)

    def test_kind_values(self):
        assert ACTION_EXECUTION_MAP["create_reminder"] == "internal"
        assert ACTION_EXECUTION_MAP["query_environment"] == "tool"
        assert ACTION_EXECUTION_MAP["send_notification"] == "external"
        assert ACTION_EXECUTION_MAP["query_search"] == "tool"
        assert ACTION_EXECUTION_MAP["create_object"] == "internal"
        assert ACTION_EXECUTION_MAP["move_object"] == "internal"
        assert ACTION_EXECUTION_MAP["use_object"] == "internal"
        assert ACTION_EXECUTION_MAP["cancel_reminder"] == "internal"
        assert ACTION_EXECUTION_MAP["remember_fact"] == "internal"


class TestActionSource:
    def test_five_values(self):
        assert set(ACTION_SOURCES) == {
            "conversation",
            "autonomy",
            "cancel",
            "plan",
            "event_driven",
        }

    def test_record_accepts_plan_source(self):
        record = ActionRecord(
            id="act_p", user_id="u1", action_type="create_reminder", source="plan"
        )
        assert record.source == "plan"

    def test_record_accepts_event_driven_source(self):
        record = ActionRecord(
            id="act_e", user_id="u1", action_type="create_reminder", source="event_driven"
        )
        assert record.source == "event_driven"

    def test_rejects_unknown_source(self):
        with pytest.raises(ValidationError):
            ActionRecord(
                id="act_u", user_id="u1", action_type="create_reminder", source="magic"
            )


class TestStateMachineSemantics:
    def test_semantics_table_keys_match_statuses(self):
        assert set(ACTION_STATUS_SEMANTICS.keys()) == set(ACTION_STATUSES)

    def test_retry_back_edge_documented(self):
        assert RETRY_BACK_EDGE == ("failed", "planned")
        assert "retry" in ACTION_STATUS_SEMANTICS["failed"]

    def test_terminal_out_degree_zero_in_transition_table(self):
        for status in ("succeeded", "cancelled"):
            for event in (
                "gate_pass",
                "gate_reject",
                "execute_start",
                "step_all_succeeded",
                "step_retryable_failed",
                "step_permanent_failed",
                "expire",
                "cancel_requested",
            ):
                assert transition_action(status, event) is None

    def test_failed_is_terminal_in_transition_table(self):
        for event in (
            "gate_pass",
            "execute_start",
            "step_all_succeeded",
            "cancel_requested",
        ):
            assert transition_action("failed", event) is None

    def test_success_path_unchanged(self):
        assert transition_action("created", "gate_pass") == "planned"
        assert transition_action("planned", "execute_start") == "executing"
        assert transition_action("executing", "step_all_succeeded") == "succeeded"


class TestModelLayerPurity:
    def test_models_have_no_upper_layer_imports(self):
        import app.models.action as module

        source = open(module.__file__, encoding="utf-8").read()
        for banned in (
            "app.repositories",
            "app.application",
            "app.services",
            "app.api",
        ):
            assert banned not in source


class TestScenarioFromIntent:
    def test_intent_to_action_to_record(self):
        action = Action(
            id="act_s1",
            type="create_reminder",
            target="u1",
            parameters={"content": "买牛奶", "due": "晚上"},
            source="conversation",
            dedupe_key=make_dedupe_key("create_reminder", {"content": "买牛奶", "due": "晚上"}),
        )
        record = ActionRecord(
            id=action.id,
            user_id="u1",
            source=action.source,
            action_type=action.type,
            params=action.parameters,
            status=action.status,
            dedupe_key=action.dedupe_key,
            goal_id=action.goal_id,
        )
        assert record.action_type == "create_reminder"
        assert record.params["content"] == "买牛奶"
        assert record.source == "conversation"
        assert record.status == "created"
        assert not record.is_terminal()
