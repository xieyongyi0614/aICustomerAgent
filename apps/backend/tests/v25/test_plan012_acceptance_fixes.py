"""验收修复回归：执行桥挂载 / 调度与重规划子闸 / 世界反馈子闸（P1 修复验证）。

对应 Acceptance Report P1：
1. `PlanExecutorBridge` 进入 `life_loop._step_goal_advance` 生产执行路径
2. `plan_scheduler_enabled` / `plan_execution_enabled` /
   `plan_revision_enabled` / `plan_world_feedback_enabled` 有真实行为门控
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application import life_loop
from app.core.settings import get_settings
from app.models.plan import PlanStepOutcome
from app.repositories import goal_repository
from app.services import goal_execution, goal_planning
from app.services.planning import observer as observer_mod
from app.services.planning.executor_bridge import PlanExecutorBridge

from .conftest import V25_NOW, V25_USER


@pytest.fixture
def plan_path_on(override_settings):
    override_settings(
        planning_enabled="true",
        plan_observation_enabled="true",
        plan_scheduler_enabled="true",
        plan_execution_enabled="true",
        plan_revision_enabled="true",
        plan_world_feedback_enabled="true",
        tool_system_enabled="true",
        action_enabled="true",
        world_enabled="false",
        observability_persist_enabled="false")


@pytest.fixture
def execution_on(override_settings):
    """执行桥 on、观测与调度 off：验证分派不受无关子闸影响。"""
    override_settings(
        planning_enabled="true",
        plan_execution_enabled="true",
        plan_scheduler_enabled="false",
        plan_observation_enabled="false",
        action_enabled="true",
        world_enabled="false",
        observability_persist_enabled="false")


class TestExecutionBridgeIsMounted:
    """P1-1：Flag on 时步骤执行走 `PlanExecutorBridge.execute_step`。"""

    @pytest.mark.asyncio
    async def test_execution_flag_on_uses_the_bridge(
        self, db_session_factory, execution_on, make_goal, make_plan, monkeypatch
    ):
        calls: list = []

        async def _fake_execute(_self, goal, plan, step, ctx):
            calls.append((goal.id, step.index, ctx.now))
            return PlanStepOutcome(
                step_index=step.index,
                status="succeeded",
                at=V25_NOW,
                tool_id=step.tool_id or "",
                action_id="act-bridge",
            )

        monkeypatch.setattr(PlanExecutorBridge, "execute_step", _fake_execute)
        legacy: list = []
        monkeypatch.setattr(
            goal_execution,
            "attempt_current_step",
            AsyncMock(side_effect=lambda *a, **k: legacy.append(a) or {"status": "legacy"}),
        )

        goal = make_goal(user_id=V25_USER, description="执行桥挂载目标")
        make_plan(goal.id)
        result = await life_loop._step_goal_advance(V25_USER, V25_NOW)

        assert calls, "执行子闸 on 时必须调用 PlanExecutorBridge.execute_step"
        assert legacy == []
        assert result["plan_execute"]["steps"] == 1
        assert result["plan_execute"]["outcomes"] == ["succeeded"]
        stored = goal_repository.get_latest_plan(goal.id)
        assert stored is not None

    @pytest.mark.asyncio
    async def test_execution_flag_off_keeps_legacy_path(
        self, db_session_factory, override_settings, make_goal, make_plan, monkeypatch
    ):
        override_settings(
            action_enabled="true",
            world_enabled="false",
            observability_persist_enabled="false")
        monkeypatch.setattr(
            PlanExecutorBridge,
            "execute_step",
            AsyncMock(side_effect=AssertionError("不应走执行桥")),
        )
        legacy: list = []
        monkeypatch.setattr(
            goal_execution,
            "attempt_current_step",
            AsyncMock(side_effect=lambda *a, **k: legacy.append(1) or {"status": "legacy"}),
        )
        goal = make_goal(user_id=V25_USER, description="原路径执行")
        make_plan(goal.id)
        result = await life_loop._step_goal_advance(V25_USER, V25_NOW)
        assert legacy == [1]
        assert "plan_execute" not in result

    def test_master_flag_off_leaves_execution_child_inert(
        self, monkeypatch
    ):
        monkeypatch.setenv("PLANNING_ENABLED", "false")
        monkeypatch.setenv("PLAN_EXECUTION_ENABLED", "true")
        monkeypatch.setenv("ACTION_ENABLED", "true")
        get_settings.cache_clear()
        try:
            assert life_loop._plan_execution_enabled(get_settings()) is False
        finally:
            get_settings.cache_clear()


class TestSchedulerFlagIsLive:
    """P1-2a：`plan_scheduler_enabled` 决定就绪步来源。"""

    def test_scheduler_on_uses_plan_scheduler(self, monkeypatch):
        monkeypatch.setenv("PLANNING_ENABLED", "true")
        monkeypatch.setenv("PLAN_SCHEDULER_ENABLED", "true")
        get_settings.cache_clear()
        called: list = []
        monkeypatch.setattr(
            life_loop.plan_scheduler.PlanScheduler,
            "current_step",
            staticmethod(lambda plan: called.append("scheduler") or None),
        )
        monkeypatch.setattr(
            life_loop.goal_observation,
            "_current_step",
            lambda specs: called.append("legacy") or None,
        )
        plan = SimpleNamespace(sub_goals=[])
        try:
            assert (
                life_loop._current_plan_step(SimpleNamespace(), plan, get_settings())
                is None
            )
        finally:
            get_settings.cache_clear()
        assert called == ["scheduler"]

    def test_scheduler_off_falls_back_to_legacy(self, monkeypatch):
        called: list = []
        monkeypatch.setattr(
            life_loop.plan_scheduler.PlanScheduler,
            "current_step",
            staticmethod(lambda plan: called.append("scheduler") or None),
        )
        monkeypatch.setattr(
            life_loop.goal_observation,
            "_current_step",
            lambda specs: called.append("legacy") or None,
        )
        plan = SimpleNamespace(sub_goals=[])
        settings = get_settings()
        assert life_loop._current_plan_step(SimpleNamespace(), plan, settings) is None
        assert called == ["legacy"]


class TestRevisionFlagIsLive:
    """P1-2b：`plan_revision_enabled` on 时执行后入队 TRIGGER_REPLAN。"""

    @pytest.mark.asyncio
    async def test_exhausted_attempt_enqueues_replan(
        self, db_session_factory, plan_path_on, make_goal, make_plan, monkeypatch
    ):
        goal = make_goal(user_id=V25_USER, description="重规划触发目标")
        plan = make_plan(
            goal.id,
            specs=[
                {
                    "index": 1,
                    "description": "会失败的步骤",
                    "capability": "create_reminder",
                    "params": {"content": "x"},
                    "criteria": {
                        "type": "action_succeeded",
                        "capability": "create_reminder",
                    },
                    "on_failure": "replan",
                    "attempt_count": 1,
                    "tool_id": "builtin.reminder.create",
                }
            ],
        )
        async def _fail_execute(_self, goal, plan, step, ctx):
            return PlanStepOutcome(
                step_index=step.index, status="failed", at=V25_NOW, action_id="act-f"
            )

        monkeypatch.setattr(PlanExecutorBridge, "execute_step", _fail_execute)
        enqueued: list = []
        monkeypatch.setattr(
            goal_planning,
            "enqueue_planning",
            lambda user_id, goal_id, trigger, **kw: enqueued.append(
                (user_id, goal_id, trigger)
            )
            or True,
        )

        await life_loop._step_goal_advance(V25_USER, V25_NOW)
        assert any(
            item[2] == goal_planning.TRIGGER_REPLAN for item in enqueued
        ), f"未触发重规划入队：{enqueued}"
        stored = goal_repository.get_latest_plan(goal.id)
        assert stored is not None
        assert stored.sub_goals[0].attempt_count >= 1

    @pytest.mark.asyncio
    async def test_revision_flag_off_does_not_enqueue(
        self, db_session_factory, execution_on, make_goal, make_plan, monkeypatch
    ):
        goal = make_goal(user_id=V25_USER, description="重规划关闭")
        make_plan(goal.id)

        async def _fail_execute(_self, goal, plan, step, ctx):
            return PlanStepOutcome(
                step_index=step.index, status="failed", at=V25_NOW, action_id="act-f"
            )

        monkeypatch.setattr(PlanExecutorBridge, "execute_step", _fail_execute)
        enqueued: list = []
        monkeypatch.setattr(
            goal_planning,
            "enqueue_planning",
            lambda *a, **k: enqueued.append(a) or True,
        )
        await life_loop._step_goal_advance(V25_USER, V25_NOW)
        assert enqueued == []


class TestWorldFeedbackFlagIsLive:
    """P1-2c：`plan_world_feedback_enabled` 门控终态广播。"""

    def test_broadcast_off_when_world_feedback_disabled(
        self, db_session_factory, override_settings, make_goal, monkeypatch
    ):
        override_settings(
            planning_enabled="true",
            plan_world_feedback_enabled="false",
        )
        called: list = []
        monkeypatch.setattr(
            observer_mod.event_bridge,
            "register_goal_event",
            lambda *a, **k: called.append(a) or True,
        )
        goal = make_goal(user_id=V25_USER, description="不广播")
        assert observer_mod.broadcast_goal_terminal(goal, "completed") is False
        assert called == []

    def test_broadcast_on_when_world_feedback_enabled(
        self, db_session_factory, override_settings, make_goal, monkeypatch
    ):
        override_settings(
            planning_enabled="true",
            plan_world_feedback_enabled="true",
        )
        called: list = []
        monkeypatch.setattr(
            observer_mod.event_bridge,
            "register_goal_event",
            lambda *a, **k: called.append(a) or True,
        )
        goal = make_goal(user_id=V25_USER, description="要广播")
        assert observer_mod.broadcast_goal_terminal(goal, "completed") is True
        assert len(called) == 1


class TestFlagConsumptionStatic:
    """四个子闸在生产代码中必须有消费点（防再退化成死开关）。"""

    def test_flags_are_consumed_outside_settings(self):
        from pathlib import Path

        app_root = Path(life_loop.__file__).parents[1]
        hits = {name: [] for name in (
            "plan_scheduler_enabled",
            "plan_execution_enabled",
            "plan_revision_enabled",
            "plan_world_feedback_enabled",
        )}
        for path in app_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in hits:
                if name in text and "settings/plan.py" not in str(path) and "settings/enablement.py" not in str(path):
                    hits[name].append(str(path).replace("\\", "/"))
        for name, files in hits.items():
            assert files, f"{name} 无生产消费点"
            assert any(
                "life_loop.py" in f or "observer.py" in f for f in files
            ), f"{name} 消费点不在 life_loop/observer：{files}"
