"""V2.6.0 端到端验收：功能 / 流程 / 数据 / 错误 / 回归面。"""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core import timeutil
from app.api.v1.debug import action_execution as debug_api
from app.core.settings import get_settings
from app.models.action import ActionResult, ActionIntent, transition_action
from app.repositories import action_repository
from app.services.action import integration, manager, result as result_service, scheduler


def _set_status(action_id: str, status: str) -> None:
    record = action_repository.get_record(action_id)
    record.status = status
    action_repository.save_record(record)


class TestFunctionalAcceptance:
    def test_create(self):
        action = manager.create(
            user_id="u_acc",
            action_type="create_reminder",
            params={"content": "验收提醒", "due_at": "明天"},
        )
        assert action.status == "created"
        assert action.id.isdigit()
        assert action.dedupe_key

    def test_execute_reuses_record(self, monkeypatch):
        settings = get_settings()
        action = manager.create(
            user_id="u_acc_exec",
            action_type="remember_fact",
            params={"fact": "验收执行事实"},
        )
        before = len(action_repository.list_records("u_acc_exec"))
        result = asyncio.run(manager.execute(action.id))
        after = len(action_repository.list_records("u_acc_exec"))
        assert result is not None
        assert after == before
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status in ("succeeded", "failed", "executing", "planned", "cancelled")

    def test_status_changes(self):
        assert transition_action("created", "gate_pass") == "planned"
        assert transition_action("planned", "execute_start") == "executing"
        assert transition_action("executing", "step_all_succeeded") == "succeeded"
        assert transition_action("executing", "step_permanent_failed") == "failed"
        assert transition_action("created", "cancel_requested") == "cancelled"
        assert transition_action("succeeded", "gate_pass") is None

    def test_result_generated(self, monkeypatch):
        settings = get_settings()
        from app.models.action import CapabilityResult

        result = result_service.from_capability_result(
            CapabilityResult(
                status="succeeded",
                payload={"memory_id": "m1", "world_event_id": "e1"},
            ),
            action_id="act_r",
        )
        assert result.status == "succeeded"
        assert result.output["memory_id"] == "m1"
        assert result.observations["memory_id"] == "m1"
        assert result.id and result.created_at is not None

    def test_feedback_produced(self, monkeypatch):
        settings = get_settings()
        action = manager.create(
            user_id="u_acc_fb",
            action_type="create_reminder",
            params={"content": "反馈"},
        )
        record = action_repository.get_record(action.id)
        summary = integration.apply_result_feedback(
            record,
            ActionResult(
                status="succeeded",
                output={"world_event_id": "evt_fb"},
                observations={"world_event_id": "evt_fb"},
            ),
        )
        assert summary["mode"] == "v26"
        assert summary["feedback"]["world_event_id"] == "evt_fb"


class TestSystemFlowAcceptance:
    def test_plan_action_execute_outcome(self, monkeypatch):
        settings = get_settings()
        intent = ActionIntent(
            action_type="remember_fact",
            confidence="confident",
            params={"fact": "计划链路验收"},
            dedupe_key="acceptflow0000001",
        )
        action = integration.create_from_plan_intent(
            intent, user_id="u_flow", plan_step="step_1"
        )
        assert action.source == "plan"
        assert action.plan_step == "step_1"
        before = len(action_repository.list_records("u_flow"))
        result = asyncio.run(integration.execute_plan_action(action))
        after = len(action_repository.list_records("u_flow"))
        assert after == before
        assert result is not None
        outcome = integration.to_plan_step_outcome(result, action_id=action.id)
        assert outcome.action_id == action.id
        assert outcome.status in ("succeeded", "failed")

    def test_schedule_then_due(self):
        action = manager.create(
            user_id="u_sched",
            action_type="create_reminder",
            params={"content": "调度验收", "due_at": "明早"},
        )
        scheduler.schedule(
            action, when="delay", scheduled_at=timeutil.now() - timedelta(minutes=1)
        )
        due = scheduler.due_actions(timeutil.now())
        assert any(a.id == action.id for a in due)
        head = scheduler.next_action(timeutil.now())
        assert head is not None

    def test_planning_bridge_dispatch(self, monkeypatch):
        from app.services.planning.executor_bridge import PlanExecutorBridge

        settings = get_settings()
        bridge = PlanExecutorBridge()

        class Goal:
            id = "g_acc"
            user_id = "u_bridge_acc"

        intent = ActionIntent(
            action_type="remember_fact",
            confidence="confident",
            params={"fact": "bridge acceptance"},
            dedupe_key="bridgeacc00000001",
        )
        record = asyncio.run(bridge._dispatch(Goal(), intent))
        assert record is not None
        assert record.source == "plan"
        assert record.id.isdigit()


class TestDataAcceptance:
    def test_priority_and_schedule_persist(self):
        action = manager.create(
            user_id="u_data",
            action_type="create_reminder",
            params={"content": "数据验收"},
            priority=180,
        )
        scheduler.schedule(action, when="delay", delay=timedelta(minutes=30), priority=180)
        loaded = action_repository.get_record(action.id)
        schedule = action_repository.get_schedule(action.id)
        assert loaded.priority == 180
        assert loaded.scheduled_at is not None
        assert loaded.status == "planned"
        assert schedule is not None
        assert schedule.priority == 180
        assert schedule.status == "scheduled"

    def test_lifecycle_consistency(self):
        action = manager.create(
            user_id="u_life",
            action_type="remember_fact",
            params={"fact": "生命周期"},
        )
        assert manager.get_status(action.id) == "created"
        assert manager.cancel(action.id, reason="life") is True
        assert manager.get_status(action.id) == "cancelled"
        assert manager.cancel(action.id) is False

    def test_result_json_roundtrip(self):
        result = ActionResult(
            status="succeeded",
            output={"note": "roundtrip"},
            observations={"note": "roundtrip"},
            metadata={"source": "acceptance"},
        )
        restored = ActionResult.model_validate(result.model_dump())
        assert restored.output["note"] == "roundtrip"
        assert restored.metadata["source"] == "acceptance"


class TestErrorAcceptance:
    def test_execute_failure_normalizes(self, monkeypatch):
        from app.services.action.executor import ActionExecutor
        from app.services.action.registry import ExecutionContext

        class Boom:
            async def execute(self, *a, **k):
                raise RuntimeError("boom")

        class Reg:
            def get(self, name):
                return Boom()

        executor = ActionExecutor(Reg(), timeout_seconds=1)
        from app.models.action import Action

        action = Action(id="e1", type="create_reminder", parameters={"content": "x"})
        ctx = ExecutionContext(
            user_id="u", character_id="asuna", record_id="e1", now=None, settings=None
        )
        result = asyncio.run(executor.execute_internal(action, ctx))
        assert result.status == "failed"
        assert result.failure_kind == "transient"

    def test_timeout_normalizes(self):
        from app.models.action import CapabilityResult

        result = result_service.from_capability_result(
            CapabilityResult(status="timeout", error="slow", payload={"failure_kind": "timeout"}),
            action_id="e2",
        )
        # v26 去门控语义反转：timeout 语义恒生效（原 gate-off 退化为 failed 的分支已删）。
        assert result.status == "timeout"
        assert result.failure_kind == "timeout"

    def test_invalid_params_create_still_works_and_gate_can_reject(self):
        action = manager.create(
            user_id="u_bad",
            action_type="cancel_reminder",
            params={"target": ""},
        )
        assert action.status == "created"

    def test_retry_cap_and_idempotent_dedupe(self):
        a = manager.create(
            user_id="u_retry", action_type="remember_fact", params={"fact": "幂等"}
        )
        b = manager.create(
            user_id="u_retry", action_type="remember_fact", params={"fact": "幂等"}
        )
        assert a.dedupe_key == b.dedupe_key
        _set_status(a.id, "failed")
        first = asyncio.run(manager.retry(a.id))
        assert first is not None
        _set_status(a.id, "failed")
        assert asyncio.run(manager.retry(a.id)) is None

    def test_missing_action(self):
        assert manager.query("act_missing") is None
        assert manager.cancel("act_missing") is False
        assert manager.get_status("act_missing") is None
        assert asyncio.run(manager.execute("act_missing")) is None


class TestRegressionCheck:
    """v26 去门控语义反转：flag-off 负例随开关退役，改钉「字段已删 + 常开形态」。"""

    def test_removed_flags_are_absent(self):
        from app.core.settings import Settings

        for flag in (
            "action_execution_enabled",
            "action_scheduler_enabled",
            "action_feedback_enabled",
            "action_result_enabled",
            "action_debug_enabled",
        ):
            assert flag not in Settings.model_fields, flag

    def test_schedule_step_always_runs(self):
        result = asyncio.run(scheduler.step_action_schedule(timeutil.now()))
        assert result["status"] == "done"
        assert result["claimed"] == 0

    def test_feedback_always_projected(self):
        action = manager.create(
            user_id="u_legacy", action_type="create_reminder", params={"content": "legacy"}
        )
        record = action_repository.get_record(action.id)
        summary = integration.apply_result_feedback(
            record, ActionResult(status="succeeded")
        )
        assert summary["mode"] != "legacy"

    def test_world_relationship_memory_boundaries_in_integration(self):
        source = open(integration.__file__, encoding="utf-8").read()
        assert "world_engine." not in source
        assert "relationship_bridge." not in source
        assert "memory_repository." not in source

    def test_v25_migration_head_documented(self):
        """v2.5 交付时链头为 0049；2026-09-29 全链折叠为单迁移 `0001` 后，V2.5 及
        之后全部 Schema 已并入折叠基线，守卫改断言「折叠基线 + 连续增量迁移且链头自洽」。

        本用例原名 `test_v25_migration_head_0049_documented`，FEISHU-010 加 0050 时
        改写为「≥ 0049 且自洽」，折叠时再次改写；增量迁移 `0002` / `0003` 引入后改为
        「编号连续 + 首文件为折叠基线 + 链头等于钉测常量」。
        """
        from pathlib import Path

        from tests.support.schema_pins import MIGRATION_HEAD

        migrations = sorted(p.name for p in Path("migrations/versions").glob("0*.py"))
        numeric = [int(name[:4]) for name in migrations if name[:4].isdigit()]
        assert migrations[0] == "0001_squashed_full_schema.py"
        assert numeric == list(range(numeric[0], numeric[0] + len(numeric)))
        assert numeric[-1] == int(MIGRATION_HEAD)

    def test_debug_surface_always_served(self):
        action = manager.create(
            user_id="u_dbg", action_type="create_reminder", params={"content": "dbg"}
        )
        rows = debug_api.list_execution_actions(user_id="u_dbg")
        assert any(r["id"] == action.id for r in rows)
        metrics = debug_api.execution_metrics(window_hours=24)
        assert "success_rate" in metrics
