"""TASK-006 Action Result System 测试。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.action import (
    ActionEffect,
    ActionResult,
    CapabilityResult,
    make_dedupe_key,
)
from app.services.action import result as result_service
from app.services.action import manager


class TestResultContract:
    def test_fields_present_and_roundtrip(self):
        result = ActionResult(
            id="res_1",
            action_id="act_1",
            status="succeeded",
            effects=[ActionEffect(kind="world", ref="evt_1", detail="ok")],
            output={"world_event_id": "evt_1"},
            metadata={"usage": {"duration_ms": 1}},
            observations={"world_event_id": "evt_1"},
            created_at=datetime.now(),
        )
        restored = ActionResult.model_validate(result.model_dump())
        assert restored.id == "res_1"
        assert restored.action_id == "act_1"
        assert restored.output["world_event_id"] == "evt_1"
        assert restored.observations["world_event_id"] == "evt_1"
        assert restored.metadata["usage"]["duration_ms"] == 1

    def test_status_four_values(self):
        for status in ("succeeded", "failed", "partial", "timeout"):
            assert ActionResult(status=status).status == status
        with pytest.raises(ValidationError):
            ActionResult(status="weird")

    def test_effect_helpers(self):
        result = ActionResult(
            status="succeeded",
            effects=[
                ActionEffect(kind="memory", ref="m1"),
                ActionEffect(kind="world", ref="w1"),
            ],
        )
        assert result.has_memory_effect()
        assert result.has_world_effect()
        assert not result.has_relationship_effect()


class TestFourOutcomes:
    def test_success(self):
        result = result_service.from_capability_result(
            CapabilityResult(status="succeeded", payload={"note": "done"}),
            action_id="a1",
        )
        assert result.status == "succeeded"
        assert result.output["note"] == "done"
        assert result.id and result.action_id == "a1"
        assert result.created_at is not None

    def test_failure_transient(self):
        result = result_service.from_capability_result(
            CapabilityResult(
                status="failed", error="boom", payload={"failure_kind": "transient"}
            ),
            action_id="a2",
        )
        assert result.status == "failed"
        assert result.failure_kind == "transient"
        assert result_service.classify_retryable(result)

    def test_timeout_maps_timeout(self):
        """v26 去门控语义反转：timeout 语义恒生效（原 gate-off 退化为 failed 的分支已删）。"""
        result = result_service.from_capability_result(
            CapabilityResult(status="timeout", error="slow", payload={"failure_kind": "timeout"}),
            action_id="a3",
        )
        assert result.status == "timeout"
        assert result.failure_kind == "timeout"

    def test_partial_not_retried(self):
        result = ActionResult(status="partial", effects=[ActionEffect(kind="world", ref="w")])
        assert not result_service.classify_retryable(result)

    def test_retry_reuses_dedupe_key(self):
        key = make_dedupe_key("create_reminder", {"content": "开会"})
        action = manager.create(
            user_id="u1",
            action_type="create_reminder",
            params={"content": "开会"},
        )
        assert action.dedupe_key == key
        from app.repositories import action_repository

        record = action_repository.get_record(action.id)
        record.status = "failed"
        action_repository.save_record(record)
        import asyncio

        asyncio.run(manager.retry(action.id))
        reloaded = manager.query(action.id)
        assert reloaded.dedupe_key == key


class TestMappings:
    def test_tool_execution_projection(self):
        execution = SimpleNamespace(
            status="succeeded",
            error=None,
            result={"payload": {"memory_id": "m9", "note": "saved"}},
        )
        result = result_service.from_tool_execution(execution, action_id="t1")
        assert result.status == "succeeded"
        assert result.output["memory_id"] == "m9"
        assert result.observations["memory_id"] == "m9"
        assert result.metadata["source"] == "tool"

    def test_tool_denied_permanent(self):
        execution = SimpleNamespace(status="denied", error="no", result=None)
        result = result_service.from_tool_execution(execution, action_id="t2")
        assert result.status == "failed"
        assert result.failure_kind == "permanent"

    def test_plan_step_outcome_mapping(self):
        outcome = SimpleNamespace(status="succeeded", error=None, output={"plan": "ok"})
        result = result_service.from_plan_step_outcome(outcome, action_id="p1")
        assert result.status == "succeeded"
        assert result.output["plan"] == "ok"
        assert result.metadata["source"] == "plan_step"

    def test_capability_legacy_failure_kind_stripped_from_output(self):
        result = result_service.from_capability_result(
            CapabilityResult(
                status="failed", payload={"failure_kind": "permanent", "x": 1}
            ),
            action_id="a5",
        )
        assert "failure_kind" not in result.output
        assert result.failure_kind == "permanent"


class TestLegacyDualWrite:
    def test_dual_write_includes_legacy_keys(self):
        result = ActionResult(
            id="res_9",
            action_id="act_9",
            status="succeeded",
            output={"world_event_id": "evt_9", "memory_id": "mem_9"},
            failure_kind=None,
        )
        payload = result.dual_write_legacy_keys()
        assert payload["world_event_id"] == "evt_9"
        assert payload["memory_id"] == "mem_9"
        assert payload["status"] == "succeeded"

    def test_feedback_payload_kinds(self):
        result = ActionResult(
            status="succeeded",
            effects=[
                ActionEffect(kind="world", ref="w"),
                ActionEffect(kind="memory", ref="m"),
            ],
        )
        payload = result_service.feedback_payload(result)
        assert set(payload["feedback_kinds"]) == {"world", "memory"}


class TestFlagOffBehavior:
    def test_flag_off_result_has_three_legacy_statuses_only_produced(self):
        result = result_service.from_capability_result(
            CapabilityResult(status="succeeded"),
            action_id="f1",
        )
        assert result.status in ("succeeded", "failed", "partial")
