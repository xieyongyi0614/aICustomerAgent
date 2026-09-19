"""PLAN-003 装配器断言：六源两态 / 硬依赖零 LLM / 装配零写库 / 工具面 Run Profile。

覆盖 Task Detail §9.1（U1 ~ U7、U11、U12）与 §9.2（I1、I2）；`degraded` 进
`loop_runs.steps` 的子步骤断言在 `test_plan003_engine.py`——子步骤由引擎写，`assemble`
的零写库是本任务的硬断言（见 `app/services/planning/engine.py` 模块文档裁决 2）。
"""

import inspect

import pytest
from sqlalchemy import func, select

from app.application import world_engine
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK, RunContext
from app.core.db import Base
from app.models.goal import GoalRecord
from app.models.memory import UserMemory
from app.models.plan import PlanContext
from app.models.reflection import Insight
from app.models.world_simulation import SituationDimension, UserSituation
from app.repositories import goal_repository, world_repository, world_simulation_repository
from app.services.memory2.retriever import RankedMemories, RankedMemory
from app.services.planning import context as plan_context

from .conftest import V25_NOW, V25_USER

PROBE_USER = "plan3-probe-user"

ON_SURFACE_TOOL = "builtin.reminder.create"
RESOLVABLE_OFF_SURFACE_TOOL = "builtin.search.query"

WORLD_WRITE_FACE = (
    "run_turn_update",
    "run_maintenance",
    "run_simulation_maintenance",
    "create_event",
    "cancel_events_by_type",
    "complete_events_by_type",
    "trigger_due_events",
    "expire_stale_events",
    "create_object",
    "move_object",
    "apply_object_action",
    "discard_object",
    "consume_object",
    "expire_due_objects",
    "set_environment",
    "set_location",
    "seed_default_household",
    "record_character_action_event",
    "merge_character_action_notes",
    "advance_time",
)

GOAL_WRITE_FACE = (
    "set_status",
    "finish_goal",
    "complete_goal",
    "fail_goal",
    "reactivate_goal",
    "create_plan",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
)


@pytest.fixture
def planning_on(override_settings):
    """PLAN-003 装配面：编排常开（总闸与上下文子闸已删），四源恒装配；世界/观测面钉死。"""
    override_settings(
        world_enabled="false",
        observability_persist_enabled="false")


@pytest.fixture
def assembler():
    return plan_context.PlanContextAssembler()


@pytest.fixture
def run_ctx():
    return RunContext(
        run_id="run-plan3",
        user_id=V25_USER,
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        trigger_type="schedule",
        reason="goal_work",
        started_at=V25_NOW,
    )


def _memory(index: int) -> RankedMemory:
    return RankedMemory(
        memory=UserMemory(
            id=f"mem-{index}",
            user_id=V25_USER,
            character_id="asuna",
            type="user_preference",
            content=f"偏好{index}",
            importance=0.5,
            created_at=V25_NOW,
            updated_at=V25_NOW,
        )
    )


def _insight(index: int) -> Insight:
    return Insight(
        id=f"ins-{index}",
        user_id=V25_USER,
        statement=f"洞察{index}",
        type="pattern",
        confidence=0.8,
        scope="user",
        created_at=V25_NOW,
        updated_at=V25_NOW,
    )


def _situation(dimension: SituationDimension = SituationDimension.HEALTH) -> UserSituation:
    return UserSituation(
        id=f"sit-{dimension.value}",
        user_id=V25_USER,
        dimension=dimension,
        summary="用户最近作息不规律",
        intensity=3,
        detected_at=V25_NOW,
        updated_at=V25_NOW,
    )


def _stub_memories(monkeypatch, *, respect_top_k: bool = False, count: int = 5) -> dict:
    """记忆检索打桩：默认固定返回 `count` 条；`respect_top_k` 时按 `top_k` 返回。"""
    seen: dict = {}

    def _retrieve(user_id, query, top_k=None, **kwargs):
        seen.update(user_id=user_id, query=query, top_k=top_k)
        size = min(count, top_k or 0) if respect_top_k else count
        return RankedMemories(items=[_memory(i) for i in range(size)])

    monkeypatch.setattr(plan_context.memory_retriever, "retrieve", _retrieve)
    return seen


def _stub_insights(monkeypatch, count: int, *, signals=None) -> None:
    monkeypatch.setattr(
        plan_context.reflection_lifecycle,
        "list_user_active_insights",
        lambda user_id: [_insight(i) for i in range(count)],
    )
    monkeypatch.setattr(
        plan_context.reflection_tool_feed,
        "interest_signal",
        lambda user_id, **kwargs: list(signals or []),
    )


def _table_counts(session_factory) -> dict[str, int]:
    with session_factory() as session:
        return {
            name: session.execute(select(func.count()).select_from(table)).scalar()
            for name, table in Base.metadata.tables.items()
        }


class TestHardDependencies:
    """U7：`goal` 与 `tool_surface` 是硬依赖，缺失即 `PlanUnavailable` 且零 LLM。"""

    @pytest.mark.asyncio
    async def test_missing_goal_returns_unavailable_without_llm(
        self, db_session_factory, planning_on, assembler, monkeypatch
    ):
        calls: list = []
        monkeypatch.setattr(
            "app.services.goal_planning._ask_llm_with_retry",
            lambda messages, settings: calls.append("llm"),
        )
        ghost = GoalRecord(
            id="missing-goal",
            user_id=V25_USER,
            type="user_care",
            description="不存在的目标",
            created_at=V25_NOW,
            updated_at=V25_NOW,
        )
        result = await assembler.assemble(ghost, now=V25_NOW)
        assert isinstance(result, plan_context.PlanUnavailable)
        assert result.reason == plan_context.PLAN_UNAVAILABLE_GOAL_MISSING
        assert calls == []

    def test_unavailable_reason_codes_are_the_frozen_three(self):
        assert plan_context.PLAN_UNAVAILABLE_REASONS == (
            "goal_missing",
            "tool_system_disabled",
            "registry_unavailable",
        )


class TestSixSources:
    """U1 ~ U5：六源两态、降级清单、有界装配。"""

    @pytest.mark.asyncio
    async def test_goal_source_available_projects_chain(
        self, db_session_factory, planning_on, assembler, make_goal
    ):
        parent = make_goal(description="父目标")
        child = goal_repository.create_hierarchical_goal(
            V25_USER, "short_term", "personal", "子目标", 3, parent_id=parent.id
        )
        result = await assembler.assemble(child, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.goal.id == child.id
        assert [goal.id for goal in result.ancestors] == [parent.id]
        assert [goal.id for goal in result.siblings] == []


    @pytest.mark.asyncio
    async def test_world_source_reads_existing_world_without_creating_one(
        self, db_session_factory, planning_on, assembler, make_goal, override_settings
    ):
        goal = make_goal(description="不建档目标")
        override_settings(world_enabled="true")
        assert world_repository.get_world(V25_USER) is None
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.degraded[0] == plan_context.DEGRADED_WORLD_DISABLED
        assert plan_context.DEGRADED_SCENE_UNAVAILABLE in result.degraded
        assert world_repository.get_world(V25_USER) is None

    @pytest.mark.asyncio
    async def test_context_source_available_and_degraded(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        goal = make_goal(description="场景处境目标")
        world_repository.ensure_world(V25_USER)
        override_settings(
            world_enabled="true")
        world_simulation_repository.save_situation(_situation())
        _stub_memories(monkeypatch)
        _stub_insights(monkeypatch, 1)
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.scene is not None
        assert [situation.dimension for situation in available.situations] == [
            SituationDimension.HEALTH
        ]
        assert available.relationship["stage"]
        assert available.degraded == []

        def _boom(*args, **kwargs):
            raise RuntimeError("处境读取失败")

        monkeypatch.setattr(world_simulation_repository, "get_active_situation", _boom)
        override_settings(world_enabled="false")
        degraded = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(degraded, PlanContext)
        assert degraded.scene is None
        assert degraded.situations == []
        assert plan_context.DEGRADED_SCENE_UNAVAILABLE in degraded.degraded
        assert plan_context.DEGRADED_SITUATION_UNAVAILABLE in degraded.degraded


    @pytest.mark.asyncio
    async def test_memory_source_failure_degrades_without_raising(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        goal = make_goal(description="记忆失败目标")
        override_settings()

        def _boom(*args, **kwargs):
            raise RuntimeError("检索失败")

        monkeypatch.setattr(plan_context.memory_retriever, "retrieve", _boom)
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.memories == []
        assert plan_context.DEGRADED_MEMORY_UNAVAILABLE in result.degraded


    @pytest.mark.asyncio
    async def test_reflection_source_failure_degrades_without_raising(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        goal = make_goal(description="反思失败目标")
        override_settings()

        def _boom(user_id):
            raise RuntimeError("Insight 读取失败")

        monkeypatch.setattr(
            plan_context.reflection_lifecycle, "list_user_active_insights", _boom
        )
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.insights == []
        assert plan_context.DEGRADED_REFLECTION_UNAVAILABLE in result.degraded

    @pytest.mark.asyncio
    async def test_reflection_merges_tool_signals_without_duplicates(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        goal = make_goal(description="工具效能倾向目标")
        override_settings( plan_context_insight_limit="5")
        _stub_insights(
            monkeypatch,
            1,
            signals=[
                {"insight_id": "ins-0", "statement": "重复", "type": "pattern", "confidence": 0.9},
                {
                    "insight_id": "tool-1",
                    "statement": "查天气总超时",
                    "type": "capability_note",
                    "confidence": 0.7,
                },
            ],
        )
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert [insight.insight_id for insight in result.insights] == ["ins-0", "tool-1"]

    @pytest.mark.asyncio
    async def test_tool_surface_source_available(
        self, db_session_factory, planning_on, assembler, make_goal
    ):
        goal = make_goal(description="工具面目标")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert ON_SURFACE_TOOL in result.tool_surface.tool_ids
        assert RESOLVABLE_OFF_SURFACE_TOOL not in result.tool_surface.tool_ids
        assert plan_context.DEGRADED_SURFACE_UNAVAILABLE not in result.degraded

    @pytest.mark.asyncio
    async def test_memory_source_is_bounded_by_the_tighter_limit(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        """U4：条数 ≤ min(`memory_top_k`, `plan_context_memory_limit`) 两侧各一例。"""
        goal = make_goal(description="记忆有界目标")
        override_settings( memory_top_k="5", plan_context_memory_limit="2")
        seen = _stub_memories(monkeypatch)
        by_limit = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(by_limit, PlanContext)
        assert len(by_limit.memories) == 2
        assert seen["top_k"] == 5
        assert seen["query"] == goal.description

        _stub_memories(monkeypatch, respect_top_k=True)
        override_settings(memory_top_k="1", plan_context_memory_limit="5")
        by_top_k = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(by_top_k, PlanContext)
        assert len(by_top_k.memories) == 1

    @pytest.mark.asyncio
    async def test_reflection_source_is_bounded_by_insight_limit(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        goal = make_goal(description="反思有界目标")
        override_settings( plan_context_insight_limit="1")
        _stub_insights(monkeypatch, 3)
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert [insight.insight_id for insight in result.insights] == ["ins-0"]


class TestAssemblyDiscipline:
    """U6 / U11 / U12 / I1 / I2：Run Profile、摘要、无面退化、来源可追溯、零写库。"""

    @pytest.mark.asyncio
    async def test_tool_surface_is_resolved_for_autonomous_tick(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch
    ):
        goal = make_goal(description="Run Profile 目标")
        seen: list[str] = []
        original = plan_context.ToolSurfaceResolver.resolve

        def _spy(self, run_kind, ctx):
            seen.append(run_kind)
            return original(self, run_kind, ctx)

        monkeypatch.setattr(plan_context.ToolSurfaceResolver, "resolve", _spy)
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert seen == [RUN_KIND_AUTONOMOUS_TICK]
        assert result.tool_surface.run_kind == RUN_KIND_AUTONOMOUS_TICK
        excluded = {item["tool_id"] for item in result.tool_surface.excluded}
        assert RESOLVABLE_OFF_SURFACE_TOOL in excluded

    @pytest.mark.asyncio
    async def test_context_digest_is_reproducible(
        self, db_session_factory, planning_on, assembler, make_goal, override_settings
    ):
        goal = make_goal(description="摘要目标")
        first = await assembler.assemble(goal, now=V25_NOW)
        second = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(first, PlanContext) and isinstance(second, PlanContext)
        assert plan_context.context_digest(first) == plan_context.context_digest(second)

        override_settings(plan_max_steps="9")
        changed = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(changed, PlanContext)
        assert plan_context.context_digest(changed) != plan_context.context_digest(first)

    def test_context_budget_projects_the_four_caps(self, planning_on):
        from app.core.settings import get_settings

        budget = plan_context.plan_budget(get_settings())
        assert tuple(sorted(budget)) == tuple(sorted(plan_context.PLAN_BUDGET_KEYS))
        assert budget == {
            "max_steps": 5,
            "max_depth": 2,
            "revision_budget": 3,
            "step_max_attempts": 2,
        }

    @pytest.mark.asyncio
    async def test_tool_required_off_allows_planning_without_surface(
        self, db_session_factory, planning_on, assembler, make_goal, override_settings
    ):
        goal = make_goal(description="无面规划目标")
        override_settings(plan_tool_required="false")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.tool_surface.tool_ids == ()
        assert result.tool_surface.run_kind == RUN_KIND_AUTONOMOUS_TICK
        assert plan_context.DEGRADED_SURFACE_UNAVAILABLE in result.degraded

    @pytest.mark.asyncio
    async def test_probe_reads_snapshot_and_is_zero_io(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        goal = make_goal(description="探测目标")
        override_settings(world_enabled="false")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)

        def _forbidden(*args, **kwargs):
            raise AssertionError("Probe 不得读仓储 / 不得调 LLM")

        monkeypatch.setattr(goal_repository, "get_goal", _forbidden)
        monkeypatch.setattr(world_engine, "collect_facts", _forbidden)
        monkeypatch.setattr(
            "app.services.goal_planning.propose_plan", _forbidden
        )
        probe = plan_context.PlanContextProbe()
        assert probe.world_available(V25_USER) is False
        assert probe.surface_size(V25_USER, run_kind=RUN_KIND_AUTONOMOUS_TICK) == len(
            result.tool_surface.tool_ids
        )
        assert probe.surface_size(V25_USER, run_kind="foreground_chat") == 0
        assert probe.degraded_sources(V25_USER) == result.degraded
        assert probe.degraded_sources(PROBE_USER) == []
        assert probe.world_available(PROBE_USER) is False

    def test_probe_source_has_no_repository_or_llm_tokens(self):
        source = inspect.getsource(plan_context.PlanContextProbe)
        for token in (
            "goal_repository",
            "get_active_situation",
            "retrieve(",
            "collect_facts",
            "SessionLocal",
            "get_tool_registry",
            "get_llm",
        ):
            assert token not in source, token

    @pytest.mark.asyncio
    async def test_sources_are_read_through_existing_entries(
        self, db_session_factory, planning_on, assembler, make_goal, monkeypatch, override_settings
    ):
        parent = make_goal(description="来源追溯父目标")
        goal = goal_repository.create_hierarchical_goal(
            V25_USER, "short_term", "personal", "来源追溯目标", 3, parent_id=parent.id
        )
        world_repository.ensure_world(V25_USER)
        world_simulation_repository.save_situation(_situation())
        override_settings(
            world_enabled="true")
        _stub_memories(monkeypatch)
        _stub_insights(monkeypatch, 1)
        seen: list[str] = []
        for module, name in (
            (goal_repository, "get_goal"),
            (goal_repository, "list_children"),
            (world_engine, "collect_facts"),
            (world_engine, "build_context"),
            (world_simulation_repository, "get_active_situation"),
            (plan_context.memory_retriever, "retrieve"),
            (plan_context.reflection_lifecycle, "list_user_active_insights"),
            (plan_context, "build_tool_context"),
        ):
            monkeypatch.setattr(module, name, _spy(module, name, seen))
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert set(seen) >= {
            "get_goal",
            "list_children",
            "collect_facts",
            "build_context",
            "get_active_situation",
            "retrieve",
            "list_user_active_insights",
            "build_tool_context",
        }

    @pytest.mark.asyncio
    async def test_assembly_writes_nothing(
        self,
        db_session_factory,
        planning_on,
        assembler,
        make_goal,
        monkeypatch,
        run_ctx,
        override_settings,
    ):
        goal = make_goal(description="零写库目标")
        world_repository.ensure_world(V25_USER)
        world_engine.seed_default_household(V25_USER)
        world_simulation_repository.save_situation(_situation())
        override_settings(
            world_enabled="true")
        _stub_memories(monkeypatch)
        _stub_insights(monkeypatch, 1)
        called: list[str] = []
        for module, names in ((world_engine, WORLD_WRITE_FACE), (goal_repository, GOAL_WRITE_FACE)):
            for name in names:
                monkeypatch.setattr(module, name, _stub_out(module, name, called))
        before = _table_counts(db_session_factory)
        result = await assembler.assemble(goal, run=run_ctx, now=V25_NOW)
        after = _table_counts(db_session_factory)
        assert isinstance(result, PlanContext)
        assert called == []
        assert before == after


def _label(module, name: str) -> str:
    return f"{module.__name__.rsplit('.', 1)[-1]}.{name}"


def _spy(module, name: str, sink: list):
    """透传原实现并记录调用（I1：来源可追溯）。"""
    original = getattr(module, name)

    def _call(*args, **kwargs):
        sink.append(name)
        return original(*args, **kwargs)

    return _call


def _stub_out(module, name: str, sink: list):
    """记录调用并返回 None（I2：写面被调用即留痕，供「零调用」断言）。"""
    def _call(*args, **kwargs):
        sink.append(_label(module, name))
        return None

    return _call


class TestDegradedRegistry:
    """U3：`degraded` 清单元素为稳定字符串，且逐源可读。

    PLAN-008 契约演进（本模块的必要改动，留痕）：World 源由「三段一体」细化为 §4.2.1 的
    **九段逐段可降级**，故 `PLAN_DEGRADED_REASONS` 在原六值之后（`world_disabled` 之后）
    插入七条世界段标记。整体不可用（`world_enabled=False` / 无世界记录）仍只登记
    `world_disabled` 一条，其余断言不变。
    """

    def test_degraded_codes_are_frozen_and_stable(self):
        assert plan_context.PLAN_DEGRADED_REASONS == (
            "world_disabled",
            "world_time_unavailable",
            "world_environment_unavailable",
            "world_location_unavailable",
            "world_objects_unavailable",
            "world_events_unavailable",
            "world_brief_unavailable",
            "world_context_unavailable",
            "scene_unavailable",
            "situation_unavailable",
            "memory_unavailable",
            "reflection_unavailable",
            "surface_unavailable",
        )
        assert all(
            code == code.lower() and code.isascii()
            for code in plan_context.PLAN_DEGRADED_REASONS
        )

    @pytest.mark.asyncio
    async def test_degraded_list_only_contains_frozen_codes(
        self, db_session_factory, planning_on, assembler, make_goal
    ):
        goal = make_goal(description="降级清单目标")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.degraded
        assert set(result.degraded) <= set(plan_context.PLAN_DEGRADED_REASONS)


class TestContextSwitch:
    """`plan_context_enabled` 已随开关体系删除：四源装配恒发生。

    原「子闸 off 跳过四源」用例的前提不存在，按开关删除纪律整类退役——
    四源装配行为由本文件其余常开用例覆盖。
    """
