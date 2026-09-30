"""PLAN-006 Step 8 / Step 7：结果契约归一、扩展工具一视同仁、Flag off 与 V2.4.0 一致。

覆盖 Task Detail §9.1 U11~U16 与 §9.2 I14 的可判定部分；对应 §8 Step 7 与 Step 8。

三处口径说明（均按真实源码冻结，已在用例中留痕）

1. **`timeout` 行按 PLAN-005 的冻结形态断言**：§4.3.2 表把 `ToolExecutionStatus.timeout`
   映射为 `PlanStepOutcome.status="timeout"`，而 PLAN-005 的实现以
   `status="failed" + failure_kind="timeout"` 表达（`PLAN_STEP_ATTEMPT_INCREMENT_STATUSES`
   只有 `succeeded` / `failed`，否则 `attempt_count` 会漏计）。本模块按实现断言，
   并同时断言「Action 台账侧 `timeout` → `failed`」一行与 §4.3.2 完全一致。
2. **`tool_id` 差异回填用动作台账构造**：链路端到端选到另一个工具需要通道能力实现体
   （会真实外发），故差异回填按 §4.2.6 的判据直接构造
   ——`PlanStepOutcome.tool_id` 取 `record.steps[0].tool_id`（实际执行），与计划绑定的
   `tool_id` 不同不视为错误，且**不改写计划步骤**。
3. **Flag off 的「逐字节一致」由既有对照承担**：本模块断言「绑定子闸 off 时工具面不参与规划
   （`tool_id` 不由 PLANNING 写入、绑定只在执行期发生）」，prompt 与行为的逐字节一致由
   `test_plan004_flags.py` 与 `pytest -m golden` 承担（不在此重复实现快照）。
"""

import pytest

from app.application import action_engine
from app.models.action import ActionRecord
from app.models.goal import SubGoalSpec
from app.models.plan import PlanContext
from app.models.tool import TOOL_EFFECT_KIND_VALUES, TOOL_FAILURE_KINDS, ToolSurface
from app.services.goal import planning as goal_planning
from app.services.action.planner import assemble_plan
from app.services.planning import executor_bridge as bridge_mod
from app.services.planning.executor_bridge import PlanExecutorBridge
from app.services.planning import context as plan_context
from app.services.planning import engine as plan_engine
from app.services.tool.registry import ToolRegistry, get_tool_registry
from tests.v24.tool003_support import StubCapability, stub_registry
from tests.v24.tool005_support import ext_definition, untrusted_definition

from . import plan004_support as plan4
from . import plan005_support as plan5
from . import plan006_support as support
from .plan006_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    action_chain_on,
    planning_gates_on,
    repo_write_probe,
    tools_on,
)

USER = support.USER
MEMORY_TOOL = support.MEMORY_SAVE
REMINDER_TOOL = support.REMINDER_CREATE
EXT_TOOL = "ext.api.push.write"
USER_TOOL = "user.notes.delete"

BRIDGE = PlanExecutorBridge(registry=None, session_resolver=lambda _user_id: None)

STATE_MAPPING_ROWS = (
    ("succeeded", "succeeded", None, "succeeded", None),
    ("failed", "failed", None, "failed", "permanent"),
    ("timeout", "failed", "timeout", "failed", "timeout"),
    ("unavailable", "cancelled", "unavailable", "blocked", "unavailable"),
    ("denied", "cancelled", "denied", "blocked", "denied"),
    ("invalid", "cancelled", "invalid", "blocked", "invalid"),
    ("pending_confirmation", "planned", None, "blocked", None),
)
"""§4.3.2 七行的可判定形式：

`(ToolExecutionStatus, ActionRecord.status, ToolResult.failure_kind, PlanStepOutcome.status,
PlanStepOutcome.failure_kind)`。

`timeout` 行按 PLAN-005 的冻结形态（`status="failed"` + `failure_kind="timeout"`，见模块文档 1）；
`failed` 行给一个**不携带** `failure_kind` 的 `ToolResult`，`PlanStepOutcome` 按既有收敛记 `permanent`。
"""

TERMINAL_RECORD_STATUS_BY_TOOL_STATUS = {
    "succeeded": "succeeded",
    "failed": "failed",
    "timeout": "failed",
}
"""已触达能力的三种终态（`_settle_executed_record` 的重试分支已在 Action 层收敛）。"""

TOOL_STEP_STATUS_BY_TOOL_STATUS = {
    "succeeded": "succeeded",
    "failed": "failed",
    "timeout": "failed",
    "unavailable": "skipped",
    "denied": "skipped",
    "invalid": "skipped",
    "pending_confirmation": "skipped",
}
"""v26 去门控（批次 7）：原 `action_engine._TOOL_STEP_STATUSES` 冻结表随 ToolExecutor
分派路径删除而本地化为构造输入（值不变，仍按七行契约逐条使用）。"""

RECORD_OUTCOMES_BY_TOOL_STATUS = {
    "unavailable": ("cancelled", "capability_unavailable"),
    "denied": ("cancelled", "permission_denied"),
    "invalid": ("cancelled", "invalid_params"),
    "pending_confirmation": ("planned", "pending_confirmation"),
}
"""原 `action_engine._TOOL_RECORD_OUTCOMES` 冻结表本地化（同上）。"""


def _plan_context(goal, surface) -> PlanContext:
    return PlanContext(
        goal=goal,
        tool_surface=surface,
        budget=plan_context.plan_budget(_settings()),
    )


def _settings():
    from app.core.settings import get_settings

    return get_settings()


def _record_for(tool_status: str, *, tool_id: str = MEMORY_TOOL, failure_kind: str | None = None):
    """按引擎的冻结映射表构造工具状态对应的动作台账终态（`steps[0].result` 为 ToolResult 形状）。"""
    if tool_status in TERMINAL_RECORD_STATUS_BY_TOOL_STATUS:
        record_status, gate_reason = (
            TERMINAL_RECORD_STATUS_BY_TOOL_STATUS[tool_status],
            None,
        )
    else:
        record_status, gate_reason = RECORD_OUTCOMES_BY_TOOL_STATUS[tool_status]
    return ActionRecord(
        id="act-plan6",
        user_id=USER,
        action_type="remember_fact",
        status=record_status,
        gate_reason=gate_reason,
        steps=[
            {
                "index": 1,
                "capability": "memory",
                "action": "save",
                "params": {},
                "status": TOOL_STEP_STATUS_BY_TOOL_STATUS[tool_status],
                "tool_id": tool_id,
                "result": {
                    "status": tool_status,
                    "effects": [],
                    "observations": {},
                    "failure_kind": failure_kind,
                    "usage": {"duration_ms": 7},
                },
                "permission": {},
                "validation": None,
                "duration_ms": 7,
            }
        ],
        attempt=1,
        created_at=support.NOW,
        updated_at=support.NOW,
    )


class TestStateMapping:
    """U11：`ToolExecutionStatus → ActionRecord.status → PlanStepOutcome.status` 七行逐条一致。"""

    def test_engine_side_tables_are_gone(self):
        """v26 去门控（批次 7）：ToolExecutor 分派路径删除，引擎侧冻结表随之消失；
        七行契约的输入构造本地化到本模块（见文件头的两张本地表）。"""
        assert not hasattr(action_engine, "_TOOL_STEP_STATUSES")
        assert not hasattr(action_engine, "_TOOL_RECORD_OUTCOMES")

    @pytest.mark.parametrize(
        ("tool_status", "action_status", "record_failure_kind", "step_status", "failure_kind"),
        STATE_MAPPING_ROWS,
    )
    def test_seven_rows_map_end_to_end(
        self, tool_status, action_status, record_failure_kind, step_status, failure_kind
    ):
        record = _record_for(tool_status, failure_kind=record_failure_kind)
        assert record.status == action_status
        step = plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL)
        outcome = bridge_mod._normalize(step, record, support.NOW)
        assert outcome.status == step_status
        assert outcome.failure_kind == failure_kind

    def test_gate_reason_mapping_table_covers_the_four_blocked_classes(self):
        assert bridge_mod.GATE_REASON_OUTCOMES["capability_unavailable"] == ("blocked", "unavailable")
        assert bridge_mod.GATE_REASON_OUTCOMES["permission_denied"] == ("blocked", "denied")
        assert bridge_mod.GATE_REASON_OUTCOMES["invalid_params"] == ("blocked", "invalid")
        assert bridge_mod.GATE_REASON_OUTCOMES["pending_confirmation"] == ("blocked", None)


class TestFailureKindValueDomain:
    """U12 / D8：`failure_kind` 全部 ⊆ 既有 `TOOL_FAILURE_KINDS`（6 值），不新增。"""

    @pytest.mark.parametrize("kind", TOOL_FAILURE_KINDS)
    def test_declared_kinds_are_passed_through(self, kind):
        record = _record_for("failed")
        record.steps[0]["result"]["failure_kind"] = kind
        outcome = bridge_mod._normalize(
            plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL), record, support.NOW
        )
        assert outcome.failure_kind == kind
        assert outcome.failure_kind in TOOL_FAILURE_KINDS

    def test_unknown_kind_collapses_to_permanent(self):
        record = _record_for("failed")
        record.steps[0]["result"]["failure_kind"] = "not_a_kind"
        outcome = bridge_mod._normalize(
            plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL), record, support.NOW
        )
        assert outcome.failure_kind == "permanent"

    def test_no_new_failure_kind_is_declared_in_planning(self):
        from app.models.plan import PLAN_STEP_OUTCOME_VALUES

        assert TOOL_FAILURE_KINDS == (
            "transient",
            "permanent",
            "timeout",
            "unavailable",
            "denied",
            "invalid",
        )
        assert "not_a_kind" not in TOOL_FAILURE_KINDS
        assert PLAN_STEP_OUTCOME_VALUES


class TestEffectsAndObservationsProjection:
    """U13 / §4.2.6：`effects` 投影三键 + `observations` 白名单裁剪。"""

    def test_effects_projection_keeps_three_keys_and_the_declared_kinds(self):
        record = _record_for("succeeded")
        record.steps[0]["result"]["effects"] = [
            {"kind": "world", "ref": "ev-1", "reversible": True, "detail": "不应进投影"},
            {"kind": "memory", "ref": "m-1"},
        ]
        outcome = bridge_mod._normalize(
            plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL), record, support.NOW
        )
        assert outcome.effects == [
            {"kind": "world", "ref": "ev-1", "reversible": True},
            {"kind": "memory", "ref": "m-1", "reversible": False},
        ]
        assert all(effect["kind"] in TOOL_EFFECT_KIND_VALUES for effect in outcome.effects)

    def test_malformed_effects_are_dropped(self):
        record = _record_for("succeeded")
        record.steps[0]["result"]["effects"] = ["not-a-dict", {"ref": "no-kind"}]
        outcome = bridge_mod._normalize(
            plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL), record, support.NOW
        )
        assert outcome.effects == []

    def test_observations_are_clipped_by_the_step_whitelist(self):
        record = _record_for("succeeded")
        record.steps[0]["result"]["observations"] = {"memory.id": "m-1", "internal.debug": "x"}
        clipped = bridge_mod._normalize(
            plan5.spec(
                1, capability="remember_fact", tool_id=MEMORY_TOOL, observation_keys=("memory.id",)
            ),
            record,
            support.NOW,
        )
        assert clipped.observations == {"memory.id": "m-1"}
        declared_none = bridge_mod._normalize(
            plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL), record, support.NOW
        )
        assert declared_none.observations == {}

    @pytest.mark.asyncio
    async def test_observations_from_the_real_normalizer_are_clipped(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """端到端：真实 `ObservationNormalizer` 产出的 observations 也被白名单裁剪。

        v26 去门控裁决 B：工具绑定优先路由恢复后，工具归一观测保持 dotted key
        （`memory.id`，工具定义声明形）；计划步 `observation_keys` 裁剪语义不变。
        """

        capability = StubCapability(
            name="memory",
            action="save",
            required=["fact"],
            behavior=lambda _params, _ctx: _memory_result(),
        )
        monkeypatch.setattr(action_engine, "get_capability_registry", lambda: stub_registry(capability))

        clipped_step = plan5.spec(
            1,
            capability="remember_fact",
            tool_id=MEMORY_TOOL,
            params={"fact": "小明喜欢喝咖啡"},
            observation_keys=("memory.id",),
        )
        plan = plan5.plan([clipped_step])
        outcome = await PlanExecutorBridge(
            registry=get_tool_registry(), session_resolver=lambda _user_id: None
        ).execute_step(plan5.goal(user_id=USER), plan, plan.sub_goals[0], plan5.ctx(MEMORY_TOOL))
        assert outcome.status == "succeeded"
        assert outcome.observations == {"memory.id": "m-1"}

        bare = plan5.plan(
            [
                plan5.spec(
                    1, capability="remember_fact", tool_id=MEMORY_TOOL, params={"fact": "x"}
                )
            ],
            version=2,
        )
        second = await PlanExecutorBridge(
            registry=get_tool_registry(), session_resolver=lambda _user_id: None
        ).execute_step(
            plan5.goal(user_id=USER), bare, bare.sub_goals[0], plan5.ctx(MEMORY_TOOL)
        )
        assert second.status == "succeeded"
        assert second.observations == {}


def _memory_result():
    from app.models.action import CapabilityResult

    return CapabilityResult(status="succeeded", payload={"memory_id": "m-1"}, usage={})


class TestToolIdBackfill:
    """U16 / §4.2.6：`tool_id` 取实际执行的工具，差异不视为错误、不改写计划。"""

    def test_outcome_carries_the_executed_tool_id(self):
        record = _record_for("succeeded", tool_id=support.CHANNEL_SEND)
        step = plan5.spec(1, capability="remember_fact", tool_id=REMINDER_TOOL)
        before = step.model_dump(mode="json")
        outcome = bridge_mod._normalize(step, record, support.NOW)
        assert outcome.tool_id == support.CHANNEL_SEND
        assert outcome.tool_id != step.tool_id
        assert step.model_dump(mode="json") == before, "差异回填不得改写计划步骤"

    def test_outcome_falls_back_to_the_planned_tool_when_the_record_is_silent(self):
        record = ActionRecord(
            id="act-plan6-none",
            user_id=USER,
            action_type="remember_fact",
            status="cancelled",
            gate_reason="capability_unavailable",
            steps=[],
            attempt=1,
            created_at=support.NOW,
            updated_at=support.NOW,
        )
        step = plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL)
        outcome = bridge_mod._normalize(step, record, support.NOW)
        assert outcome.tool_id == MEMORY_TOOL
        assert outcome.status == "blocked"

    def test_audit_hint_is_recorded_in_the_intent_evidence(self):
        """差异可审计：执行期工具的候选与选择理由经 `ToolSelector` 可复现（同函数同规则）。"""
        from app.services.tool.surface import ToolSelector

        registry = support.builtin_registry()
        intent = bridge_mod.PlanExecutorBridge(registry=registry).to_intent(
            plan5.goal(user_id=USER),
            plan5.plan([plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL)]),
            plan5.spec(1, capability="remember_fact", tool_id=MEMORY_TOOL),
            plan5.ctx(),
        )
        selection = ToolSelector(registry).select_with_reason(
            intent, ToolSurface(run_kind="foreground_chat", tool_ids=(MEMORY_TOOL,))
        )
        assert selection.binding is not None
        assert selection.binding.tool_id == MEMORY_TOOL
        assert selection.reason == "priority_order"
        assert intent.evidence.startswith("计划步骤 1：")


class TestExtensionNamespacesAreTreatedAlike:
    """U14 / Step 7.1：`ext.api.*` / `user.*` 在面上且可解析时可被规划（零特判）。"""

    def _registry(self) -> ToolRegistry:
        from app.services.action.registry import get_capability_registry

        registry = ToolRegistry()
        registry.register(ext_definition(), get_capability_registry().get("notification"))
        registry.register(untrusted_definition(), get_capability_registry().get("memory"))
        return registry

    @pytest.mark.asyncio
    async def test_extension_tools_are_planned_when_they_are_on_the_surface(
        self, db_session_factory, planning_gates_on, make_goal, stub_planning_llm, monkeypatch
    ):
        from app.repositories import goal_repository

        registry = self._registry()
        monkeypatch.setattr(plan_engine, "get_tool_registry", lambda: registry)
        surface = support.resolve_surface(
            registry, run_kind=support.RUN_KIND_FOREGROUND_CHAT
        )
        assert EXT_TOOL in surface.tool_ids and USER_TOOL in surface.tool_ids
        assert plan_engine._evaluate_tool_resolvable(
            [support.spec(1, tool_id=EXT_TOOL)], registry
        ) is None

        goal = make_goal(description="扩展工具规划目标")
        stub_planning_llm(
            sub_goals=[
                {
                    "index": 1,
                    "description": "外部推送",
                    "capability": "send_notification",
                    "params": {"content": "推送"},
                    "criteria": {"type": "action_succeeded", "capability": "send_notification"},
                    "tool_id": EXT_TOOL,
                }
            ]
        )
        outcome = await plan_engine.PlanningEngine().plan(
            goal, _plan_context(goal, surface), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        stored = goal_repository.get_plan(outcome.plan.id)
        assert [spec.tool_id for spec in stored.sub_goals] == [EXT_TOOL]

    def test_every_action_type_accepts_an_extension_tool_binding(self):
        """一视同仁的可判定形式：绑定判定只看「可解析 + 在面上」，不看命名空间。"""
        registry = self._registry()
        surface = support.resolve_surface(registry, run_kind=support.RUN_KIND_FOREGROUND_CHAT)
        for tool_id in (EXT_TOOL, USER_TOOL):
            assert registry.resolve(tool_id) is not None
            assert tool_id in surface.tool_ids
            assert plan_engine._evaluate_tool_resolvable(
                [support.spec(1, tool_id=tool_id)], registry
            ) is None

    def test_extension_tools_are_not_rejected_by_the_permission_floor_in_planning(self):
        """权限下限属执行期（`ToolPermissionGate`）：规划期不裁决，只问可解析与在面上。"""
        from app.models.tool import namespace_permission_floor

        assert namespace_permission_floor("ext.api") == "sensitive"
        assert namespace_permission_floor("user") == "dangerous"
        registry = self._registry()
        for tool_id in (EXT_TOOL, USER_TOOL):
            assert plan_engine._evaluate_tool_on_surface(
                [support.spec(1, tool_id=tool_id)],
                support.resolve_surface(registry, run_kind=support.RUN_KIND_FOREGROUND_CHAT),
            ) is None


class TestFlagOffKeepsTheToolFaceOutOfPlanning:
    """I14 / Step 8.4：绑定子闸 off 时工具面不参与规划，绑定只在执行期发生。"""

    def test_binding_off_writes_no_tool_id_through_the_decomposer(self):
        registry = support.builtin_registry()
        specs = [
            SubGoalSpec.model_validate(plan4.step(1, tool_id=None)),
        ]
        work, bindings, errors = plan4.bind(specs, enabled=False, registry=registry)
        assert bindings == []
        assert errors == []
        assert [spec.tool_id for spec in work] == [None]
        assert [spec.kind for spec in work] == ["tool"]

    @pytest.mark.asyncio
    async def test_binding_off_skips_both_planning_gates(
        self, db_session_factory, planning_gates_on, make_goal, stub_planning_llm
    ):
        """绑定开关注入 off（构造参数，供单列验证；settings 子闸已删）：闸门 5/6 不生效，计划内容原样落库。"""
        from app.repositories import goal_repository

        goal = make_goal(description="绑定子闸关闭目标")
        stub_planning_llm(
            sub_goals=[
                {
                    "index": 1,
                    "description": "步骤1",
                    "capability": "create_reminder",
                    "params": {"content": "x", "due_at": "2026-09-20T09:00:00"},
                    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
                }
            ]
        )
        surface = support.resolve_surface()
        engine = plan_engine.PlanningEngine(tool_binding_enabled=False)
        outcome = await engine.plan(
            goal, _plan_context(goal, surface), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        stored = goal_repository.get_plan(outcome.plan.id)
        assert [spec.tool_id for spec in stored.sub_goals] == [None]
        assert len(surface.tool_ids) > 0

    def test_binding_off_keeps_the_decomposer_read_only_for_the_surface(self):
        registry = support.builtin_registry()
        work, bindings, errors = plan4.bind(
            [SubGoalSpec.model_validate(plan4.step(1))], enabled=False, registry=registry
        )
        assert work[0].kind == "tool"
        assert work[0].expected_effects == ()
        assert work[0].binding_reason is None
        assert bindings == [] and errors == []


class TestAssemblyConsumesTheToolSystemUnchanged:
    """§5.2：装配与执行都走既有工具系统（`assemble_plan` → `ToolSelector` → `ToolExecutor`）。"""

    @pytest.mark.asyncio
    async def test_assemble_plan_selects_through_the_existing_selector(
        self, db_session_factory, action_chain_on, monkeypatch
    ):
        from app.models.action import ActionIntent, make_dedupe_key
        from app.services.tool.surface import ToolSelector

        registry = get_tool_registry()
        seen: list[dict] = []
        original = ToolSelector.select_with_reason

        def _spy(self, intent, surface):
            result = original(self, intent, surface)
            seen.append({"action_type": intent.action_type, "reason": result.reason})
            return result

        monkeypatch.setattr(ToolSelector, "select_with_reason", _spy)
        monkeypatch.setattr(
            action_engine, "get_capability_registry", lambda: stub_registry(_memory_capability())
        )

        params = {"fact": "小明喜欢喝咖啡"}
        intent = ActionIntent(
            action_type="remember_fact",
            confidence="confident",
            params=params,
            dedupe_key=make_dedupe_key("remember_fact", params),
        )
        snapshot = action_engine._build_snapshot(USER, _settings())
        plan = assemble_plan(intent, snapshot, action_engine._now(), goal_id=None)
        assert plan is not None
        assert seen and seen[0]["reason"] == "priority_order"
        assert plan.steps[0].capability == "memory"
        assert registry is not None


def _memory_capability() -> StubCapability:
    return StubCapability(name="memory", action="save", required=["fact"])
