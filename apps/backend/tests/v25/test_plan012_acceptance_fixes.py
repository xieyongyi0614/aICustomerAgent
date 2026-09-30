"""验收修复回归（v25 去门控语义反转）：执行桥挂载 / 调度与重规划常开 / 终态广播常开。

对应 Acceptance Report P1 的语义反转收口：
1. `PlanExecutorBridge` 进入 `life_loop._step_goal_advance` 生产执行路径（原已钉住，保留）
2. 原「四个子闸有真实行为门控」的前提随开关删除消失——分派 / 就绪步 / 重规划 / 广播
   均转常开，本模块改钉常开形态；原 flag-off 负例按纪律退役。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application import life_loop
from app.core.settings import get_settings
from app.models.plan import PlanStepOutcome
from app.repositories import goal_repository
from app.services.goal import execution as goal_execution
from app.services.goal import planning as goal_planning
from app.services.planning import observer as observer_mod
from app.services.planning.executor_bridge import PlanExecutorBridge

from .conftest import V25_NOW, V25_USER


@pytest.fixture
def plan_path_on(override_settings):
    """执行链锚点（历史名保留）：子闸已删，只钉行动与世界面。"""
    override_settings(
        observability_persist_enabled="false")


@pytest.fixture
def execution_on(override_settings):
    """行动面开启（执行桥即唯一执行路径，无 flag 分派）。"""
    override_settings(
        observability_persist_enabled="false")


class TestExecutionBridgeIsMounted:
    """P1-1：步骤执行恒走 `PlanExecutorBridge.execute_step`。"""

    @pytest.mark.asyncio
    async def test_step_execution_uses_the_bridge(
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

        assert calls, "执行必须调用 PlanExecutorBridge.execute_step"
        assert legacy == []
        assert result["plan_execute"]["steps"] == 1
        assert result["plan_execute"]["outcomes"] == ["succeeded"]
        stored = goal_repository.get_latest_plan(goal.id)
        assert stored is not None


class TestSchedulerPathIsLive:
    """P1-2a 语义反转：就绪步恒取自 `PlanScheduler`（legacy 回退已删）。"""

    def test_current_step_uses_plan_scheduler(self, monkeypatch):
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
        assert (
            life_loop._current_plan_step(SimpleNamespace(), plan, get_settings())
            is None
        )
        assert called == ["scheduler"]


class TestRevisionIsAlwaysEvaluated:
    """P1-2b 语义反转：执行后恒经 `PlanRevisionPolicy` 裁决并入队 TRIGGER_REPLAN。"""

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


class TestWorldFeedbackIsAlwaysOn:
    """P1-2c 语义反转：映射表内的终态恒广播（子闸 off 负例已退役）。"""

    def test_broadcast_happens_for_mapped_outcomes(
        self, db_session_factory, override_settings, make_goal, monkeypatch
    ):
        called: list = []
        monkeypatch.setattr(
            observer_mod.event_bridge,
            "register_goal_event",
            lambda *a, **k: called.append(a) or True,
        )
        goal = make_goal(user_id=V25_USER, description="要广播")
        assert observer_mod.broadcast_goal_terminal(goal, "completed") is True
        assert len(called) == 1

    def test_unmapped_outcomes_stay_silent(self, db_session_factory, make_goal, monkeypatch):
        called: list = []
        monkeypatch.setattr(
            observer_mod.event_bridge,
            "register_goal_event",
            lambda *a, **k: called.append(a) or True,
        )
        goal = make_goal(user_id=V25_USER, description="不广播")
        assert observer_mod.broadcast_goal_terminal(goal, "failed") is False
        assert called == []


class TestGatesStayGone:
    """四个子闸在 settings 与生产代码中都必须保持消失（防门控回潮）。"""

    def test_flags_are_gone_from_settings_and_production(self):
        from pathlib import Path

        from app.core.settings import Settings

        removed = (
            "plan_scheduler_enabled",
            "plan_execution_enabled",
            "plan_revision_enabled",
            "plan_world_feedback_enabled",
        )
        for name in removed:
            assert name not in Settings.model_fields, name
        app_root = Path(life_loop.__file__).parents[1]
        for path in app_root.rglob("*.py"):
            if "core/settings" in str(path):
                continue
            text = path.read_text(encoding="utf-8")
            for name in removed:
                assert name not in text, f"{name} 残留于 {path}"
