"""PLAN-008 Step 3：`WorldIntentSubmitter` 未接线断言与 Q5 结论留痕（U8 / I8）。

覆盖 Task Detail §9.1 U8、§9.2 I8；对应 §8 Step 3、§4.2.2 路径 ③、§9.7 Q5。

**Q5 评估结论（本任务内记录，留痕即验收记录）**

> `WorldIntentSubmitter`（`app/services/tool/world_intent.py`，TOOL-007 冻结形状）本版本仍
> `WIRED=False`：计划对世界的改动可由路径 ②（`deferred_world_op` → outbox → `world_engine`）
> 完整覆盖——计划步骤的世界副作用经工具 `effects(kind=world)` 产生、由 outbox 幂等消费，
> 不存在必须由世界侧「按日程/场景裁决」才能表达的写需求。故本版本**不接线**：
> 接线会引入第二条世界写入路径（`world_events(type=character_intent)` 的消费方
> `DailyPlanRunner` / `MovementResolver` 尚未与规划语义对齐），收益不足而风险明确。
> 接线评估（含 `character_intent` 事件类型的消费语义、与 V8 日程裁决的边界）**推后续版本**。

**Q9 交叉引用**：计划完成对 Character State 的间接影响（关系域信号）同样不在本版本扩张，
记录见 `test_plan008_static_scan.py::TestRelationshipBoundary`。

本模块只做**计划侧**的未接线断言：冻结形状本身由 TOOL-007 既有用例
（`tests/v24/test_tool007_intent.py`）守护，PLAN-008 只复核其值集未被改动。
"""

import ast
from pathlib import Path

import pytest

from app.services.tool import world_intent as world_intent_mod
from app.services.tool.world_intent import (
    INTENT_TYPES,
    NOT_WIRED_NOTE,
    STATUS_NOT_WIRED,
    SUBMIT_UNAVAILABLE,
    WIRED,
    WORLD_INTENT_TOOL_ID,
    WorldIntent,
    WorldIntentSubmitter,
    get_world_intent_submitter,
)

from . import plan008_support as support
from . import _plan_scan as scan
from .plan008_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    assembler,
    planning_world_on,
)

USER = support.USER

PLANNING_FORBIDDEN_INTENT_TOKENS = (
    "world_intent",
    "WorldIntentSubmitter",
    "WorldIntent",
    "WORLD_INTENT_TOOL_ID",
    "world.intent.submit",
)


class TestSubmitterStaysUnwired:
    """U8：`WIRED=False` 是 PLAN-008 的未接线锚点（本版本不得翻转）。"""

    def test_wired_is_still_false(self):
        assert WIRED is False
        assert WorldIntentSubmitter().is_wired() is False
        assert get_world_intent_submitter().is_wired() is False

    def test_status_projection_reports_not_wired(self):
        status = get_world_intent_submitter().status()
        assert status["wired"] is False
        assert status["status"] == STATUS_NOT_WIRED
        assert status["tool_id"] == WORLD_INTENT_TOOL_ID
        assert status["writes"] == 0
        assert status["note"] == NOT_WIRED_NOTE

    def test_submit_is_a_zero_write_placeholder(self, db_session_factory, planning_world_on):
        submitter = get_world_intent_submitter()
        intent = WorldIntent(
            user_id=USER, intent_type=INTENT_TYPES[0], reason="计划想让世界整理一下"
        )
        before = support.table_counts(db_session_factory)
        result = submitter.submit(intent, ctx=None)
        after = support.table_counts(db_session_factory)
        assert result == SUBMIT_UNAVAILABLE
        assert after == before
        assert support.world_event_rows(USER) == []


class TestPlanningSideZeroCalls:
    """§5.2 / §6.1：计划层零 `WorldIntentSubmitter` 调用（静态 + 运行时双断言）。"""

    def test_planning_package_holds_no_intent_token(self):
        offenders: dict[str, list[str]] = {}
        for path in support.planning_modules():
            text = scan.code_text(path)
            hits = [token for token in PLANNING_FORBIDDEN_INTENT_TOKENS if token in text]
            imported = {
                module
                for module in scan.imported_modules(path)
                if "world_intent" in module
            }
            if hits or imported:
                offenders[path.name] = sorted(hits | imported)
        assert offenders == {}

    @pytest.mark.asyncio
    async def test_assembly_never_touches_the_submitter(
        self, db_session_factory, planning_world_on, assembler, make_goal, monkeypatch
    ):
        from tests.v24.tool007_support import seed_all

        seed_all(USER)
        calls: list[str] = []
        monkeypatch.setattr(
            world_intent_mod,
            "get_world_intent_submitter",
            lambda: calls.append("factory") or get_world_intent_submitter(),
        )
        monkeypatch.setattr(
            WorldIntentSubmitter, "submit", lambda self, intent, ctx: calls.append("submit")
        )
        goal = make_goal(user_id=USER, description="意图零调用目标")
        result = await assembler.assemble(goal, now=support.NOW)
        assert result.world["weather"] == "sunny"
        assert calls == []

    @pytest.mark.asyncio
    async def test_plan_step_execution_never_touches_the_submitter(
        self, db_session_factory, planning_world_on, monkeypatch, override_settings
    ):
        from app.services.planning.executor_bridge import PlanExecutorBridge
        from app.services.tool.registry import get_tool_registry
        from tests.v24.tool007_support import seed_world

        override_settings(action_outbox_enabled="true")
        seed_world(USER)
        calls: list[str] = []
        monkeypatch.setattr(
            WorldIntentSubmitter, "submit", lambda self, intent, ctx: calls.append("submit")
        )
        goal = support.goal(user_id=USER)
        plan = support.plan([support.step(1)])
        bridge = PlanExecutorBridge(
            registry=get_tool_registry(), session_resolver=lambda _user_id: None
        )
        outcome = await bridge.execute_step(
            goal, plan, plan.sub_goals[0], support.surface_context(support.REMINDER_CREATE)
        )
        assert outcome.status == "succeeded"
        assert calls == []


class TestFrozenShapeIsUnchanged:
    """I8：TOOL-007 冻结形状的取值未被 PLAN-008 改动（权威用例见 `tests/v24/test_tool007_intent.py`）。"""

    def test_frozen_values_are_the_tool_007_ones(self):
        assert WORLD_INTENT_TOOL_ID == "world.intent.submit"
        assert SUBMIT_UNAVAILABLE == "unavailable"
        assert STATUS_NOT_WIRED == "not_wired"
        assert INTENT_TYPES == ("tidy_room", "move_location", "start_activity")
        assert "character_intent" in NOT_WIRED_NOTE

    def test_module_has_no_write_surface(self):
        """形状冻结的写面证据：模块零仓储导入、零 outbox 投递、零世界写调用。"""
        path = Path(world_intent_mod.__file__)
        imported = scan.imported_modules(path)
        assert not [
            module
            for module in imported
            if module.startswith("app.repositories") or module.startswith("app.application")
        ]
        code = scan.code_text(path)
        assert "outbox" not in code
        assert "SessionLocal" not in code

    def test_planning_package_does_not_import_the_intent_module(self):
        offenders = [
            path.name
            for path in support.planning_modules()
            if any(
                isinstance(node, ast.ImportFrom) and "world_intent" in (node.module or "")
                for node in ast.walk(scan.tree(path))
            )
        ]
        assert offenders == []


class TestForwardPathThreeStaysOpen:
    """§4.2.2 路径 ③ 的状态：形状在位、调用面为零（本版本）与接线时点的可判定依据。"""

    def test_path_three_reserved_but_not_wired(self):
        assert hasattr(WorldIntentSubmitter, "submit")
        assert WorldIntentSubmitter().status()["writes"] == 0
        assert WIRED is False

    def test_path_two_is_the_only_plan_side_world_change_expression(self):
        """路径 ② 的产出面（工具能力）与计划层的零产出并列断言：Q5 结论的可判定依据。"""
        produced = support.produced_op_literals()
        assert {op for ops in produced.values() for op in ops} <= set(
            support.WORLD_OP_WHITELIST
        )
        assert "world_intent.py" not in produced
