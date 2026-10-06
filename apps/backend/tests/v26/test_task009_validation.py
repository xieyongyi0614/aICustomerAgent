"""TASK-009 V2.6.0 验收：生命周期 / 失败场景 / Flag 矩阵 / 六原则 / 六风险。"""

import asyncio
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core import timeutil
from app.core.settings import Settings, SettingsError, get_settings
from app.models.action import (
    ACTION_EXECUTION_MAP,
    ACTION_TYPES,
    Action,
    ActionResult,
    transition_action,
)
from app.services.action import contracts, integration, manager, result as result_service, scheduler


class TestLifecycle:
    def _set_status(self, action_id: str, status: str) -> None:
        from app.repositories import action_repository

        record = action_repository.get_record(action_id)
        record.status = status
        action_repository.save_record(record)

    def test_created_to_cancelled(self):
        action = manager.create(user_id="u_lc", action_type="create_reminder", params={"content": "a"})
        assert manager.get_status(action.id) == "created"
        assert manager.cancel(action.id, reason="user") is True
        assert manager.get_status(action.id) == "cancelled"

    def test_failed_to_succeeded_via_retry(self):
        action = manager.create(
            user_id="u_lc2",
            action_type="remember_fact",
            params={"fact": "x"},
        )
        self._set_status(action.id, "failed")
        result = asyncio.run(manager.retry(action.id))
        assert result is not None
        assert manager.get_status(action.id) == "succeeded"

    def test_terminal_out_degree_zero(self):
        for status in ("succeeded", "cancelled"):
            for event in (
                "gate_pass",
                "execute_start",
                "step_all_succeeded",
                "cancel_requested",
            ):
                assert transition_action(status, event) is None

    def test_success_path(self):
        assert transition_action("created", "gate_pass") == "planned"
        assert transition_action("planned", "execute_start") == "executing"
        assert transition_action("executing", "step_all_succeeded") == "succeeded"


class TestFailureScenarios:
    def _set_status(self, action_id: str, status: str) -> None:
        from app.repositories import action_repository

        record = action_repository.get_record(action_id)
        record.status = status
        action_repository.save_record(record)

    def test_retry_max_attempts(self):
        action = manager.create(
            user_id="u_fr",
            action_type="create_reminder",
            params={"content": "max"},
        )
        self._set_status(action.id, "failed")
        first = asyncio.run(manager.retry(action.id))
        assert first is not None
        self._set_status(action.id, "failed")
        second = asyncio.run(manager.retry(action.id))
        assert second is None

    def test_idempotent_dedupe(self):
        a = manager.create(user_id="u_id", action_type="remember_fact", params={"fact": "dup"})
        b = manager.create(user_id="u_id", action_type="remember_fact", params={"fact": "dup"})
        assert a.dedupe_key == b.dedupe_key

    def test_partial_keeps_effects(self):
        result = ActionResult(
            status="partial",
            effects=[__import__("app.models.action", fromlist=["ActionEffect"]).ActionEffect(kind="world", ref="w1")],
        )
        assert len(result.effects) == 1
        assert not result_service.classify_retryable(result)

    def test_timeout_maps_timeout(self):
        from app.models.action import CapabilityResult

        result = result_service.from_capability_result(
            CapabilityResult(status="timeout", error="t", payload={"failure_kind": "timeout"}),
            action_id="t",
        )
        # v26 去门控语义反转：timeout 语义恒生效（原 gate-off 退化为 failed 的分支已删）。
        assert result.status == "timeout"
        assert result.failure_kind == "timeout"


class TestFlagMatrix:
    """v26 去门控语义反转：Flag 矩阵随开关删除退役，改钉「字段已删 + 恒投影」。"""

    def test_removed_flags_are_absent(self):
        from app.core.settings import Settings

        for flag in (
            "action_execution_enabled",
            "action_scheduler_enabled",
            "action_result_enabled",
            "action_feedback_enabled",
            "action_debug_enabled",
        ):
            assert flag not in Settings.model_fields, flag

    def test_schedule_step_always_runs(self):
        import asyncio

        result = asyncio.run(scheduler.step_action_schedule(timeutil.now()))
        assert result["status"] == "done"


class TestDesignPrinciples:
    def test_g1_action_independent_abstraction(self):
        action = Action(id="g1", type="query_environment", parameters={"scope": "all"})
        assert action.type and action.status == "created"
        assert action.goal_id is None
        source = open(
            __import__("app.models.action", fromlist=["__file__"]).__file__,
            encoding="utf-8",
        ).read()
        assert "app.repositories" not in source
        assert "app.services" not in source

    def test_g2_planning_no_execute_in_bridge_surface(self):
        import app.services.action.integration as mod

        src = open(mod.__file__, encoding="utf-8").read()
        assert "ActionExecutor(" not in src

    def test_g3_executor_no_decision(self):
        import app.services.action.executor as mod

        src = open(mod.__file__, encoding="utf-8").read()
        assert "decision_pipeline" not in src
        assert "autonomy_policy" not in src

    def test_g4_tool_is_extension(self):
        assert ACTION_EXECUTION_MAP["send_notification"] == "external"
        assert set(ACTION_EXECUTION_MAP) == set(ACTION_TYPES)

    def test_g5_all_executions_produce_result(self):
        executor_mod = __import__(
            "app.services.action.executor", fromlist=["ActionExecutor"]
        )
        from app.services.action.registry import get_capability_registry

        executor = executor_mod.ActionExecutor(get_capability_registry())
        action = Action(id="g5", type="send_notification", parameters={"content": "x"})
        ctx = __import__(
            "app.services.action.registry", fromlist=["ExecutionContext"]
        ).ExecutionContext(
            user_id="u", character_id="asuna", record_id="g5", now=None, settings=None
        )
        result = asyncio.run(executor.run(action, ctx))
        assert isinstance(result, ActionResult)

    def test_g6_result_supports_feedback(self):
        result = ActionResult(
            status="succeeded",
            effects=[
                __import__("app.models.action", fromlist=["ActionEffect"]).ActionEffect(
                    kind="world", ref="w"
                )
            ],
            output={"world_event_id": "w"},
        )
        payload = result_service.feedback_payload(result)
        assert "feedback_kinds" in payload
        assert payload["world_event_id"] == "w"

    def test_g7_schedulable(self):
        action = manager.create(user_id="u_g7", action_type="create_reminder", params={"content": "s"})
        item = scheduler.schedule(action, when="delay", delay=timedelta(minutes=5))
        assert item.when_type == "delay"

    def test_g8_zero_new_infra(self):
        from app.core.db import ActionRecordRow, ActionScheduleRow

        assert ActionRecordRow.__tablename__ == "action_records"
        assert ActionScheduleRow.__tablename__ == "action_schedules"

    def test_g9_legacy_dual_write_window(self):
        result = ActionResult(
            status="succeeded",
            output={"world_event_id": "evt", "memory_id": "mem"},
            failure_kind="transient",
        )
        payload = result.dual_write_legacy_keys()
        assert payload["world_event_id"] == "evt"
        assert payload["memory_id"] == "mem"
        assert payload["legacy_failure_kind"] == "transient"


class TestRiskClosure:
    def test_r1_partial_no_rollback(self):
        result = ActionResult(status="partial", effects=[])
        assert result.status == "partial"
        assert result_service.classify_retryable(result) is False

    def test_r2_legacy_keys_dual_written(self):
        payload = ActionResult(
            status="failed",
            output={"memory_id": "m"},
            failure_kind="permanent",
        ).dual_write_legacy_keys()
        assert "memory_id" in payload and "legacy_failure_kind" in payload

    def test_r3_schedule_unique(self):
        action = manager.create(user_id="u_r3", action_type="create_reminder", params={"content": "u"})
        scheduler.schedule(action, when="delay", delay=timedelta(minutes=1))
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            scheduler.schedule(action, when="delay", delay=timedelta(minutes=2))

    def test_r4_action_fields_minimal(self):
        fields = set(Action.model_fields)
        assert fields == {
            "id",
            "type",
            "target",
            "parameters",
            "priority",
            "status",
            "result",
            "created_at",
            "scheduled_at",
            "executed_at",
            "source",
            "goal_id",
            "plan_step",
            "dedupe_key",
            "run_id",
        }

    def test_r5_feedback_payload_bounded(self):
        result = ActionResult(status="succeeded", effects=[])
        payload = result_service.feedback_payload(result)
        assert len(payload) < 20

    def test_r6_unique_new_table(self):
        from app.core.db import Base

        tables = set(Base.metadata.tables)
        assert "action_schedules" in tables
        assert "actions" not in tables
        assert "action_results" not in tables


class TestOutstandingQuestions:
    def test_q1_partial_recorded_not_rolled_back(self):
        result = ActionResult(
            status="partial",
            effects=[
                __import__("app.models.action", fromlist=["ActionEffect"]).ActionEffect(
                    kind="world", ref="done_part"
                )
            ],
        )
        routed = integration.route_effects(result)
        assert len(routed["world"]) == 1

    def test_q2_cron_is_next_moment_only(self):
        action = manager.create(user_id="u_q2", action_type="create_reminder", params={"content": "c"})
        item = scheduler.schedule(action, when="cron")
        assert item.when_type == "cron"
        assert item.scheduled_at > timeutil.now()

    def test_q4_external_reserved(self):
        from app.services.action.executor import ActionExecutor
        from app.services.action.registry import ExecutionContext, get_capability_registry

        executor = ActionExecutor(get_capability_registry())
        result = asyncio.run(
            executor.execute_external(
                Action(id="q4", type="send_notification"),
                ExecutionContext(user_id="u", character_id="asuna", record_id="q4", now=None, settings=None),
            )
        )
        assert result.failure_kind == "unavailable"

    def test_q5_mcp_mapping_reserved_via_execution_kind(self):
        assert ACTION_EXECUTION_MAP["query_search"] == "tool"


class TestContractsAndObserve:
    def test_contracts_frozen(self):
        assert all(contracts.freeze_contracts().values())

    def test_no_external_rest_for_execution_layer(self):
        from app.api.v1.action_execution import action_execution_router

        paths = [getattr(r, "path", "") for r in action_execution_router.routes]
        assert all(p.startswith("/debug/action-execution") for p in paths)
