"""PLAN-008 Step 1：九类世界事实装配（U1~U5 / I3 / S1）。

覆盖 Task Detail §9.1 U1~U5、§9.2 I3、§9.3 S1；对应 §8 Step 1 与 §4.2.1 表。

口径（按真实源码冻结，已在用例中留痕）

1. **① 时间 / ③ 地点不走 `world_engine` 的同名包装**：`build_time_context` /
   `get_location_context` 内部 `ensure_world`（写路径：缺世界记录即建档、家庭库存缺省即播种），
   与 §6.1 D1 / §10.2 「世界事实装配全程只读」冲突；本任务取同一事实的只读内核
   `TimeProvider.context(world)` / `build_location_context(world)`（先例：TOOL-007 模块文档）。
   故本模块的 §4.2.1 读入口逐字对照为：① `TimeProvider.context`、③ `locations.build_location_context`，
   其余七项与文档表格一致。
2. **④ 的双态是「有物 / 无物」**：`world_engine.get_objects_by_location` 内部吞异常返回 `[]`
   （既有实现），故「读失败」在数据层不可判；本模块仍保留 try/except 兜底并登记
   `world_objects_unavailable`，但**可用性判定以数据为准**（空清单 = 不可用态）。
3. **`degraded` 契约演进**：World 源由三段一体细化为九段逐段可降级，`PLAN_DEGRADED_REASONS`
   新增七条世界段标记（改动留痕见 `test_plan003_context.py::TestDegradedRegistry`）；
   `world_enabled=False` 仍只登记 `world_disabled` 一条。
"""

from datetime import datetime

import pytest

from app.application import world_engine
from app.models.plan import PlanContext
from app.models.world import WorldContext
from app.models.world_simulation import WorldBrief
from app.repositories import world_repository
from app.services.planning import context as plan_context
from tests.v24.tool007_support import (
    LOCATION,
    seed_all,
    seed_event,
    seed_object,
    seed_situation,
    seed_world,
)

from . import plan008_support as support
from .plan008_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    assembler,
    planning_world_on,
)

V25_NOW = support.NOW
USER = support.USER

TOP_LEVEL_FACT_KEYS = (
    "part_of_day",
    "weather",
    "location",
    "nearby_objects",
    "active_events",
)


@pytest.fixture
def world_ready(db_session_factory):
    """九段可用的世界夹具：世界 + 两件物品 + 一条处境 + 一条事件（日程块一并播种）。"""
    seed_all(USER, location=LOCATION, weather="sunny")
    return USER


def _world_codes(context) -> list[str]:
    return [
        code
        for code in context.degraded
        if code.startswith("world_") and code != plan_context.DEGRADED_WORLD_DISABLED
    ]


class TestNineWorldFacts:
    """U1：九项各有「可用 / 不可用」两态，且不可用态逐段登记稳定降级码。"""

    @pytest.mark.asyncio
    async def test_s1_nine_facts_are_traceable_in_one_assembly(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready
    ):
        """S1：「帮我规划一次旅行」——九项世界事实在同一份 `PlanContext` 中可逐项追溯。"""
        goal = make_goal(user_id=USER, description="帮我规划一次旅行")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.world["part_of_day"]
        assert result.world["weather"] == "sunny"
        assert result.world["location"] == LOCATION
        assert result.world["location_name"]
        assert result.world["available_actions"]
        assert result.world["nearby_objects"]
        assert result.world["active_events"]
        assert [situation.dimension.value for situation in result.situations] == ["health"]
        assert result.scene is not None
        assert result.world_brief is not None and result.world_brief.text
        assert result.world_context is not None
        assert result.world_context.inventory
        assert _world_codes(result) == []
        assert plan_context.DEGRADED_WORLD_DISABLED not in result.degraded

    @pytest.mark.asyncio
    async def test_time_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready
    ):
        goal = make_goal(user_id=USER, description="时段目标")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.world["part_of_day"] == available.world_context.time.part_of_day

    @pytest.mark.asyncio
    async def test_time_fact_degrades_when_the_provider_raises(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="时段降级目标")

        def _boom(self, world):
            raise RuntimeError("时间上下文失败")

        monkeypatch.setattr(plan_context.TimeProvider, "context", _boom)
        monkeypatch.setattr(world_engine, "build_context", lambda *args, **kwargs: None)
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert plan_context.DEGRADED_WORLD_TIME_UNAVAILABLE in result.degraded
        assert result.world_brief is None
        assert plan_context.DEGRADED_WORLD_BRIEF_UNAVAILABLE in result.degraded

    @pytest.mark.asyncio
    async def test_environment_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="环境目标")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.world["weather"] == "sunny"
        assert "salient_events" in available.world

        monkeypatch.setattr(world_engine, "collect_facts", lambda *args, **kwargs: {})
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert "weather" not in empty.world
        assert plan_context.DEGRADED_WORLD_ENVIRONMENT_UNAVAILABLE in empty.degraded

    @pytest.mark.asyncio
    async def test_location_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="地点目标")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.world["location"] == LOCATION
        assert available.world["location_name"] == "客厅"
        assert available.world["available_actions"]

        monkeypatch.setattr(plan_context, "build_location_context", lambda world: None)
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert "location_name" not in empty.world
        assert "available_actions" not in empty.world
        assert plan_context.DEGRADED_WORLD_LOCATION_UNAVAILABLE in empty.degraded

    @pytest.mark.asyncio
    async def test_objects_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch
    ):
        seed_world(USER, location=LOCATION)
        goal = make_goal(user_id=USER, description="物品目标")
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert empty.world["nearby_objects"] == []
        assert empty.world["nearby_object_count"] == 0

        seed_object(USER, "牛奶")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.world["nearby_objects"] == ["牛奶"]
        assert available.world_context.inventory

    @pytest.mark.asyncio
    async def test_objects_fact_degrades_on_read_failure(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="物品降级目标")

        def _boom(*args, **kwargs):
            raise RuntimeError("物品查询失败")

        monkeypatch.setattr(world_engine, "get_objects_by_location", _boom)
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert "nearby_objects" not in result.world
        assert plan_context.DEGRADED_WORLD_OBJECTS_UNAVAILABLE in result.degraded

    @pytest.mark.asyncio
    async def test_events_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch
    ):
        seed_world(USER, location=LOCATION)
        goal = make_goal(user_id=USER, description="事件目标")
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert empty.world["active_events"] == []

        seed_event(USER, title="复查", event_type="reminder")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert [item["event_type"] for item in available.world["active_events"]] == ["reminder"]

    @pytest.mark.asyncio
    async def test_events_fact_degrades_on_read_failure(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="事件降级目标")

        def _boom(*args, **kwargs):
            raise RuntimeError("事件查询失败")

        monkeypatch.setattr(world_engine, "list_active_events", _boom)
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert "active_events" not in result.world
        assert plan_context.DEGRADED_WORLD_EVENTS_UNAVAILABLE in result.degraded

    @pytest.mark.asyncio
    async def test_situation_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch
    ):
        seed_world(USER, location=LOCATION)
        goal = make_goal(user_id=USER, description="处境目标")
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert empty.situations == []

        seed_situation(USER)
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert [situation.dimension.value for situation in available.situations] == ["health"]

    @pytest.mark.asyncio
    async def test_scene_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch
    ):
        seed_world(USER, location=LOCATION)
        goal = make_goal(user_id=USER, description="场景目标")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.scene is not None
        assert available.scene.location_id == LOCATION

        monkeypatch.setattr(world_engine, "get_world", lambda user_id: None)
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert empty.scene is None
        assert plan_context.DEGRADED_SCENE_UNAVAILABLE in empty.degraded

    @pytest.mark.asyncio
    async def test_brief_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="简报目标")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.world_brief is not None
        assert available.world_brief.text

        monkeypatch.setattr(
            plan_context.world_brief_service,
            "build_world_brief",
            lambda *args, **kwargs: WorldBrief(text=""),
        )
        monkeypatch.setattr(
            world_engine, "build_context", lambda *args, **kwargs: None
        )
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert empty.world_brief is None
        assert plan_context.DEGRADED_WORLD_BRIEF_UNAVAILABLE in empty.degraded

    @pytest.mark.asyncio
    async def test_world_context_fact_available_and_unavailable(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="世界切片目标")
        available = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(available, PlanContext)
        assert available.world_context is not None

        monkeypatch.setattr(world_engine, "build_context", lambda *args, **kwargs: None)
        empty = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(empty, PlanContext)
        assert empty.world_context is None
        assert plan_context.DEGRADED_WORLD_CONTEXT_UNAVAILABLE in empty.degraded


class TestWorldDisabled:
    """U2 / D4：无世界记录 → World 源全空 + `degraded` 含 `world_disabled`（仅此一条）。

    D4 的「九项全空」在 World 源内逐项成立（①~⑤、⑧、⑨）；⑥ 处境取自
    `world_simulation_repository`、⑦ 场景取自角色资产，属 Context 源：⑦ 因缺地点
    `scene_unavailable`，⑥ 的可用性只取决于该表的数据面——**世界记录缺失与处境表
    无门控关系**（PLAN-003 既有语义，本任务零改动），故本用例不断言 ⑥ 为空（人造的
    「无世界记录 + 处境表非空」组合下它仍有值；这正是「逐段可降级」与「同开同关」的区别）。
    """

    @pytest.mark.asyncio
    async def test_world_record_missing_degrades_without_creating_one(
        self, db_session_factory, planning_world_on, assembler, make_goal
    ):
        goal = make_goal(user_id=USER, description="无世界记录目标")
        assert world_repository.get_world(USER) is None
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.degraded[0] == plan_context.DEGRADED_WORLD_DISABLED
        assert world_repository.get_world(USER) is None


class TestGoalOpportunity:
    """U3：`EventImpact.goal_opportunity` 并入 `world["active_events"]`（规划素材）。"""

    @pytest.mark.asyncio
    async def test_goal_opportunity_lands_in_active_events(
        self, db_session_factory, planning_world_on, assembler, make_goal
    ):
        seed_world(USER, location=LOCATION)
        world_engine.create_event(
            USER,
            "user_condition",
            "用户状态",
            "high",
            None,
            "simulation",
            "active",
            {"kind": "detected", "intensity": 5, "dimension": "health", "summary": "作息紊乱"},
        )
        goal = make_goal(user_id=USER, description="机会目标")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        entry = result.world["active_events"][0]
        assert entry["event_type"] == "user_condition"
        assert entry["urgency"] == "high"
        assert entry["goal_opportunity"] == {
            "domain": "user_care",
            "type": "care_health",
            "hint": "关心用户：作息紊乱",
            "layer": "short_term",
        }

    @pytest.mark.asyncio
    async def test_active_events_are_bounded_and_sorted_by_urgency(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch
    ):
        from app.services.world import event_impact

        seed_world(USER, location=LOCATION)
        goal = make_goal(user_id=USER, description="事件有界目标")
        monkeypatch.setattr(
            world_engine,
            "list_active_events",
            lambda user_id: [object()] * (plan_context.WORLD_ACTIVE_EVENTS_LIMIT + 3),
        )
        monkeypatch.setattr(
            event_impact,
            "evaluate_batch",
            lambda events, context: [
                event_impact.EventImpact(
                    event_id=str(index),
                    event_type="reminder",
                    urgency="high" if index == 0 else "low",
                    care_relevance=0.5,
                    topic_value=0.3,
                    goal_opportunity=(
                        event_impact.GoalHint("user_care", "remind_weather", "提醒用户注意天气")
                        if index == 0
                        else None
                    ),
                )
                for index in range(len(events))
            ],
        )
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        events = result.world["active_events"]
        assert len(events) == plan_context.WORLD_ACTIVE_EVENTS_LIMIT
        assert events[0]["goal_opportunity"]["type"] == "remind_weather"
        assert events[0]["urgency"] == "high"

    @pytest.mark.asyncio
    async def test_impact_context_carries_only_part_of_day(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        """⑤ 的裁决上下文只注入 `part_of_day`（模块文档实现核对 2）。"""
        seen: dict = {}
        from app.services.world import event_impact

        original = event_impact.evaluate_batch

        def _spy(events, context=None):
            seen["context"] = context
            return original(events, context)

        monkeypatch.setattr(event_impact, "evaluate_batch", _spy)
        goal = make_goal(user_id=USER, description="裁决上下文目标")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert seen["context"] == {"part_of_day": result.world["part_of_day"]}


class TestWorldBriefBudget:
    """U4 / D5：`world_brief` 长度 ≤ `world_brief_char_budget`（复用与重装两条路径）。"""

    @pytest.mark.asyncio
    async def test_reused_brief_stays_within_budget(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, override_settings
    ):
        goal = make_goal(user_id=USER, description="简报预算目标")
        override_settings(world_brief_char_budget="40")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.world_brief is not None
        assert len(result.world_brief.text) <= 40

    @pytest.mark.asyncio
    async def test_oversized_reuse_is_rebuilt_within_budget(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch, override_settings
    ):
        goal = make_goal(user_id=USER, description="简报重装目标")
        override_settings(world_brief_char_budget="30")
        real_build_context = world_engine.build_context

        def _oversized(user_id, session_id=None, trace=None):
            context = real_build_context(user_id, session_id, trace)
            assert context is not None
            return context.model_copy(
                update={"brief": WorldBrief(text="很长的简报" * 200)}
            )

        monkeypatch.setattr(world_engine, "build_context", _oversized)
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert isinstance(result.world_context, WorldContext)
        assert result.world_brief is not None
        assert len(result.world_brief.text) <= 30
        assert result.world_brief.text != "很长的简报" * 200


class TestDegradedCodes:
    """U5：`degraded` 元素为稳定字符串，且九段标记全部登记进冻结值集。"""

    def test_world_segment_codes_are_frozen_lowercase_ascii(self):
        world_codes = tuple(
            code
            for code in plan_context.PLAN_DEGRADED_REASONS
            if code.startswith("world_") and code != plan_context.DEGRADED_WORLD_DISABLED
        )
        assert world_codes == (
            "world_time_unavailable",
            "world_environment_unavailable",
            "world_location_unavailable",
            "world_objects_unavailable",
            "world_events_unavailable",
            "world_brief_unavailable",
            "world_context_unavailable",
        )
        assert all(code == code.lower() and code.isascii() for code in world_codes)

    def test_world_read_entries_are_the_frozen_read_only_face(self):
        assert plan_context.WORLD_READ_ENTRIES == (
            "get_world",
            "collect_facts",
            "get_objects_by_location",
            "list_active_events",
            "build_context",
        )


class TestAssemblyZeroWrite:
    """I3 / §10.2：世界事实装配全程只读——零世界写函数、零仓储直写、表计数不变。"""

    @pytest.mark.asyncio
    async def test_assembly_calls_no_world_write_face(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch
    ):
        seed_all(USER, location=LOCATION)
        world_engine.seed_default_household(USER)
        probe = support.install_world_write_probe(monkeypatch)
        goal = make_goal(user_id=USER, description="装配零写目标")
        before = support.table_counts(db_session_factory)
        result = await assembler.assemble(goal, now=V25_NOW)
        after = support.table_counts(db_session_factory)
        assert isinstance(result, PlanContext)
        assert probe.written == []
        assert probe.direct == []
        assert before == after

    @pytest.mark.asyncio
    async def test_assembly_never_touches_run_turn_update_or_maintenance(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch, world_ready
    ):
        called: list[str] = []

        def _record(name: str):
            def _call(*args, **kwargs):
                called.append(name)
                return 0

            return _call

        for name in ("run_turn_update", "run_maintenance", "run_simulation_maintenance"):
            monkeypatch.setattr(world_engine, name, _record(name))
        goal = make_goal(user_id=USER, description="零写路径目标")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert result.world_context is not None
        assert called == []

    @pytest.mark.asyncio
    async def test_assembly_reads_only_through_the_declared_entries(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready, monkeypatch
    ):
        """I1（装配侧）：九段的读入口逐项经过，且都出自 `WORLD_READ_ENTRIES`。"""
        seen: list[str] = []
        for name in plan_context.WORLD_READ_ENTRIES:
            original = getattr(world_engine, name)

            def _spy(*args, _name=name, _original=original, **kwargs):
                seen.append(_name)
                return _original(*args, **kwargs)

            monkeypatch.setattr(world_engine, name, _spy)
        goal = make_goal(user_id=USER, description="读入口目标")
        result = await assembler.assemble(goal, now=V25_NOW)
        assert isinstance(result, PlanContext)
        assert set(seen) == set(plan_context.WORLD_READ_ENTRIES)

    @pytest.mark.asyncio
    async def test_assembly_sees_the_time_provider_clock_not_a_frozen_now(
        self, db_session_factory, planning_world_on, assembler, make_goal, world_ready
    ):
        """① 的时刻取自世界时钟（既有 `TimeProvider`），与调用方 `now` 无关。"""
        goal = make_goal(user_id=USER, description="世界时钟目标")
        result = await assembler.assemble(goal, now=datetime(2030, 1, 1, 3, 0, 0))
        assert isinstance(result, PlanContext)
        assert result.world["part_of_day"] == result.world_context.time.part_of_day
        assert result.world_context.time.now.year != 2030
