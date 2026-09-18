"""PLAN-003 挂载与场景断言：九步序列 / stage 序列 / 预算数学 / Flag off 原路径 / 零迁移。

覆盖 Task Detail §9.2（I7 ~ I12）与 §9.3 中的可判定场景（S1 / S3 / S4 / S7 / S8）。
形状快照的口径：**不改**既有序列，只断言其未变（新增 stage 即坐标变更，用例失败）。
"""

import re
from pathlib import Path

import pytest

from app.application import life_loop
from app.application.agent_runtime import profiles
from app.application.agent_runtime.llm_gateway import _CAPABILITY_DEFAULTS
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK, RunContext
from app.core.db import GoalPlanRow
from app.repositories import background_job_repository, goal_repository
from app.services import goal_planning, life_loop_budget
from app.services.planning import context as plan_context
from app.services.planning import engine as plan_engine
from app.services.planning import goal_contract

from .conftest import V25_NOW, V25_USER
from .test_plan001_flag_regression import FROZEN_PROMPT_DIGEST, _digest

AUTONOMOUS_TICK_STAGES = (
    "perception",
    "state_update",
    "state_snapshot",
    "goal_check",
    "goal_stack",
    "goal_supply",
    "goal_advance",
    "memory_retrieval",
    "reflection_check",
    "decision",
    "world_experience",
)

CAPABILITY_BITS = (
    "answer",
    "router",
    "turn_analysis",
    "scene_intent",
    "intention",
    "scene_update",
    "state_update",
    "extractor",
    "summary",
    "proactive",
    "judge",
    "reflection",
)

MIGRATION_HEAD = "0048"

PLAN_FACE_SIGNATURES = (
    "create_plan",
    "get_plan",
    "get_latest_plan",
    "list_plans",
    "count_plans",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
    "list_active_plans",
)


@pytest.fixture
def planning_on(override_settings):
    life_loop_budget.reset_cache()
    override_settings(
        planning_enabled="true",
        plan_context_enabled="true",
        plan_step_binding_enabled="true",
        tool_system_enabled="true",
        world_enabled="false",
        observability_persist_enabled="false")


def _claim_planning_job(goal_id: str, trigger: str = goal_planning.TRIGGER_CREATED) -> None:
    """把一条规划 job 置为 running（模拟后台 worker 的领取动作，AUT-002 既有测试同款）。"""
    background_job_repository.enqueue_job(
        goal_planning.JOB_TYPE_PLANNING,
        {"goal_id": goal_id, "trigger": trigger, "world_facts": {}},
        f"{goal_planning.JOB_TYPE_PLANNING}:{goal_id}:{trigger}:1",
    )
    with background_job_repository.SessionLocal() as session:
        (job,) = background_job_repository.list_jobs(goal_planning.JOB_TYPE_PLANNING)
        job.status = "running"
        session.add(job)
        session.commit()


class TestMountWiring:
    """Step 6：`goal_supply` 内部接线（签名与返回 dict 字段集不变）。"""

    def test_signature_and_return_field_set_are_unchanged(
        self, db_session_factory, override_settings, monkeypatch
    ):
        import inspect

        assert list(inspect.signature(life_loop._step_goal_supply).parameters) == [
            "user_id",
            "now",
        ]
        life_loop_budget.reset_cache()
        override_settings(
            autonomy_supply_interval_minutes="0",
            world_enabled="false")
        monkeypatch.setattr(
            goal_planning,
            "materialize",
            lambda user_id, world_facts=None, now=None: {
                "status": "ok",
                "created": ["g-1"],
                "enqueued": 1,
            },
        )
        engine = plan_engine.PlanningEngine()
        calls: list = []
        monkeypatch.setattr(
            plan_engine,
            "get_planning_engine",
            lambda: _SpyEngine(engine, calls),
        )
        life_loop._supply_last.clear()
        flag_off = life_loop._step_goal_supply(V25_USER, V25_NOW)
        assert calls == []
        life_loop._supply_last.clear()
        override_settings(planning_enabled="true")
        flag_on = life_loop._step_goal_supply(V25_USER, V25_NOW)
        life_loop._supply_last.clear()
        assert set(flag_off) == set(flag_on)
        assert flag_on["created"] == ["g-1"]
        assert calls == [("enqueue", "g-1"), ("run_jobs", None)]

    def test_supply_processes_claimed_planning_job_in_step(
        self,
        db_session_factory,
        override_settings,
        monkeypatch,
        stub_planning_llm,
        make_goal,
    ):
        """S1：`goal_supply` 步内 `run_jobs` 把**已领取**的规划 job 处理完 → 计划落库。

        `run_jobs` 委托既有 `run_planning_jobs`（§3.4），其语义为「处理 running 载荷」并把
        计划置 `active`（既有行为，不改）；「`validated`」态由 `PlanningEngine.plan` 产出
        （见 `test_plan003_engine.py`），激活属 PLAN-005。本用例证明挂载点确实在供给步内
        把规划处理完，而非只依赖后台 worker；同时 `enqueue` 幂等（不产生第二个 job）。
        """
        life_loop_budget.reset_cache()
        override_settings(
            autonomy_supply_interval_minutes="0",
            planning_enabled="true",
            tool_system_enabled="true",
            world_enabled="false")
        goal = make_goal(description="供给步处理目标")
        _claim_planning_job(goal.id)
        stub_planning_llm(
            sub_goals=[
                {
                    "index": 1,
                    "description": "提醒休息",
                    "capability": "create_reminder",
                    "params": {"content": "休息一下"},
                    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
                }
            ]
        )
        monkeypatch.setattr(
            goal_planning,
            "materialize",
            lambda user_id, world_facts=None, now=None: {
                "status": "ok",
                "created": [goal.id],
                "enqueued": 1,
            },
        )
        life_loop._supply_last.clear()
        detail = life_loop._step_goal_supply(V25_USER, V25_NOW)
        life_loop._supply_last.clear()
        assert detail["created"] == [goal.id]
        plan = goal_repository.get_latest_plan(goal.id)
        assert plan is not None
        assert plan.status == "active"
        assert [spec.index for spec in plan.sub_goals] == [1]
        assert len(background_job_repository.list_jobs("goal_planning")) == 1

    def test_engine_routing_is_flag_gated(
        self, db_session_factory, override_settings, monkeypatch
    ):
        life_loop_budget.reset_cache()
        override_settings(
            autonomy_supply_interval_minutes="0",
            world_enabled="false")
        monkeypatch.setattr(
            goal_planning,
            "materialize",
            lambda user_id, world_facts=None, now=None: {"status": "ok", "created": [], "enqueued": 0},
        )
        calls: list = []
        monkeypatch.setattr(
            plan_engine, "get_planning_engine", lambda: _SpyEngine(None, calls)
        )
        life_loop._supply_last.clear()
        life_loop._step_goal_supply(V25_USER, V25_NOW)
        life_loop._supply_last.clear()
        assert calls == []
        override_settings(planning_enabled="true")
        life_loop._step_goal_supply(V25_USER, V25_NOW)
        life_loop._supply_last.clear()
        assert calls == [("run_jobs", None)]


class _SpyEngine:
    """引擎代理：只记录 `enqueue` / `run_jobs` 调用，其余委托真实引擎。"""

    def __init__(self, engine, sink: list) -> None:
        self._engine = engine
        self._sink = sink

    def enqueue(self, user_id, goal_id, trigger, *, ctx=None):
        self._sink.append(("enqueue", str(goal_id)))
        if self._engine is None:
            return True
        return self._engine.enqueue(user_id, goal_id, trigger, ctx=ctx)

    def run_jobs(self):
        self._sink.append(("run_jobs", None))
        if self._engine is None:
            return 0
        return self._engine.run_jobs()


class TestShapeSnapshots:
    """I7 / I8 / I9：stage 序列、预算数学零差异。"""

    def test_autonomous_tick_stage_sequence_is_unchanged(self):
        spec = profiles.get_profile(RUN_KIND_AUTONOMOUS_TICK)
        assert spec.stages == AUTONOMOUS_TICK_STAGES
        assert "goal_supply" in spec.stages and "goal_advance" in spec.stages
        assert spec.llm_capable == frozenset({"decision"})
        assert spec.critical == frozenset({"decision"})

    def test_cycle_llm_budget_math_is_unchanged(self):
        from app.core.settings import get_settings

        assert get_settings().life_loop_cycle_llm_budget == 1
        assert tuple(_CAPABILITY_DEFAULTS) == CAPABILITY_BITS
        assert profiles.snapshot_profile(RUN_KIND_AUTONOMOUS_TICK)["llm_capable"] == ["decision"]

    def test_planning_engine_adds_no_llm_capability_bit(self):
        assert "plan" not in _CAPABILITY_DEFAULTS
        assert "planning" not in _CAPABILITY_DEFAULTS


class TestZeroMigrationAndContracts:
    """I10 / I12：计划面九函数零改动、迁移链头 0046、CHECK 五值未变。"""

    def test_goal_repository_plan_face_keeps_its_nine_functions(self):
        import inspect

        for name in PLAN_FACE_SIGNATURES:
            assert callable(getattr(goal_repository, name)), name
        assert list(inspect.signature(goal_repository.create_plan).parameters) == ["record"]
        assert list(inspect.signature(goal_repository.set_plan_status).parameters) == [
            "plan_id",
            "status",
        ]
        assert list(inspect.signature(goal_repository.set_plan_rejection).parameters) == [
            "plan_id",
            "reason",
        ]
        assert list(inspect.signature(goal_repository.count_plans).parameters) == ["goal_id"]

    def test_migration_head_is_still_0048(self):
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        numbered = sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert f"{max(numbered):04d}" == MIGRATION_HEAD
        assert max(numbered) == 48

    def test_goal_plans_status_values_are_unchanged(self):
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in GoalPlanRow.__table__.constraints
            if constraint.name == "ck_goal_plans_status"
        }
        assert list(checks) == ["ck_goal_plans_status"]
        for status in ("draft", "validated", "rejected", "active", "superseded"):
            assert status in checks["ck_goal_plans_status"]
        assert tuple(sorted(GoalPlanRow.__table__.c.keys())) == (
            "created_at",
            "goal_id",
            "id",
            "rejection_reason",
            "status",
            "sub_goals",
            "updated_at",
            "version",
        )

    def test_planning_contract_whitelist_evolution_is_recorded(self):
        """PLAN-003 落地 12 → 16；PLAN-011 再扩三个只读扩展 → 19（判定口径不变）。"""
        assert len(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS) == 19
        assert goal_contract.PLANNING_WRITE_FUNCTION_NAMES == (
            "set_status",
            "finish_goal",
            "complete_goal",
            "fail_goal",
            "reactivate_goal",
        )
        assert plan_engine.PLAN_STEP_ASSEMBLE == "plan_assemble"
        assert plan_context.PLAN_UNAVAILABLE_REASONS


class TestScenarioGates:
    """S3 / S4 / S7：面剔除、恒不可用工具、世界关闭下的规划。"""

    @pytest.mark.asyncio
    async def test_s3_late_night_channel_tool_is_rejected_by_gate6(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="深夜通道目标")
        stub_planning_llm(sub_goals=[_channel_step()])
        engine = plan_engine.PlanningEngine()
        context = _channel_context(goal)
        outcome = await engine.plan(goal, context, trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_TOOL_OFF_SURFACE
        assert outcome.steps == []
        assert goal_repository.get_plan(outcome.plan.id).sub_goals == []

    @pytest.mark.asyncio
    async def test_s4_unavailable_tool_never_enters_a_plan(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="恒不可用工具目标")
        stub_planning_llm(sub_goals=[_step_with_tool("builtin.search.query")])
        engine = plan_engine.PlanningEngine()
        outcome = await engine.plan(goal, _channel_context(goal), trigger=goal_planning.TRIGGER_CREATED)
        assert outcome.rejection_reason == plan_engine.REASON_TOOL_OFF_SURFACE
        assert "builtin.search.query" not in [
            spec.tool_id for spec in goal_repository.list_plans(goal.id)[0].sub_goals
        ]

    @pytest.mark.asyncio
    async def test_s7_world_disabled_still_produces_a_plan(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="世界关闭规划目标")
        assembler = plan_context.PlanContextAssembler()
        context = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(context, plan_context.PlanContext)
        assert plan_context.DEGRADED_WORLD_DISABLED in context.degraded
        stub_planning_llm(sub_goals=[_step_with_tool("builtin.reminder.create")])
        outcome = await plan_engine.PlanningEngine().plan(
            goal, context, trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert outcome.degraded == context.degraded

    @pytest.mark.asyncio
    async def test_s2_context_digest_lands_on_the_plan_record(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="六源摘要目标")
        assembler = plan_context.PlanContextAssembler()
        context = await assembler.assemble(
            goal,
            run=RunContext(
                run_id="run-s2",
                user_id=V25_USER,
                run_kind=RUN_KIND_AUTONOMOUS_TICK,
                trigger_type="schedule",
                reason="goal_work",
                started_at=V25_NOW,
                data={"evidence_refs": ["ins-9"]},
            ),
            now=V25_NOW,
        )
        assert isinstance(context, plan_context.PlanContext)
        assert context.run["run_id"] == "run-s2"
        assert context.evidence_refs == ["ins-9"]
        stub_planning_llm(sub_goals=[_step_with_tool("builtin.reminder.create")])
        outcome = await plan_engine.PlanningEngine().plan(
            goal, context, trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.plan.context_digest == plan_context.context_digest(context)
        assert outcome.plan.evidence_refs == ("ins-9",)


def _step_with_tool(tool_id: str) -> dict:
    return {
        "index": 1,
        "description": "一步",
        "capability": "create_reminder",
        "params": {"content": "提醒"},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
        "tool_id": tool_id,
    }


def _channel_step() -> dict:
    return {
        "index": 1,
        "description": "深夜给用户发消息",
        "capability": "send_notification",
        "params": {"content": "该睡了", "recipient": "user"},
        "criteria": {"type": "action_succeeded", "capability": "send_notification"},
        "tool_id": "channel.feishu.send",
    }


def _channel_context(goal):
    from app.models.tool import ToolSurface

    return plan_context.PlanContext(
        goal=goal,
        tool_surface=ToolSurface(
            run_kind=RUN_KIND_AUTONOMOUS_TICK,
            tool_ids=("builtin.notification.send",),
            excluded=(
                {"tool_id": "channel.feishu.send", "reason": "part_of_day:late_night"},
                {"tool_id": "builtin.search.query", "reason": "unavailable:source_not_configured"},
            ),
            surface_hash="snapshot",
        ),
        budget=plan_context.plan_budget(_settings()),
    )


def _settings():
    from app.core.settings import get_settings

    return get_settings()
