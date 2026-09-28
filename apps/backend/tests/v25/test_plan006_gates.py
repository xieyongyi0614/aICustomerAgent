"""PLAN-006 Step 1~3：规划期闸门 5/6 判定细节、四类工具不进计划、专项用例。

覆盖 Task Detail §9.1 U1~U4 / U5~U9 与 §9.2 I6 / I13；对应 §8 Step 1 / Step 2 / Step 3。

本模块的两条读法（与 Task Detail 的偏差已在用例里写明）：

1. **「计划步数与内容不变」的判定面**：`§4.2.2` 该行的语义是「该步暂不装配」，而 PLAN-003
   冻结的闸门 6 语义是**整份新计划被拒**（`rejected`，不落步骤）——两者不矛盾但判定面不同：
   规划期只能断言「闸门判定只读、不重写步骤内容」（`spec.model_dump` 前后一致）与「被拒计划的
   理由码正确」；「计划内容不变 + 仅该步暂不装配」的完整形态由 PLAN-005 的调度面承载
   （`blocked_reason=off_surface` + A2 复核 `blocked`），故 Step 3 专项用例同时断言这两面。
2. **T2 的理由前缀**：`builtin.search.query` 走的是 TOOL-010 的「可用性降级」维度
   （`unavailable:source_not_configured`），它不在 §4.2.1 八维表列出的七个前缀里——
   §2.1 的前缀清单同样未列它。用例按**真实常量** `TOOL_UNAVAILABLE_REASON` 断言，
   不按文档前缀猜。
"""

from pathlib import Path

import pytest

from app.character.asuna.tool import TOOL_UNAVAILABLE_REASON, TOOL_UNAVAILABLE_TOOL_IDS
from app.core.settings import get_settings
from app.models.plan import PlanContext
from app.services import goal_planning
from app.services.planning import context as plan_context
from app.services.planning import engine as plan_engine
from app.services.planning import goal_contract
from app.services.planning import scheduler as plan_scheduler
from app.services.tool import surface as surface_module
from app.services.tool.registry import get_tool_registry
from app.services.tool.surface import ToolSurfaceResolver

from . import _plan_scan as scan
from . import plan006_support as support
from . import plan005_support as plan5
from .plan006_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    action_chain_on,
    isolated_tool_registry,
    planning_gates_on,
    repo_write_probe,
    tools_on,
)

REASON_TOOL_UNRESOLVABLE = "plan_tool_unresolvable"
REASON_TOOL_OFF_SURFACE = "plan_tool_off_surface"

PREDICATE = plan_engine._evaluate_tool_resolvable
SURFACE_PREDICATE = plan_engine._evaluate_tool_on_surface


def _plan_context(goal, surface) -> PlanContext:
    return PlanContext(
        goal=goal,
        tool_surface=surface,
        budget=plan_context.plan_budget(get_settings()),
    )


def _step(
    tool_id: str,
    *,
    index: int = 1,
    capability: str = "create_reminder",
    params: dict | None = None,
) -> dict:
    return {
        "index": index,
        "description": f"步骤{index}",
        "capability": capability,
        "params": {"content": "该休息了"} if params is None else params,
        "criteria": {"type": "action_succeeded", "capability": capability},
        "tool_id": tool_id,
    }


class TestGatePredicates:
    """U1 / U2：闸门 5 可解析与闸门 6 在面上的判定（§6.1 两个内部接口）。"""

    def test_u1_resolvable_requires_a_declaration(self):
        registry = support.builtin_registry()
        assert PREDICATE([support.spec(1, tool_id=support.REMINDER_CREATE)], registry) is None
        assert (
            PREDICATE([support.spec(1, tool_id=support.UNRESOLVABLE_TOOL)], registry)
            == support.UNRESOLVABLE_TOOL
        )

    def test_u1_skips_steps_without_a_tool_id_or_without_tool_kind(self):
        """判定对象收窄（§8 Step 1.1）：无 `tool_id` 与非 `kind="tool"` 的步骤不参与。"""
        registry = support.builtin_registry()
        assert PREDICATE([support.spec(1)], registry) is None
        assert PREDICATE([support.spec(1, kind="composite")], registry) is None
        assert PREDICATE([support.spec(1, tool_id="", kind="observe")], registry) is None

    def test_u1_fails_closed_when_the_registry_is_unavailable(self):
        """工具系统总闸 off（注册表不可得）时判不可解析：宁可不规划。"""
        assert (
            PREDICATE([support.spec(1, tool_id=support.REMINDER_CREATE)], None)
            == support.REMINDER_CREATE
        )

    def test_u1_returns_the_first_unresolvable_tool(self):
        specs = [
            support.spec(1, tool_id=support.REMINDER_CREATE),
            support.spec(2, tool_id=support.UNRESOLVABLE_TOOL),
        ]
        assert PREDICATE(specs, support.builtin_registry()) == support.UNRESOLVABLE_TOOL

    def test_d1_gate5_is_read_only_for_the_registry(self):
        """D1：闸门 5 零注册表改动——只调 `resolve`，快照前后一致。"""
        registry = support.builtin_registry()
        probe = support.RegistryReadProbe(registry)
        before = support.registry_snapshot(registry)
        PREDICATE(
            [
                support.spec(1, tool_id=support.REMINDER_CREATE),
                support.spec(2, tool_id=support.UNRESOLVABLE_TOOL),
            ],
            probe,
        )
        assert probe.calls == ["resolve", "resolve"]
        assert support.registry_snapshot(registry) == before

    def test_u2_off_surface_judgement_reads_only_the_given_surface(self):
        surface = plan5.surface(support.REMINDER_CREATE)
        assert SURFACE_PREDICATE([support.spec(1, tool_id=support.REMINDER_CREATE)], surface) is None
        assert (
            SURFACE_PREDICATE([support.spec(1, tool_id=support.SEARCH_QUERY)], surface)
            == support.SEARCH_QUERY
        )

    def test_u2_empty_surface_rejects_every_tool_step(self):
        assert (
            SURFACE_PREDICATE([support.spec(1, tool_id=support.REMINDER_CREATE)], None)
            == support.REMINDER_CREATE
        )
        assert (
            SURFACE_PREDICATE(
                [support.spec(1, tool_id=support.REMINDER_CREATE)], plan5.surface()
            )
            == support.REMINDER_CREATE
        )

    def test_u2_skips_steps_without_a_tool_id(self):
        assert SURFACE_PREDICATE([support.spec(1)], plan5.surface()) is None
        assert SURFACE_PREDICATE([support.spec(1, kind="composite")], None) is None

    def test_d2_gate6_never_recomputes_the_surface(self, monkeypatch):
        """D2：闸门 6 只读调用方给的面，零面重算——面解析器被禁也能出结论。"""

        def _boom(*_args, **_kwargs):
            raise AssertionError("闸门 6 不得自行调用 ToolSurfaceResolver")

        monkeypatch.setattr(surface_module.ToolSurfaceResolver, "resolve", _boom)
        surface = plan5.surface(support.REMINDER_CREATE)
        assert SURFACE_PREDICATE([support.spec(1, tool_id=support.REMINDER_CREATE)], surface) is None
        assert (
            SURFACE_PREDICATE([support.spec(1, tool_id=support.SEARCH_QUERY)], surface)
            == support.SEARCH_QUERY
        )

    def test_d2_engine_module_has_no_surface_resolver(self):
        """D2 静态面：`engine.py` 不导入面解析器（面属装配期产物）。

        口径与全套静态扫描一致：断言走**代码口径**（注释与字符串被丢弃），故契约文档里
        可以写出被禁的名字（否则禁令无法被声明）。
        """
        assert "ToolSurfaceResolver" not in scan.code_text(Path(plan_engine.__file__))
        assert "app.services.tool.surface" not in scan.imported_modules(Path(plan_engine.__file__))


class TestGateSwitchability:
    """U3：两闸门受绑定子闸门控，且可分别独立关闭。"""

    @pytest.fixture
    def engine(self):
        return plan_engine.PlanningEngine()

    @pytest.mark.asyncio
    async def test_u3_binding_switch_off_disables_both_gates(
        self, db_session_factory, planning_gates_on, engine, make_goal, stub_planning_llm
    ):
        """绑定开关注入 off（构造参数，供单列验证；settings 子闸已删）→ 两道闸跳过。"""
        engine = plan_engine.PlanningEngine(tool_binding_enabled=False)
        goal = make_goal(description="绑定子闸关闭目标")
        stub_planning_llm(sub_goals=[_step(support.UNRESOLVABLE_TOOL)])
        surface = support.resolve_surface()
        outcome = await engine.plan(
            goal, _plan_context(goal, surface), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        assert outcome.rejection_reason is None

    @pytest.mark.asyncio
    async def test_u3_gates_are_switchable_one_by_one(
        self, db_session_factory, planning_gates_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="闸门独立开关目标")
        stub_planning_llm(sub_goals=[_step(support.UNRESOLVABLE_TOOL)])
        surface = support.resolve_surface()
        context = _plan_context(goal, surface)

        only_gate6 = plan_engine.PlanningEngine(tool_resolvable_gate=False)
        assert (
            await only_gate6.plan(goal, context, trigger=goal_planning.TRIGGER_CREATED)
        ).rejection_reason == REASON_TOOL_OFF_SURFACE

        only_gate5 = plan_engine.PlanningEngine(tool_surface_gate=False)
        assert (
            await only_gate5.plan(goal, context, trigger=goal_planning.TRIGGER_CREATED)
        ).rejection_reason == REASON_TOOL_UNRESOLVABLE

        neither = plan_engine.PlanningEngine(
            tool_resolvable_gate=False, tool_surface_gate=False
        )
        assert (
            await neither.plan(goal, context, trigger=goal_planning.TRIGGER_CREATED)
        ).status == plan_engine.PLAN_STATUS_VALIDATED


class TestFourExcludedToolClasses:
    """U5~U8（T1~T4）：四类工具均不进计划，且 `excluded` 携带正确理由前缀。"""

    @pytest.mark.asyncio
    async def test_t1_operationally_disabled_tool_never_enters_a_plan(
        self, db_session_factory, planning_gates_on, make_goal, stub_planning_llm, override_settings
    ):
        override_settings(tool_disabled_ids=support.MEMORY_SAVE)
        registry = get_tool_registry()
        assert registry is not None and registry.effective_status(support.MEMORY_SAVE) == "disabled"
        surface = support.resolve_surface(registry)
        assert support.excluded_reason(surface, support.MEMORY_SAVE) == "tool_status:disabled"
        assert support.MEMORY_SAVE not in surface.tool_ids

        goal = make_goal(description="禁用工具目标")
        stub_planning_llm(
            sub_goals=[_step(support.MEMORY_SAVE, capability="remember_fact")]
        )
        outcome = await plan_engine.PlanningEngine().plan(
            goal, _plan_context(goal, surface), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.rejection_reason == REASON_TOOL_OFF_SURFACE
        from app.repositories import goal_repository

        assert goal_repository.get_plan(outcome.plan.id).sub_goals == []

    @pytest.mark.asyncio
    async def test_t2_permanently_unavailable_tool_is_clipped_by_availability(
        self, db_session_factory, planning_gates_on, make_goal, stub_planning_llm
    ):
        registry = get_tool_registry()
        assert support.SEARCH_QUERY in TOOL_UNAVAILABLE_TOOL_IDS
        assert registry is not None and registry.resolve(support.SEARCH_QUERY) is not None
        surface = support.resolve_surface(registry)
        assert support.excluded_reason(surface, support.SEARCH_QUERY) == TOOL_UNAVAILABLE_REASON
        assert support.SEARCH_QUERY not in surface.tool_ids

        goal = make_goal(description="恒不可用工具目标")
        stub_planning_llm(
            sub_goals=[
                _step(support.SEARCH_QUERY, capability="query_search", params={"query": "天气"})
            ]
        )
        outcome = await plan_engine.PlanningEngine().plan(
            goal, _plan_context(goal, surface), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.rejection_reason == REASON_TOOL_OFF_SURFACE

    @pytest.mark.asyncio
    async def test_t3_tripped_tool_is_clipped_by_health(
        self, db_session_factory, planning_gates_on, make_goal, stub_planning_llm
    ):
        from app.services.tool.health import ToolHealthTracker

        registry = get_tool_registry()
        settings = get_settings()
        tracker = ToolHealthTracker(registry, settings)
        for _ in range(tracker.threshold):
            tracker.record_outcome(support.ENV_QUERY, ok=False, failure_kind="transient")
        assert tracker.is_tripped(support.ENV_QUERY) is True

        surface = support.resolve_surface(registry)
        assert support.excluded_reason(surface, support.ENV_QUERY) == "tool_status:tripped"
        assert support.ENV_QUERY not in surface.tool_ids

        goal = make_goal(description="熔断工具目标")
        stub_planning_llm(
            sub_goals=[_step(support.ENV_QUERY, capability="query_environment", params={})]
        )
        outcome = await plan_engine.PlanningEngine().plan(
            goal, _plan_context(goal, surface), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.rejection_reason == REASON_TOOL_OFF_SURFACE

    @pytest.mark.asyncio
    async def test_t4a_channel_tool_is_clipped_by_the_run_profile(
        self, db_session_factory, tools_on, make_goal, stub_planning_llm
    ):
        """自治面（`RUN_KIND_AUTONOMOUS_TICK`）结构性剔除 `channel.*`。"""
        registry = get_tool_registry()
        assert registry is not None and registry.effective_status(support.CHANNEL_SEND) == "enabled"
        surface = support.resolve_surface(registry)
        reason = support.excluded_reason(surface, support.CHANNEL_SEND)
        assert reason is not None and reason.startswith("run_profile:")
        assert support.CHANNEL_SEND not in surface.tool_ids

        goal = make_goal(description="自治面通道工具目标")
        stub_planning_llm(
            sub_goals=[
                _step(support.CHANNEL_SEND, capability="send_notification", params={"content": "该睡了"})
            ]
        )
        outcome = await plan_engine.PlanningEngine().plan(
            goal, _plan_context(goal, surface), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.rejection_reason == REASON_TOOL_OFF_SURFACE

    def test_t4b_channel_tool_is_clipped_by_the_part_of_day(self, tools_on):
        """日时段维度：`late_night` 下 `channel.*` 被剔除，理由前缀 `part_of_day`。"""
        registry = get_tool_registry()
        surface = support.resolve_surface(
            registry,
            run_kind=support.RUN_KIND_FOREGROUND_CHAT,
            ctx=support.tool_context(
                run_kind=support.RUN_KIND_FOREGROUND_CHAT, part_of_day="late_night"
            ),
        )
        assert surface.run_kind == support.RUN_KIND_FOREGROUND_CHAT
        assert support.excluded_reason(surface, support.CHANNEL_SEND) == "part_of_day:late_night"
        assert support.CHANNEL_SEND not in surface.tool_ids

        channel_step = [
            support.spec(1, tool_id=support.CHANNEL_SEND, capability="send_notification")
        ]
        assert PREDICATE(channel_step, registry) is None
        assert SURFACE_PREDICATE(channel_step, surface) == support.CHANNEL_SEND

        daytime = support.resolve_surface(
            registry,
            run_kind=support.RUN_KIND_FOREGROUND_CHAT,
            ctx=support.tool_context(
                run_kind=support.RUN_KIND_FOREGROUND_CHAT, part_of_day="afternoon"
            ),
        )
        assert SURFACE_PREDICATE(channel_step, daytime) is None


class TestSurfaceExplainability:
    """U9 / U10 / I13：八维理由逐条可解释、`surface_hash` 稳定、世界关闭剔除 `world.*`。"""

    def test_u9_every_exclusion_carries_a_reason(self, planning_gates_on, override_settings):
        override_settings(tool_disabled_ids=support.MEMORY_SAVE)
        surface = support.resolve_surface()
        assert surface.excluded
        assert all(entry.get("tool_id") and entry.get("reason") for entry in surface.excluded)

    def test_u9_reason_prefixes_match_the_dimension(self, planning_gates_on, override_settings):
        override_settings(tool_disabled_ids=support.MEMORY_SAVE)
        surface = support.resolve_surface()
        assert support.excluded_reason(surface, support.MEMORY_SAVE) == "tool_status:disabled"
        assert support.excluded_reason(surface, support.SEARCH_QUERY) == TOOL_UNAVAILABLE_REASON

    def test_u10_surface_hash_is_stable_for_the_same_input(self, planning_gates_on):
        first = support.resolve_surface()
        second = support.resolve_surface()
        assert first.surface_hash == second.surface_hash
        assert first.tool_ids == second.tool_ids
        assert first.excluded == second.excluded

    def test_u10_surface_hash_changes_with_the_part_of_day(self, tools_on):
        day = support.resolve_surface(
            run_kind=support.RUN_KIND_FOREGROUND_CHAT,
            ctx=support.tool_context(run_kind=support.RUN_KIND_FOREGROUND_CHAT, part_of_day="afternoon"),
        )
        night = support.resolve_surface(
            run_kind=support.RUN_KIND_FOREGROUND_CHAT,
            ctx=support.tool_context(run_kind=support.RUN_KIND_FOREGROUND_CHAT, part_of_day="late_night"),
        )
        assert day.surface_hash != night.surface_hash


class TestGateFivePassesWhileGateSixRejects:
    """U4（Step 3 专项）：闸门 5 过、闸门 6 拒——判定只读、计划内容不变、该步暂不装配。"""

    def test_u4_gate5_passes_while_gate6_rejects(self, planning_gates_on):
        registry = get_tool_registry()
        specs = [support.spec(1, tool_id=support.SEARCH_QUERY, capability="query_search")]
        before = specs[0].model_dump(mode="json")

        assert PREDICATE(specs, registry) is None
        surface = support.resolve_surface(registry)
        assert SURFACE_PREDICATE(specs, surface) == support.SEARCH_QUERY
        assert specs[0].model_dump(mode="json") == before, "闸门判定必须只读：步骤内容不得被改写"

    def test_u4_the_step_is_assembled_once_the_surface_is_restored(self, planning_gates_on):
        specs = [support.spec(1, tool_id=support.SEARCH_QUERY, capability="query_search")]
        healed = plan5.surface(support.SEARCH_QUERY)
        assert SURFACE_PREDICATE(specs, healed) is None

    def test_u4_an_existing_plan_keeps_its_steps_and_only_defers_assembly(
        self, planning_gates_on
    ):
        """「步数与内容不变」的可判定形态：调度面只推迟装配，不改计划。"""
        plan = plan5.plan([support.spec(1, tool_id=support.SEARCH_QUERY, capability="query_search")])
        before = plan.sub_goals[0].model_dump(mode="json")

        off = plan5.ctx()
        assert [spec.index for spec in plan_scheduler.PlanScheduler.ready_steps(plan)] == [1]
        assert (
            plan_scheduler.PlanScheduler.blocked_reason(plan, off)
            == plan_scheduler.BLOCKED_OFF_SURFACE
        )
        assert plan.sub_goals[0].model_dump(mode="json") == before

        on = plan5.ctx(support.SEARCH_QUERY)
        assert plan_scheduler.PlanScheduler.blocked_reason(plan, on) is None
        assert plan_scheduler.PlanScheduler.current_step(plan).index == 1

    @pytest.mark.asyncio
    async def test_u4_the_rejected_plan_records_only_the_reason_code(
        self, db_session_factory, planning_gates_on, make_goal, stub_planning_llm
    ):
        """规划期闸门 6 拒的落地形态：`rejected` 计划只记理由码，不落被改写的步骤。"""
        from app.repositories import goal_repository

        goal = make_goal(description="专项用例目标")
        stub_planning_llm(
            sub_goals=[
                _step(support.SEARCH_QUERY, capability="query_search", params={"query": "天气"})
            ]
        )
        outcome = await plan_engine.PlanningEngine().plan(
            goal,
            _plan_context(goal, support.resolve_surface()),
            trigger=goal_planning.TRIGGER_CREATED,
        )
        assert outcome.rejection_reason == REASON_TOOL_OFF_SURFACE
        stored = goal_repository.get_plan(outcome.plan.id)
        assert stored.status == "rejected"
        assert stored.rejection_reason == REASON_TOOL_OFF_SURFACE
        assert stored.sub_goals == []

    def test_u4_gate_five_and_six_report_different_tools(self, planning_gates_on):
        """两闸门的判定对象一致但结论可分离：同一工具「可解析」但「不在面」。"""
        registry = get_tool_registry()
        specs = [support.spec(1, tool_id=support.SEARCH_QUERY, capability="query_search")]
        assert registry.resolve(support.SEARCH_QUERY) is not None
        assert PREDICATE(specs, registry) is None
        assert SURFACE_PREDICATE(specs, support.resolve_surface(registry)) == support.SEARCH_QUERY


class TestSurfaceResolverIsNotReimplementedInPlanning:
    """R11 / §10.3：规划层不新增面规则——面只经既有 `ToolSurfaceResolver` 消费。"""

    @staticmethod
    def _package_files():
        return [
            path
            for path in Path(goal_contract.__file__).parent.rglob("*.py")
            if "__pycache__" not in path.parts
        ]

    def test_planning_does_not_reimplement_exclusion_reasons(self):
        for path in self._package_files():
            assert "should_exclude" not in scan.code_text(path), path.name
            assert "STATUS_LABELS" not in scan.code_text(path), path.name

    def test_the_only_surface_consumer_is_the_resolver(self):
        """面解析器只在装配期（`context.py`）与执行期 A2 复核（`executor_bridge.py`）出现。"""
        users = [
            path.name
            for path in self._package_files()
            if "ToolSurfaceResolver" in scan.code_text(path)
        ]
        assert sorted(users) == ["context.py", "executor_bridge.py"]
        assert isinstance(ToolSurfaceResolver, type)
