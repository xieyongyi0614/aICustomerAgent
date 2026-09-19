"""V2.6.0 Code Review 修复验证：主路径接线 / Flag off 零漂移 / 状态机权威。"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.models.action import ActionResult, ActionIntent, transition_action
from app.repositories import action_repository
from app.services.action import manager, scheduler


class TestActionScheduleConsumption:
    """REF-004/005 消费入口：挂 life_loop 维护步，不进 autonomous_tick Profile。

    裁决（docs/refactor/flag-removal-audit.md F.13）：到期调度认领是维护语义，
    不进自治阶段序列。v26 去门控（批次 7）：双闸自门控已删，挂载点激活（H.4 验证点）。
    """

    def test_scheduler_self_gate_is_gone(self):
        """原「双闸 off 自门控 skipped」的前提随开关删除退役：空载时正常跑完（done）。"""
        result = asyncio.run(scheduler.step_action_schedule(datetime.now()))
        assert result["status"] == "done"
        assert result["claimed"] == 0

    def test_autonomous_profile_has_no_action_schedule_stage(self):
        from app.application.agent_runtime import profiles

        spec = profiles.get_profile("autonomous_tick")
        assert "action_schedule" not in spec.stages

    def test_maintenance_mounts_action_schedule(self):
        import inspect

        from app.application import life_loop

        src = inspect.getsource(life_loop._run_maintenance)
        assert "step_action_schedule" in src
        assert 'step": "action_schedule"' in src or '"action_schedule"' in src
        pending_src = inspect.getsource(life_loop._maintenance_pending)
        assert "action_schedule" in pending_src


class TestStateMachineAuthority:
    def test_manager_update_rejects_status(self):
        action = manager.create(
            user_id="u_sm", action_type="create_reminder", params={"content": "x"}
        )
        with pytest.raises(ValueError):
            manager.update(action.id, status="succeeded")

    def test_cancel_uses_transition(self):
        action = manager.create(
            user_id="u_sm2", action_type="create_reminder", params={"content": "y"}
        )
        assert manager.cancel(action.id) is True
        assert manager.get_status(action.id) == "cancelled"
        assert transition_action("cancelled", "cancel_requested") is None

    def test_action_engine_source_uses_transition_on_failure_path(self):
        from app.application import action_engine

        source = open(action_engine.__file__, encoding="utf-8").read()
        assert "_apply_action_result_to_record" in source
        assert "step_permanent_failed" in source
        assert "step_retryable_failed" in source


class TestManagerExecuteWiring:
    def test_manager_has_execute(self):
        assert callable(manager.execute)

    def test_execute_missing_record_none(self):
        assert asyncio.run(manager.execute("act_missing")) is None

    def test_execute_existing_record_reuses_id(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_enabled", True)
        action = manager.create(
            user_id="u_exec",
            action_type="query_environment",
            params={"scope": "all"},
        )
        result = asyncio.run(manager.execute(action.id))
        assert result is not None
        assert isinstance(result, ActionResult)
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.id == action.id
        assert loaded.source == "conversation"

    def test_execute_plan_source_one_record(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_enabled", True)
        from app.services.action import integration

        intent = ActionIntent(
            action_type="query_environment",
            confidence="confident",
            params={"scope": "all"},
            dedupe_key="planexec00000001",
        )
        action = integration.create_from_plan_intent(
            intent, user_id="u_plan_exec", plan_step="step_1"
        )
        assert action.source == "plan"
        assert action.plan_step == "step_1"
        before = len(action_repository.list_records("u_plan_exec"))
        result = asyncio.run(integration.execute_plan_action(action))
        assert result is not None
        after = len(action_repository.list_records("u_plan_exec"))
        assert after == before


class TestV26ExecutorPath:
    """v26 去门控语义反转：分派辅助已删，执行恒经 ActionExecutor 主路径。"""

    def test_execute_plan_uses_action_executor(self, monkeypatch):
        from app.application import action_engine

        settings = get_settings()
        monkeypatch.setattr(settings, "action_enabled", True)
        action = manager.create(
            user_id="u_v26e",
            action_type="remember_fact",
            params={"fact": "review fix fact"},
        )
        result = asyncio.run(manager.execute(action.id))
        assert result is not None
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        if loaded.status == "cancelled":
            pytest.fail(f"gate/assemble cancelled: {loaded.gate_reason} result={loaded.result}")
        assert loaded.status in ("succeeded", "failed", "executing", "planned")
        assert loaded.id == action.id


class TestSchedulerOwnerAndRecordSync:
    def test_schedule_writes_record_scheduled_at_and_planned(self):
        action = manager.create(
            user_id="u_sch",
            action_type="create_reminder",
            params={"content": "同步", "due_at": "明天"},
        )
        item = scheduler.schedule(action, when="delay", delay=timedelta(minutes=10))
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.scheduled_at is not None
        assert loaded.status == "planned"
        assert item.status == "scheduled"


class TestPlanningBridgeFlagOn:
    def test_dispatch_uses_manager_when_flag_on(self, monkeypatch):
        from app.services.planning.executor_bridge import PlanExecutorBridge

        settings = get_settings()
        monkeypatch.setattr(settings, "action_enabled", True)
        bridge = PlanExecutorBridge()

        class Goal:
            id = "g1"
            user_id = "u_bridge"

        intent = ActionIntent(
            action_type="remember_fact",
            confidence="confident",
            params={"fact": "bridge fact"},
            dedupe_key="bridgekey00000001",
        )
        record = asyncio.run(bridge._dispatch(Goal(), intent))
        assert record is not None
        assert record.source == "plan"
        assert record.id.startswith("act_")
