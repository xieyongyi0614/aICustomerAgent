"""PLAN-011 Step 4 单测：`loop_runs.steps` 计划子步骤记账验证（§4.2.5 / §9.2 I5 / I6）。

本文件验证**已落地**的记账形态（不新增记账点、不改 `life_loop` 九步序列）：

| 记账位 | 形态 | 承载 |
|---|---|---|
| `plan_assemble` | `loop_run_repository.mark_step` 独立条目 | 引擎 `_record_run_step`（`ctx.run["run_id"]` 存在时） |
| `plan_generate` / `plan_revise` | 同上 | 引擎 `_record_run_step` |
| `plan_observe` | `goal_advance` 阶段条目的**字段** | `life_loop._record_step_async` 把步骤返回值 update 进条目 |

**与 Task Detail §4.2.5 的一处偏差（`plan_execute`）**：Task Detail 命名的三个子步骤为
`plan_assemble` / `plan_execute` / `plan_observe`，而落地形态是「装配 / 生成 / 修订三个独立条目 +
`plan_observe` 字段」。`plan_execute` 在本版本**不存在**且不应存在：PLAN-005 的挂载纪律明确
「不新增维护步、不新增调度循环」（`test_plan005_mount.py::test_no_new_maintenance_step_or_scheduling_loop`
把 `plan_execute` 不出现钉住），步骤执行仍由既有 `goal_observation` / `goal_execution` 阶段承载；
PLAN-003 Task Detail §11.3 已把子步骤名裁决为 `plan_assemble` / `plan_generate` / `plan_revise`。
故本任务按「**验证已落地形态 + 显式否定 `plan_execute`**」交付，不新增记账点（Non-Scope N8）。

预算约束：计划子步骤为 0 LLM（不带 `llm_capable`），故不占用 `life_loop_cycle_llm_budget`；
日额度熔断时按 `status="skipped"` 降级记账（引擎 `_budget_skip`）。
"""

import re
from pathlib import Path

import pytest

from app.application import life_loop
from app.core.settings import get_settings
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.repositories import goal_repository, loop_run_repository
from app.services import life_loop_budget
from app.services.planning import engine as plan_engine

from . import plan011_support as support
from .test_plan005_mount import AUTONOMOUS_TICK_STAGES, LIFE_LOOP_STEPS


@pytest.fixture
def planning_on(override_settings):
    override_settings(
        planning_enabled="true",
        plan_context_enabled="true",
        plan_observation_enabled="true",
        world_enabled="false",
        observability_persist_enabled="false")
    life_loop_budget.reset_cache()
    return True


def _context(goal, run_id: str) -> PlanContext:
    from app.core.settings import get_settings
    from app.services.planning import context as plan_context

    return PlanContext(
        goal=goal,
        tool_surface=ToolSurface(
            run_kind="autonomous_tick", tool_ids=(support.REMINDER_CREATE,)
        ),
        budget=plan_context.plan_budget(get_settings()),
        run={"run_id": run_id, "run_kind": "life_loop", "trigger_type": "schedule"},
    )


def _run_entries(run_id: str) -> list[dict]:
    run = loop_run_repository.get(run_id)
    assert run is not None
    return list(run.steps or [])


def _step_names(run_id: str) -> list[str]:
    return [str(entry.get("step")) for entry in _run_entries(run_id)]


def _new_run(user_id: str = support.USER):
    return loop_run_repository.create_run(
        user_id, kind="autonomy", reason="plan011_verify", run_kind="autonomous_tick"
    )


class TestPlanSubStepAccounting:
    """I5：`plan_assemble` / `plan_observe` 记账正确；`plan_execute` 结构性不存在。"""

    @pytest.mark.asyncio
    async def test_engine_records_assemble_and_generate_entries(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(user_id=support.USER, description="子步骤记账")
        run = _new_run()
        stub_planning_llm(sub_goals=[support.step_spec(1)])

        outcome = await plan_engine.PlanningEngine().plan(
            goal, _context(goal, run.id), trigger="goal_created"
        )

        assert outcome.validated is True
        entries = {entry.get("step"): entry for entry in _run_entries(run.id)}
        assert plan_engine.PLAN_STEP_ASSEMBLE in entries
        assert plan_engine.PLAN_STEP_GENERATE in entries
        assert plan_engine.PLAN_STEP_REVISE not in entries
        assert entries[plan_engine.PLAN_STEP_ASSEMBLE]["goal_id"] == goal.id
        assert entries[plan_engine.PLAN_STEP_ASSEMBLE]["degraded"] == outcome.degraded
        assert entries[plan_engine.PLAN_STEP_GENERATE]["status"] == outcome.status
        assert entries[plan_engine.PLAN_STEP_GENERATE]["steps"] == [1]

    @pytest.mark.asyncio
    async def test_no_run_id_means_zero_accounting(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        """无 `run_id` 的装配（后台 job 形态）不产生子步骤条目——记账不臆造 Run。"""
        goal = make_goal(user_id=support.USER, description="无 Run 不记账")
        run = _new_run()
        stub_planning_llm(sub_goals=[support.step_spec(1)])
        ctx = _context(goal, run.id).model_copy(update={"run": {}})

        await plan_engine.PlanningEngine().plan(goal, ctx, trigger="goal_created")

        assert _run_entries(run.id) == []

    @pytest.mark.asyncio
    async def test_budget_degradation_records_a_skipped_sub_step(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm, monkeypatch
    ):
        """Step 4.2：受既有 `budget_state` 约束——日额度熔断时降级记账（`skipped`）。"""
        goal = make_goal(user_id=support.USER, description="预算降级记账")
        run = _new_run()
        stub_planning_llm(sub_goals=[support.step_spec(1)])
        monkeypatch.setattr(life_loop_budget, "is_degraded", lambda: True)

        outcome = await plan_engine.PlanningEngine().plan(
            goal, _context(goal, run.id), trigger="goal_created"
        )

        assert outcome.status == plan_engine.PLAN_STATUS_SKIPPED
        entries = {entry.get("step"): entry for entry in _run_entries(run.id)}
        assert entries[plan_engine.PLAN_STEP_ASSEMBLE]["step"] == "plan_assemble"
        assert entries[plan_engine.PLAN_STEP_GENERATE]["status"] == "skipped"
        assert entries[plan_engine.PLAN_STEP_GENERATE]["reason"]
        assert goal_repository.count_plans(goal.id) == 0

    @pytest.mark.asyncio
    async def test_observe_lands_as_a_field_of_the_goal_advance_entry(
        self, db_session_factory, planning_on, make_goal, make_plan
    ):
        """I5：`plan_observe` 经既有阶段记录器（`_record_step_async`）进 `loop_runs.steps`。"""
        goal = make_goal(user_id=support.USER, description="观测记账")
        make_plan(goal.id)
        run = _new_run()
        steps: list[dict] = []

        detail = await life_loop._step_goal_advance(support.USER, support.NOW)
        await life_loop._record_step_async(
            run.id, steps, "goal_advance", lambda: _resolved(detail)
        )

        assert detail["plan_observe"]["goals"] == 1
        entries = {entry.get("step"): entry for entry in _run_entries(run.id)}
        assert entries["goal_advance"]["plan_observe"] == detail["plan_observe"]
        assert entries["goal_advance"]["status"] == "ok"
        assert "llm_capable" not in entries["goal_advance"]["plan_observe"]

    @pytest.mark.asyncio
    async def test_plan_execute_is_not_a_recorded_sub_step(
        self, db_session_factory, planning_on, make_goal, make_plan, stub_planning_llm
    ):
        """偏差留痕：`plan_execute` **不存在**（PLAN-005 挂载纪律：不新增维护步 / 不新增调度循环）。"""
        goal = make_goal(user_id=support.USER, description="plan_execute 不存在")
        make_plan(goal.id)
        run = _new_run()
        stub_planning_llm(sub_goals=[support.step_spec(1)])
        await plan_engine.PlanningEngine().plan(
            goal, _context(goal, run.id), trigger="goal_created"
        )
        await life_loop._step_goal_advance(support.USER, support.NOW)

        assert "plan_execute" not in _step_names(run.id)


class TestLifeLoopShapeIsUnchanged:
    """I6：九步阶段序列 / `autonomous_tick` stage 序列 / 签名零差异。"""

    def test_life_loop_still_runs_exactly_the_nine_steps(self):
        source = Path(life_loop.__file__).read_text(encoding="utf-8")
        cycle = source.split("async def _run_user_cycle", 1)[1].split("async def ", 1)[0]
        recorded = re.findall(
            r'_record_step(?:_async)?\(\s*run\.id,\s*steps,\s*"(\w+)"', cycle
        )
        assert tuple(recorded) == LIFE_LOOP_STEPS
        assert "plan_execute" not in cycle

    def test_autonomous_tick_stage_sequence_is_unchanged(self):
        from app.application.agent_runtime import profiles

        spec = profiles.get_profile("autonomous_tick")
        assert spec.stages == AUTONOMOUS_TICK_STAGES

    def test_plan_sub_steps_consume_zero_cycle_llm_budget(self, db_session_factory, planning_on, make_goal, make_plan):
        """预算数学未变：子步骤不带 `llm_capable`，既有周期 LLM 预算不计入计划子步骤。"""
        goal = make_goal(user_id=support.USER, description="零 LLM 记账")
        make_plan(goal.id)
        assert life_loop._cycle_llm_budget_exhausted(
            [
                {"step": "plan_assemble", "status": "ok"},
                {"step": "plan_generate", "status": "ok"},
                {"step": "plan_observe", "status": "ok"},
            ],
            get_settings(),
        ) is False


async def _resolved(detail: dict) -> dict:
    return detail
