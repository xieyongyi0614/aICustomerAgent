"""PLAN-003 规划引擎断言：七道闸 / 闸门 5·6 独立开关 / `revise` 语义 / 入队幂等 / 预算。

覆盖 Task Detail §9.1（U8 ~ U10、U13）与 §9.2（I3 ~ I6）；装配面见
`test_plan003_context.py`，挂载与形状快照见 `test_plan003_mount.py`。
"""

import ast
from pathlib import Path

import pytest

from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK, RunContext
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.repositories import background_job_repository, goal_repository, loop_run_repository
from app.services import goal_planning
from app.services.planning import context as plan_context
from app.services.planning import engine as plan_engine

from .conftest import V25_NOW, V25_USER

ENGINE_PATH = Path(plan_engine.__file__)

ON_SURFACE_TOOL = "builtin.reminder.create"
RESOLVABLE_OFF_SURFACE_TOOL = "builtin.search.query"
UNRESOLVABLE_TOOL = "world.object.teleport"

ENGINE_FORBIDDEN_NAMES = (
    "session",
    "SessionLocal",
    "GoalRow",
    "GoalPlanRow",
    "ToolSelector",
    "update",
    "insert",
    "delete",
)


def _step(index: int = 1, **overrides) -> dict:
    spec = {
        "index": index,
        "description": f"步骤{index}",
        "capability": "create_reminder",
        "params": {"content": f"提醒{index}"},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    }
    spec.update(overrides)
    return spec


@pytest.fixture
def planning_on(override_settings):
    override_settings(
        v25_planning_enabled="true",
        v25_plan_context_enabled="true",
        v25_plan_step_binding_enabled="true",
        v24_tool_system_enabled="true",
        world_enabled="false",
        observability_persist_enabled="false")


@pytest.fixture
def engine():
    return plan_engine.PlanningEngine()


def _context(goal, *, tool_ids=(ON_SURFACE_TOOL,), **overrides) -> PlanContext:
    return PlanContext(
        goal=goal,
        tool_surface=ToolSurface(
            run_kind=RUN_KIND_AUTONOMOUS_TICK, tool_ids=tuple(tool_ids)
        ),
        budget=plan_context.plan_budget(_settings()),
        **overrides,
    )


def _settings():
    from app.core.settings import get_settings

    return get_settings()


class TestSevenGates:
    """U8：七道闸各有负例，理由码与 Task Detail §4.2.4 逐条一致；拒绝零异常。"""

    @pytest.mark.asyncio
    async def test_gate1_attempt_cap(
        self, db_session_factory, planning_on, engine, make_goal, override_settings
    ):
        goal = make_goal(description="尝试封顶目标")
        override_settings(v2_autonomy_planning_max_attempts="0")
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.status == plan_engine.PLAN_STATUS_REJECTED
        assert outcome.rejection_reason == plan_engine.REASON_ATTEMPT_CAP
        assert outcome.plan is not None and outcome.plan.status == "rejected"

    @pytest.mark.asyncio
    async def test_gate2_subgoal_count_exceeded(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm, override_settings
    ):
        goal = make_goal(description="步数封顶目标")
        override_settings(v25_plan_max_steps="1")
        stub_planning_llm(sub_goals=[_step(1), _step(2)])
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_COUNT_EXCEEDED

    @pytest.mark.asyncio
    async def test_gate3_invalid_sub_goal_shape(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="形状非法目标")
        stub_planning_llm(sub_goals=[_step(2)])
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_INVALID_SHAPE

    @pytest.mark.asyncio
    async def test_gate4_capability_unaligned(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="能力不对齐目标")
        stub_planning_llm(
            sub_goals=[
                {
                    "index": 1,
                    "description": "瞬移",
                    "capability": "teleport_user",
                    "params": {},
                    "criteria": {"type": "action_succeeded", "capability": "teleport_user"},
                }
            ]
        )
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_CAPABILITY_UNALIGNED

    @pytest.mark.asyncio
    async def test_gate5_tool_unresolvable(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="工具不可解析目标")
        stub_planning_llm(sub_goals=[_step(1, tool_id=UNRESOLVABLE_TOOL)])
        outcome = await engine.plan(
            goal, _context(goal, tool_ids=(UNRESOLVABLE_TOOL,)), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.rejection_reason == plan_engine.REASON_TOOL_UNRESOLVABLE

    @pytest.mark.asyncio
    async def test_gate6_tool_off_surface(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="工具不在面上目标")
        stub_planning_llm(sub_goals=[_step(1, tool_id=RESOLVABLE_OFF_SURFACE_TOOL)])
        outcome = await engine.plan(
            goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.rejection_reason == plan_engine.REASON_TOOL_OFF_SURFACE

    @pytest.mark.asyncio
    async def test_gate7_llm_failed(
        self, db_session_factory, planning_on, engine, make_goal, monkeypatch
    ):
        goal = make_goal(description="LLM 失败目标")

        def _boom(messages, settings):
            raise RuntimeError("LLM 不可用")

        monkeypatch.setattr(goal_planning, "_ask_llm_with_retry", _boom)
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_LLM_FAILED

    def test_reason_codes_match_the_frozen_table(self):
        assert plan_engine.PLANNING_REASONS == (
            "attempt_cap",
            "subgoal_count_exceeded",
            "invalid_sub_goal_shape",
            "capability_unaligned",
            "plan_tool_unresolvable",
            "plan_tool_off_surface",
            "llm_failed",
        )

    @pytest.mark.asyncio
    async def test_rejection_never_raises_and_never_touches_the_goal_status(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="拒绝不改目标状态目标")
        stub_planning_llm(sub_goals=[_step(2)])
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.status == plan_engine.PLAN_STATUS_REJECTED
        assert goal_repository.get_goal(goal.id).status == "active"

    @pytest.mark.asyncio
    async def test_validated_plan_is_persisted_with_steps(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="合法计划目标")
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL)])
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert outcome.validated
        assert outcome.rejection_reason is None
        assert outcome.plan.status == "validated"
        assert outcome.plan.version == 1
        assert [spec.index for spec in outcome.steps] == [1]
        stored = goal_repository.get_plan(outcome.plan.id)
        assert stored is not None and stored.status == "validated"
        assert stored.version == outcome.plan.version
        assert stored.sub_goals[0].tool_id == ON_SURFACE_TOOL
        assert outcome.plan.trigger == goal_planning.TRIGGER_CREATED
        assert outcome.plan.context_digest


class TestNewGatesAreIndependentlySwitchable:
    """U9：闸门 5 / 6 可分别独立关闭；「闸门 5 过、闸门 6 拒」单列用例。"""

    @pytest.mark.asyncio
    async def test_gate5_passes_while_gate6_rejects(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        """`builtin.search.query` 已声明但被工具面剔除：5 过、6 拒，且步数与内容不变。"""
        goal = make_goal(description="面剔除目标")
        step = _step(1, tool_id=RESOLVABLE_OFF_SURFACE_TOOL)
        stub_planning_llm(sub_goals=[step])
        context = _context(goal, tool_ids=(ON_SURFACE_TOOL,))
        assert plan_engine._unresolvable_tool([_spec(step)]) is None
        outcome = await engine.plan(goal, context, trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_TOOL_OFF_SURFACE
        assert outcome.steps == []
        assert len(context.tool_surface.tool_ids) == 1
        assert context.tool_surface.tool_ids == (ON_SURFACE_TOOL,)

    @pytest.mark.asyncio
    async def test_gate5_disabled_falls_through_to_gate6(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="关闭闸门5目标")
        stub_planning_llm(sub_goals=[_step(1, tool_id=UNRESOLVABLE_TOOL)])
        engine = plan_engine.PlanningEngine(tool_resolvable_gate=False)
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_TOOL_OFF_SURFACE

    @pytest.mark.asyncio
    async def test_gate6_disabled_falls_through_to_gate5(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="关闭闸门6目标")
        stub_planning_llm(sub_goals=[_step(1, tool_id=UNRESOLVABLE_TOOL)])
        engine = plan_engine.PlanningEngine(tool_surface_gate=False)
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_TOOL_UNRESOLVABLE

    @pytest.mark.asyncio
    async def test_binding_switch_off_skips_both_new_gates(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm, override_settings
    ):
        goal = make_goal(description="绑定子闸关闭目标")
        override_settings(v25_plan_step_binding_enabled="false")
        step = _step(1, tool_id=UNRESOLVABLE_TOOL)
        stub_planning_llm(sub_goals=[step])
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert [spec.tool_id for spec in outcome.steps] == [UNRESOLVABLE_TOOL]


class TestReviseSemantics:
    """U10：`version+1` / 旧版 `superseded` / 保留 `done` 步 / 达预算终止。"""

    @pytest.mark.asyncio
    async def test_active_plan_is_bumped_and_superseded(
        self, db_session_factory, planning_on, engine, make_goal, make_plan, stub_planning_llm
    ):
        goal = make_goal(description="修订版本目标")
        done = _step(1, tool_id=ON_SURFACE_TOOL, status="done")
        pending = _step(2, tool_id=ON_SURFACE_TOOL)
        plan = make_plan(goal.id, [done, pending], version=1, status="active")
        stub_planning_llm(sub_goals=[_step(1), _step(2)])
        outcome = await engine.revise(plan, _context(goal), reason="step_attempt_exhausted")
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert outcome.plan.version == 2
        assert goal_repository.get_plan(plan.id).status == "superseded"
        kept, regenerated = outcome.steps
        assert kept.status == "done" and kept.index == 1
        assert kept.tool_id == ON_SURFACE_TOOL
        assert regenerated.index == 2 and regenerated.status == "pending"

    @pytest.mark.asyncio
    async def test_rejected_plan_regenerates_by_replan_trigger(
        self, db_session_factory, planning_on, engine, make_goal, make_plan, stub_planning_llm, monkeypatch
    ):
        goal = make_goal(description="拒绝版重生成目标")
        plan = make_plan(goal.id, [], version=1, status="rejected")
        seen: dict = {}
        original = goal_planning.propose_plan

        def _spy(goal_record, world_facts=None, settings=None):
            seen["goal_id"] = goal_record.id
            return original(goal_record, world_facts, settings)

        monkeypatch.setattr(goal_planning, "propose_plan", _spy)
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL)])
        outcome = await engine.revise(plan, _context(goal), reason="criteria_undecidable")
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert seen["goal_id"] == goal.id
        assert outcome.plan.version == 2
        assert goal_repository.get_plan(plan.id).status == "rejected"

    @pytest.mark.asyncio
    async def test_revision_budget_exhaustion_fails_the_goal(
        self, db_session_factory, planning_on, engine, make_goal, make_plan, override_settings
    ):
        goal = make_goal(description="修订预算耗尽目标")
        plan = make_plan(goal.id, [_step(1)], version=1, status="active")
        override_settings(v25_plan_revision_budget="1")
        outcome = await engine.revise(plan, _context(goal), reason="tool_persistently_unavailable")
        assert outcome.status == plan_engine.PLAN_STATUS_REJECTED
        assert outcome.rejection_reason == plan_engine.REASON_REVISION_EXHAUSTED
        assert goal_repository.get_plan(plan.id).status == "rejected"
        assert goal_repository.get_plan(plan.id).rejection_reason == (
            plan_engine.REASON_REVISION_EXHAUSTED
        )
        revived = goal_repository.get_goal(goal.id)
        assert revived.status == "failed"
        assert revived.failure_reason == "plan_exhausted"

    @pytest.mark.asyncio
    async def test_zero_revision_budget_blocks_every_revision(
        self, db_session_factory, planning_on, engine, make_goal, make_plan, override_settings
    ):
        goal = make_goal(description="零修订预算目标")
        plan = make_plan(goal.id, [_step(1)], version=1, status="active")
        override_settings(v25_plan_revision_budget="0")
        outcome = await engine.revise(plan, _context(goal), reason="insight_driven")
        assert outcome.rejection_reason == plan_engine.REASON_REVISION_EXHAUSTED
        assert goal_repository.count_plans(goal.id) == 1

    @pytest.mark.asyncio
    async def test_kept_steps_survive_when_proposal_drops_them(
        self, db_session_factory, planning_on, engine, make_goal, make_plan, stub_planning_llm
    ):
        goal = make_goal(description="保留步目标")
        done = _step(1, tool_id=ON_SURFACE_TOOL, status="done")
        plan = make_plan(goal.id, [done, _step(2)], version=1, status="active")
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL), _step(2)])
        outcome = await engine.revise(plan, _context(goal), reason="criteria_undecidable")
        assert [spec.index for spec in outcome.steps] == [1, 2]
        assert outcome.steps[0].status == "done"


class TestParameterBoundaries:
    """U13：`v25_plan_max_steps` / `v25_plan_max_depth` / `v25_plan_revision_budget` 边界各一例。"""

    @pytest.mark.asyncio
    async def test_max_steps_boundary_is_inclusive(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm, override_settings
    ):
        goal = make_goal(description="步数边界目标")
        override_settings(v25_plan_max_steps="2")
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL), _step(2, tool_id=ON_SURFACE_TOOL)])
        allowed = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert allowed.status == plan_engine.PLAN_STATUS_VALIDATED
        assert len(allowed.steps) == 2

        stub_planning_llm(
            sub_goals=[_step(i, tool_id=ON_SURFACE_TOOL) for i in (1, 2, 3)]
        )
        rejected = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert rejected.rejection_reason == plan_engine.REASON_COUNT_EXCEEDED

    @pytest.mark.asyncio
    async def test_max_depth_boundary(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm, override_settings
    ):
        goal = make_goal(description="深度边界目标")
        override_settings(v25_plan_max_depth="1")
        stub_planning_llm(
            sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL), _step(2, parent_index=1, tool_id=ON_SURFACE_TOOL)]
        )
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_INVALID_SHAPE

    @pytest.mark.asyncio
    async def test_revision_budget_boundary_uses_the_count(
        self, db_session_factory, planning_on, engine, make_goal, make_plan, stub_planning_llm, override_settings
    ):
        goal = make_goal(description="修订预算边界目标")
        make_plan(goal.id, [_step(1)], version=1, status="superseded")
        make_plan(goal.id, [_step(1)], version=2, status="active")
        override_settings(v25_plan_revision_budget="3")
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL)])
        plan = goal_repository.get_latest_plan(goal.id)
        outcome = await engine.revise(plan, _context(goal), reason="criteria_undecidable")
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert outcome.plan.version == 3

        override_settings(v25_plan_revision_budget="2")
        plan = goal_repository.get_latest_plan(goal.id)
        exhausted = await engine.revise(plan, _context(goal), reason="criteria_undecidable")
        assert exhausted.rejection_reason == plan_engine.REASON_REVISION_EXHAUSTED


class TestEnqueueAndBudget:
    """I3 ~ I6：入队幂等、引擎静态纪律、预算双重约束、终态请求合法。"""

    def test_enqueue_is_idempotent_with_existing_job_type(
        self, db_session_factory, planning_on, engine, make_goal
    ):
        goal = make_goal(description="入队幂等目标")
        assert engine.enqueue(V25_USER, goal.id, goal_planning.TRIGGER_CREATED) is True
        assert engine.enqueue(V25_USER, goal.id, goal_planning.TRIGGER_CREATED) is False
        jobs = background_job_repository.list_jobs("goal_planning")
        assert len(jobs) == 1
        assert jobs[0].job_type == "goal_planning"
        assert jobs[0].payload["trigger"] == goal_planning.TRIGGER_CREATED
        assert (
            engine.enqueue(V25_USER, goal.id, goal_planning.TRIGGER_REPLAN) is True
        )
        assert len(background_job_repository.list_jobs("goal_planning")) == 2

    def test_enqueue_accepts_context_and_projects_world_facts(
        self, db_session_factory, planning_on, engine, make_goal, make_plan
    ):
        goal = make_goal(description="入队世界源目标")
        engine.enqueue(
            V25_USER,
            goal.id,
            goal_planning.TRIGGER_CREATED,
            ctx=_context(goal, world={"location": "home.living_room"}),
        )
        payload = background_job_repository.list_jobs("goal_planning")[0].payload
        assert payload["world_facts"] == {"location": "home.living_room"}

    def test_engine_source_has_no_session_or_tool_selection(self):
        """D1 / D5：零 session / 零 ORM 写构造 / 零工具选择调用（只用 resolve 判可解析）。"""
        source = ENGINE_PATH.read_text(encoding="utf-8")
        code = ast.parse(source)
        names = {node.id for node in ast.walk(code) if isinstance(node, ast.Name)}
        names |= {node.attr for node in ast.walk(code) if isinstance(node, ast.Attribute)}
        assert not names & set(ENGINE_FORBIDDEN_NAMES)
        assert name_hits(code) == set()

    def test_engine_only_touches_the_plan_face_of_goal_repository(self):
        from app.services.planning import goal_contract

        allowed = set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS)
        used = {
            node.attr
            for node in ast.walk(ast.parse(ENGINE_PATH.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "goal_repository"
        }
        assert used <= allowed
        assert used == {
            "count_plans",
            "create_plan",
            "set_plan_rejection",
            "set_plan_status",
            "fail_goal",
        }

    @pytest.mark.asyncio
    async def test_degraded_budget_skips_planning_without_an_error(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm, monkeypatch
    ):
        goal = make_goal(description="额度降级目标")
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL)])
        monkeypatch.setattr(
            plan_engine.life_loop_budget, "is_degraded", lambda *args, **kwargs: True
        )
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.status == plan_engine.PLAN_STATUS_SKIPPED
        assert outcome.rejection_reason == plan_engine.REASON_BUDGET_DEGRADED
        assert goal_repository.count_plans(goal.id) == 0

    @pytest.mark.asyncio
    async def test_plan_uses_the_v25_llm_profile_when_set(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm, monkeypatch, override_settings
    ):
        goal = make_goal(description="规划 profile 目标")
        seen: list = []
        monkeypatch.setattr(goal_planning, "get_llm", lambda profile=None: seen.append(profile))
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL)])
        override_settings(v25_plan_llm_profile="plan-heavy")
        await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert seen == ["plan-heavy"]

        seen.clear()
        override_settings(v25_plan_llm_profile="", v2_autonomy_planning_llm_profile="")
        await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert seen == [None]

    @pytest.mark.asyncio
    async def test_plan_writes_plan_steps_into_loop_runs(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="子步骤记账目标")
        run = loop_run_repository.create_run(
            user_id=V25_USER, kind="autonomy", reason="goal_work", now=V25_NOW
        )
        ctx = _context(
            goal,
            degraded=["world_disabled"],
            run={"run_id": run.id, "run_kind": RUN_KIND_AUTONOMOUS_TICK, "trigger_type": "schedule"},
        )
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL)])
        await engine.plan(goal, ctx, trigger=goal_planning.TRIGGER_CREATED)
        steps = loop_run_repository.get(run.id).steps
        names = [step["step"] for step in steps]
        assert names == [plan_engine.PLAN_STEP_ASSEMBLE, plan_engine.PLAN_STEP_GENERATE]
        assert steps[0]["degraded"] == ["world_disabled"]
        assert steps[1]["status"] == plan_engine.PLAN_STATUS_VALIDATED
        assert steps[1]["steps"] == [1]

    @pytest.mark.asyncio
    async def test_plan_without_run_id_writes_no_sub_step(
        self, db_session_factory, planning_on, engine, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="无 run 记账目标")
        stub_planning_llm(sub_goals=[_step(1, tool_id=ON_SURFACE_TOOL)])
        outcome = await engine.plan(goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert loop_run_repository.list_recent() == []

    @pytest.mark.asyncio
    async def test_revision_budget_exhaustion_keeps_a_terminal_goal_untouched(
        self, db_session_factory, planning_on, engine, make_goal, make_plan, override_settings
    ):
        goal = make_goal(description="终态目标修订目标")
        plan = make_plan(goal.id, [_step(1)], version=1, status="active")
        goal_repository.fail_goal(goal.id, "previous_failure")
        override_settings(v25_plan_revision_budget="0")
        outcome = await engine.revise(plan, _context(goal), reason="insight_driven")
        assert outcome.rejection_reason == plan_engine.REASON_REVISION_EXHAUSTED
        assert goal_repository.get_goal(goal.id).failure_reason == "previous_failure"


def name_hits(code: ast.AST) -> set[str]:
    """模块内出现的模块名（导入面）：断言引擎不导入 ORM / 选择器 / 会话。"""
    modules: set[str] = set()
    for node in ast.walk(code):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return {
        module
        for module in modules
        if module.endswith(("sqlalchemy", "app.core.db", "app.services.tool.surface"))
    }


def _spec(step: dict):
    from app.models.goal import SubGoalSpec

    return SubGoalSpec.model_validate(step)


def test_engine_registers_runtime_through_goal_planning(monkeypatch):
    registered: list = []
    monkeypatch.setattr(goal_planning, "register_runtime", lambda: registered.append("ok"))
    plan_engine.PlanningEngine().register_runtime()
    assert registered == ["ok"]


def test_run_jobs_delegates_to_goal_planning(monkeypatch):
    monkeypatch.setattr(goal_planning, "run_planning_jobs", lambda: 7)
    assert plan_engine.PlanningEngine().run_jobs() == 7


def test_default_engine_is_a_singleton():
    first = plan_engine.get_planning_engine()
    second = plan_engine.get_planning_engine()
    assert first is second
    assert isinstance(first, plan_engine.PlanningEngine)


def test_context_run_projection_is_read_by_the_engine():
    run = RunContext(
        run_id="ctx-run",
        user_id=V25_USER,
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        trigger_type="schedule",
        reason="goal_work",
        started_at=V25_NOW,
    )
    assert plan_context._run_projection(run) == {
        "run_id": "ctx-run",
        "run_kind": RUN_KIND_AUTONOMOUS_TICK,
        "trigger_type": "schedule",
    }
    assert plan_context._run_projection(None) == {}
