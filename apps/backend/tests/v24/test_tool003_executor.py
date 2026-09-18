"""TOOL-003 §6.1~§6.3：五段短路、零外部调用、归一、脱敏（E1~E5、E8~E12）。"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from app.models.action import ActionIntent, ActionStep, CapabilityResult
from app.models.tool import PermissionProfile, ToolBinding, ToolInvocation, ToolSchema
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import ExecutionContext
from app.services.tool.context import ToolContext
from app.services.tool.executor import (
    PERMISSION_CONFIRM_REQUIRED,
    PERMISSION_DENY,
    PERMISSION_LAYER_DISABLED_GRANT_FREE_REASON,
    PERMISSION_LAYER_DISABLED_REASON,
    PERMISSION_LAYER_OFF_REASON,
    PermissionDecision,
    PermissionGate,
    PermissionSnapshot,
    ToolExecutor,
    resolve_step_binding,
)
from app.services.tool.permission import REASON_LEVEL_NO_GRANT_REQUIRED
from app.services.tool.normalizer import REDACTED_VALUE
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.validator import ParamValidator
from tests.v24.tool002_support import definition
from tests.v24.tool003_support import (
    NOW,
    StubCapability,
    build_executor,
    notification_definition,
    param,
    registry_with,
    sensitive_definition,
    stub_registry,
    tool_settings,
    tracker,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "builtin.reminder.create"
NOTIFICATION_ID = "builtin.notification.send"

GRANT_FREE_PERMISSION = PermissionProfile(level="normal", scope=("self",))
"""同形声明的免授权档权限画像（P0-1：总闸 on + 子闸 off 时特权档默认拒绝）。"""


def _intent() -> ActionIntent:
    return ActionIntent(action_type="create_reminder", confidence="confident", params={})


def _invocation(tool_id: str = TOOL_ID, params: dict | None = None) -> ToolInvocation:
    return ToolInvocation(tool_id=tool_id, params=params or {}, intent=_intent())


def _ctx(**overrides) -> ToolContext:
    payload = {"user_id": "u-1", "now": NOW}
    payload.update(overrides)
    return ToolContext(**payload)


def _reminder_capability(behavior=None) -> StubCapability:
    return StubCapability(
        name="reminder", action="create", required=["content", "due_at"], behavior=behavior
    )


def _succeeding_registry_and_capability():
    registry = registry_with(definition())
    capability = _reminder_capability(
        lambda params, ctx: CapabilityResult(
            status="succeeded",
            payload={
                "world_event_id": "evt-1",
                "due_at": "2026-06-02T08:00:00+00:00",
                "failure_kind": None,
            },
            usage={},
        )
    )
    return registry, capability


def _builtin_registry_and_capability(behavior=None):
    """真实内置声明（含语义校验器）+ 打桩能力。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry, _reminder_capability(behavior)


def _budget_definition(*, sensitive: bool = False):
    """超预算 / 脱敏负例声明。

    等级取免授权档：本文件的这些用例主题在**校验段与脱敏段**，而 P0-1 后权限子闸未开时
    特权档（sensitive 及以上）一律默认拒绝，会把用例挡在主题之前。
    """
    return notification_definition(
        input_schema=ToolSchema(
            parameters=[
                param("content", required=True),
                param("recipient", sensitive=sensitive),
            ],
            semantic_validators=("content_within_budget",),
        ),
        permission=GRANT_FREE_PERMISSION,
    )


class RecordingGate:
    def __init__(self, decision: PermissionDecision) -> None:
        self.decision = decision
        self.calls: list[tuple] = []

    def evaluate(self, defn, inv, snapshot):
        self.calls.append((defn.id, inv.tool_id, snapshot))
        return self.decision


class RecordingValidator(ParamValidator):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []

    def validate(self, defn, params, ctx=None):
        self.calls.append((defn.id, dict(params)))
        return super().validate(defn, params, ctx)


# --- E1：编程错误抛错 ---------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_id_mismatch_raises_e1():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    binding = registry.resolve(TOOL_ID)
    with pytest.raises(ValueError):
        await executor.run(binding, _invocation("builtin.reminder.cancel"), _ctx())
    assert capability.calls == []


# --- ① resolve ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_unregistered_binding_is_unavailable():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    orphan = ToolBinding(
        tool_id="builtin.ghost.tool",
        capability="reminder",
        action="create",
        definition=definition(id="builtin.ghost.tool"),
    )
    execution = await executor.run(orphan, _invocation("builtin.ghost.tool"), _ctx())
    assert execution.status == "unavailable"
    assert execution.result["failure_kind"] == "unavailable"
    assert execution.duration_ms == 0
    assert capability.calls == []


@pytest.mark.asyncio
async def test_disabled_tool_is_unavailable():
    registry = registry_with(definition(status="disabled"))
    capability = _reminder_capability()
    executor = build_executor(registry, capability)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "unavailable"
    assert capability.calls == []


@pytest.mark.asyncio
async def test_tripped_tool_is_unavailable_after_resolve_e2():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    binding = registry.resolve(TOOL_ID)
    assert binding is not None
    for _ in range(3):
        executor.health.record_outcome(TOOL_ID, ok=False, failure_kind="transient")
    execution = await executor.run(binding, _invocation(), _ctx())
    assert execution.status == "unavailable"
    assert capability.calls == []


# --- ② permission ------------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_sub_layer_off_keeps_grant_free_tier_allow():
    """P0-1：总闸 on + 权限子闸 off 时，免授权档（normal）仍放行——三段的中间段。"""
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.permission == {
        "level": "normal",
        "decision": "allow",
        "reason": PERMISSION_LAYER_DISABLED_GRANT_FREE_REASON,
        "confirmed": False,
    }
    assert execution.status == "succeeded"
    assert capability.calls == [{}]


@pytest.mark.asyncio
async def test_permission_sub_layer_off_denies_sensitive_tier():
    """P0-1：总闸 on + 权限子闸 off 时，特权档（sensitive）默认拒绝——fail-closed。"""
    registry = registry_with(sensitive_definition())
    capability = StubCapability()
    executor = build_executor(registry, capability)
    execution = await executor.run(
        registry.resolve(NOTIFICATION_ID),
        _invocation(NOTIFICATION_ID, {"content": "你好", "recipient": "u-9"}),
        _ctx(),
    )
    assert execution.status == "denied"
    assert execution.permission == {
        "level": "sensitive",
        "decision": "deny",
        "reason": PERMISSION_LAYER_DISABLED_REASON,
        "confirmed": False,
    }
    assert capability.calls == []


@pytest.mark.asyncio
async def test_master_gate_off_is_placeholder_allow_for_every_tier():
    """总闸 off：权限段不参与（TOOL-003 交付态），特权档同样放行——三段的首段。"""
    registry = registry_with(sensitive_definition())
    capability = StubCapability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(NOTIFICATION_ID),
        _invocation(NOTIFICATION_ID, {"content": "你好", "recipient": "u-9"}),
        _ctx(),
    )
    assert execution.permission["decision"] == "allow"
    assert execution.permission["reason"] == PERMISSION_LAYER_OFF_REASON
    assert execution.status == "succeeded"
    assert capability.calls != []


@pytest.mark.asyncio
async def test_permission_on_runs_real_gate_level_no_grant_required():
    """TOOL-005 同步：权限闸 on 时占位 allow 由真实七步判定取代（normal 免授权）。"""
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.permission["decision"] == "allow"
    assert execution.permission["reason"] == REASON_LEVEL_NO_GRANT_REQUIRED
    assert execution.status == "succeeded"


@pytest.mark.asyncio
async def test_permission_deny_short_circuits_with_zero_external_calls():
    registry, capability = _succeeding_registry_and_capability()
    gate = RecordingGate(PermissionDecision(PERMISSION_DENY, "normal", "scope_denied"))
    executor = build_executor(registry, capability, permission_gate=gate)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "denied"
    assert execution.result["failure_kind"] == "denied"
    assert execution.permission["reason"] == "scope_denied"
    assert execution.validation is None
    assert execution.duration_ms == 0
    assert capability.calls == []
    assert len(gate.calls) == 1


@pytest.mark.asyncio
async def test_permission_confirm_required_short_circuits():
    registry, capability = _succeeding_registry_and_capability()
    gate = RecordingGate(
        PermissionDecision(PERMISSION_CONFIRM_REQUIRED, "sensitive", "first_time", "要发吗？")
    )
    executor = build_executor(registry, capability, permission_gate=gate)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "pending_confirmation"
    assert execution.result["failure_kind"] is None
    assert capability.calls == []


@pytest.mark.asyncio
async def test_unknown_permission_decision_fails_closed():
    registry, capability = _succeeding_registry_and_capability()
    gate = RecordingGate(PermissionDecision("maybe", "normal", "made_up"))
    executor = build_executor(registry, capability, permission_gate=gate)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "denied"
    assert execution.permission["reason"] == "unknown_decision:maybe"
    assert capability.calls == []


def test_permission_interfaces_are_frozen_shapes():
    """TOOL-005 同步：快照 / 裁决形状按 TOOL-005 §2.2 演进（新增快照字段与 confirm_kind）。"""
    assert set(PermissionSnapshot().__dict__) == {
        "user_id",
        "now",
        "grants",
        "pending",
        "channel_bound",
        "settings",
        "namespace_floors",
    }
    assert set(PermissionDecision("allow", "normal", "r").__dict__) == {
        "decision",
        "level",
        "reason",
        "confirm_prompt",
        "scope_required",
        "confirm_kind",
    }
    gate = PermissionGate(tool_settings())
    decision = gate.evaluate(definition(), _invocation(), PermissionSnapshot(user_id="u"))
    assert decision.decision == "allow"
    assert decision.level == "normal"
    assert decision.scope_required == ("world",)
    assert decision.confirm_prompt is None
    assert decision.confirm_kind is None


# --- ③ validate --------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_off_skips_validator():
    registry, capability = _succeeding_registry_and_capability()
    validator = RecordingValidator()
    executor = build_executor(registry, capability, validator=validator)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert validator.calls == []
    assert execution.validation is None
    assert execution.status == "succeeded"


@pytest.mark.asyncio
async def test_validation_on_invalid_params_short_circuits_e3():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(TOOL_ID),
        _invocation(params={"content": "买牛奶", "due_at": "2026-06-02T08:00:00", "ghost": 1}),
        _ctx(),
    )
    assert execution.status == "invalid"
    assert execution.result["failure_kind"] == "invalid"
    assert execution.validation["passed"] is False
    assert [issue["code"] for issue in execution.validation["structural"]] == ["unknown_param"]
    assert capability.calls == []


@pytest.mark.asyncio
async def test_validation_on_past_due_at_is_invalid_e5():
    registry, capability = _builtin_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(TOOL_ID),
        _invocation(params={"content": "买牛奶", "due_at": "2020-06-02T08:00:00"}),
        _ctx(),
    )
    assert execution.status == "invalid"
    assert [issue["code"] for issue in execution.validation["semantic"]] == ["not_future"]
    assert capability.calls == []


@pytest.mark.asyncio
async def test_validation_on_oversized_content_blocks_capability_e11():
    registry = registry_with(_budget_definition())
    capability = StubCapability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(NOTIFICATION_ID),
        _invocation(NOTIFICATION_ID, {"content": "x" * 10_000}),
        _ctx(),
    )
    assert execution.status == "invalid"
    assert [issue["code"] for issue in execution.validation["semantic"]] == ["content_over_budget"]
    assert capability.calls == []


@pytest.mark.asyncio
async def test_validation_on_pass_normalizes_params_before_invoke():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(TOOL_ID),
        _invocation(params={"content": "  买   牛奶 ", "due_at": "2026-06-02T08:00:00Z"}),
        _ctx(),
    )
    assert execution.status == "succeeded"
    assert capability.calls == [{"content": "买 牛奶", "due_at": "2026-06-02T08:00:00+00:00"}]
    assert execution.params == capability.calls[0]
    assert execution.validation is None


# --- ④ invoke / ⑤ normalize --------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_reuses_capability_executor_instance():
    registry, capability = _succeeding_registry_and_capability()
    capability_executor = CapabilityExecutor(stub_registry(capability), 2.0)
    executor = ToolExecutor(
        registry, capability_executor, settings=tool_settings(), health=tracker(registry)
    )
    assert executor.capability_executor is capability_executor
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "succeeded"


@pytest.mark.asyncio
async def test_success_persists_v9_shape_when_observation_off():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    execution = await executor.run(
        registry.resolve(TOOL_ID),
        _invocation(params={"content": "买牛奶", "due_at": "2026-06-02T08:00:00"}),
        _ctx(),
    )
    assert execution.status == "succeeded"
    assert set(execution.result) == {"status", "payload", "usage", "error"}
    assert execution.result["payload"]["world_event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_success_persists_tool_result_when_observation_on():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.result["observations"] == {
        "world.event_id": "evt-1",
        "time.due_at": "2026-06-02T08:00:00+00:00",
    }
    assert [(effect["kind"], effect["ref"]) for effect in execution.result["effects"]] == [
        ("world", "evt-1")
    ]
    assert execution.result["payload"]["world_event_id"] == "evt-1"
    assert execution.result["usage"]["external_calls"] == 0
    assert execution.result["usage"]["tool_id"] == TOOL_ID


@pytest.mark.asyncio
async def test_failure_records_health_and_failure_kind():
    registry = registry_with(definition())
    capability = _reminder_capability(
        lambda params, ctx: CapabilityResult(
            status="failed", payload={"failure_kind": "permanent"}, error="世界事件创建失败"
        )
    )
    executor = build_executor(registry, capability)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "failed"
    assert execution.result["payload"]["failure_kind"] == "permanent"
    health = executor.health.snapshot(TOOL_ID)[TOOL_ID]
    assert health.consecutive_failures == 1
    assert health.last_failure_at is not None


@pytest.mark.asyncio
async def test_timeout_counts_one_failure_and_keeps_kind_e9():
    registry = registry_with(definition())

    async def _slow(params, ctx):
        await asyncio.sleep(1)
        return CapabilityResult(status="succeeded")

    capability = _reminder_capability(_slow)
    executor = build_executor(registry, capability, timeout_seconds=0.05)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "timeout"
    assert execution.result["payload"]["failure_kind"] == "timeout"
    assert executor.health.snapshot(TOOL_ID)[TOOL_ID].consecutive_failures == 1


@pytest.mark.asyncio
async def test_capability_unavailable_passes_through_e8():
    registry = registry_with(definition())
    capability = _reminder_capability(
        lambda params, ctx: CapabilityResult(
            status="unavailable", payload={"failure_kind": "unavailable"}, error="世界未启用"
        )
    )
    executor = build_executor(registry, capability)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "unavailable"
    assert execution.result["payload"]["failure_kind"] == "unavailable"
    assert capability.calls != []


@pytest.mark.asyncio
async def test_short_circuit_paths_do_not_record_health():
    registry, capability = _succeeding_registry_and_capability()
    gate = RecordingGate(PermissionDecision(PERMISSION_DENY, "normal", "denied"))
    executor = build_executor(registry, capability, permission_gate=gate)
    await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert executor.health.snapshot(TOOL_ID)[TOOL_ID].consecutive_failures == 0


@pytest.mark.asyncio
async def test_concurrent_runs_accumulate_health_in_call_order_e14():
    registry = registry_with(definition())
    capability = _reminder_capability(
        lambda params, ctx: CapabilityResult(
            status="failed", payload={"failure_kind": "transient"}, error="瞬时失败"
        )
    )
    executor = build_executor(registry, capability)
    binding = registry.resolve(TOOL_ID)
    await asyncio.gather(
        executor.run(binding, _invocation(), _ctx()),
        executor.run(binding, _invocation(), _ctx()),
    )
    assert len(capability.calls) == 2
    assert executor.health.snapshot(TOOL_ID)[TOOL_ID].consecutive_failures == 2


@pytest.mark.asyncio
async def test_capability_exception_is_normalized_to_failed_transient():
    registry = registry_with(definition())

    async def _boom(params, ctx):
        raise RuntimeError("boom!")

    capability = _reminder_capability(_boom)
    executor = build_executor(registry, capability)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.status == "failed"
    assert execution.result["payload"]["failure_kind"] == "transient"
    assert execution.result["error"].startswith("RuntimeError")


@pytest.mark.asyncio
async def test_execution_metadata_fields():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.index == 0
    assert execution.tool_id == TOOL_ID
    assert execution.capability == "reminder"
    assert execution.action == "create"
    assert execution.started_at == NOW
    assert execution.duration_ms is not None and execution.duration_ms >= 0


@pytest.mark.asyncio
async def test_index_is_passed_through():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx(), index=3)
    assert execution.index == 3
    assert capability.calls != []


@pytest.mark.asyncio
async def test_invocation_params_are_not_mutated():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    params = {"content": "  买  牛奶 ", "due_at": "2026-06-02T08:00:00"}
    invocation = _invocation(params=params)
    await executor.run(registry.resolve(TOOL_ID), invocation, _ctx())
    assert params == {"content": "  买  牛奶 ", "due_at": "2026-06-02T08:00:00"}
    assert invocation.params == params


# --- 脱敏 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sensitive_params_are_redacted_in_execution_params():
    registry = registry_with(sensitive_definition(permission=GRANT_FREE_PERMISSION))
    capability = StubCapability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(NOTIFICATION_ID),
        _invocation(NOTIFICATION_ID, {"content": "你好", "recipient": "u-9"}),
        _ctx(),
    )
    assert execution.params == {"content": "你好", "recipient": REDACTED_VALUE}
    assert execution.result["redacted"] == ["recipient"]
    assert capability.calls == [{"content": "你好", "recipient": "u-9"}]


@pytest.mark.asyncio
async def test_empty_sensitive_param_is_not_redacted_e12():
    registry = registry_with(sensitive_definition(permission=GRANT_FREE_PERMISSION))
    capability = StubCapability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(NOTIFICATION_ID),
        _invocation(NOTIFICATION_ID, {"content": "你好", "recipient": ""}),
        _ctx(),
    )
    assert execution.params == {"content": "你好", "recipient": ""}
    assert execution.result["redacted"] == []


@pytest.mark.asyncio
async def test_sensitive_param_is_redacted_on_short_circuit_paths():
    registry = registry_with(_budget_definition(sensitive=True))
    capability = StubCapability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(NOTIFICATION_ID),
        _invocation(NOTIFICATION_ID, {"content": "x" * 10_000, "recipient": "u-9"}),
        _ctx(),
    )
    assert execution.status == "invalid"
    assert execution.params == {"content": "x" * 10_000, "recipient": REDACTED_VALUE}


# --- 五段顺序与复用纪律 ------------------------------------------------------


@pytest.mark.asyncio
async def test_five_stages_run_in_fixed_order():
    order: list[str] = []
    registry = registry_with(definition())
    capability = _reminder_capability(
        lambda params, ctx: (
            order.append("invoke"),
            CapabilityResult(status="succeeded", payload={}, usage={}),
        )[1]
    )
    validator = RecordingValidator()
    health = tracker(registry)
    original_is_tripped = health.is_tripped

    def _is_tripped(tool_id, now=None):
        order.append("resolve")
        return original_is_tripped(tool_id, now)

    health.is_tripped = _is_tripped
    gate = RecordingGate(PermissionDecision("allow", "normal", PERMISSION_LAYER_OFF_REASON))
    original_gate_evaluate = gate.evaluate

    def _evaluate(defn, inv, snapshot):
        order.append("permission")
        return original_gate_evaluate(defn, inv, snapshot)

    gate.evaluate = _evaluate
    original_validate = validator.validate

    def _validate(defn, params, ctx=None):
        order.append("validate")
        return original_validate(defn, params, ctx)

    validator.validate = _validate
    executor = build_executor(
        registry,
        capability,
        settings=tool_settings(),
        validator=validator,
        health=health,
        permission_gate=gate,
    )
    execution = await executor.run(
        registry.resolve(TOOL_ID),
        _invocation(params={"content": "买牛奶", "due_at": "2026-06-02T08:00:00"}),
        _ctx(),
    )
    assert execution.status == "succeeded"
    assert order == ["resolve", "permission", "validate", "invoke"]


@pytest.mark.asyncio
async def test_short_circuit_reaches_no_later_stage():
    order: list[str] = []
    registry = registry_with(definition())
    capability = _reminder_capability(lambda params, ctx: order.append("invoke"))
    validator = RecordingValidator()
    gate = RecordingGate(PermissionDecision(PERMISSION_DENY, "normal", "denied"))
    executor = build_executor(registry, capability, validator=validator, permission_gate=gate)
    await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert validator.calls == []
    assert order == []


@pytest.mark.asyncio
async def test_precondition_failure_performs_no_db_write(monkeypatch):
    import app.repositories.action_repository as action_repository

    writes: list[str] = []
    monkeypatch.setattr(
        action_repository, "save_record", lambda record: writes.append(record.id)
    )
    registry, capability = _succeeding_registry_and_capability()
    gate = RecordingGate(PermissionDecision(PERMISSION_DENY, "normal", "denied"))
    executor = build_executor(registry, capability, permission_gate=gate)
    await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert writes == []
    assert capability.calls == []


def test_executor_does_not_reimplement_timeout_wrapper():
    source = (BACKEND_ROOT / "app/services/tool/executor.py").read_text(encoding="utf-8")
    assert "wait_for" not in source
    assert "asyncio" not in source
    assert "app.repositories" not in source


@pytest.mark.asyncio
async def test_timeout_and_exception_results_match_v9_capability_executor():
    async def _boom(params, ctx):
        raise RuntimeError("boom!")

    async def _slow(params, ctx):
        await asyncio.sleep(1)
        return CapabilityResult(status="succeeded")

    for behavior, timeout in ((_boom, 2.0), (_slow, 0.05)):
        registry = registry_with(definition())
        capability = _reminder_capability(behavior)
        v9_result = await CapabilityExecutor(stub_registry(capability), timeout).run(
            ActionStep(index=0, capability="reminder", action="create", params={}), _ctx()
        )
        executor = build_executor(registry, capability, timeout_seconds=timeout)
        execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
        v9_payload = v9_result.model_dump(mode="json")
        assert execution.status == v9_result.status
        assert {
            key: value for key, value in execution.result.items() if key != "usage"
        } == {key: value for key, value in v9_payload.items() if key != "usage"}
        assert set(execution.result["usage"]) == set(v9_payload["usage"])
        assert execution.duration_ms == round(execution.result["usage"]["duration_ms"])


@pytest.mark.asyncio
async def test_observation_on_result_is_superset_of_v9_payload():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(registry.resolve(TOOL_ID), _invocation(), _ctx())
    assert execution.result["status"] == "succeeded"
    assert execution.result["error"] is None
    assert execution.result["usage"]["duration_ms"] >= 0
    assert execution.result["raw_error"] is None
    assert execution.result["payload"]["failure_kind"] is None
    assert execution.result["failure_kind"] is None


# --- 解析与上下文 ------------------------------------------------------------


def test_resolve_step_binding_prefers_enabled_tool():
    registry = ToolRegistry()
    register_builtin_tools(registry)
    enabled = resolve_step_binding(
        registry, ActionStep(index=0, capability="notification", action="send", params={})
    )
    assert enabled.tool_id == NOTIFICATION_ID
    reminder = resolve_step_binding(
        registry, ActionStep(index=0, capability="reminder", action="create", params={})
    )
    assert reminder.tool_id == TOOL_ID
    assert (
        resolve_step_binding(
            registry, ActionStep(index=0, capability="nope", action="x", params={})
        )
        is None
    )


@pytest.mark.asyncio
async def test_resolve_step_binding_returns_binding_for_tripped_tool():
    registry = registry_with(definition())
    health = tracker(registry)
    for _ in range(3):
        health.record_outcome(TOOL_ID, ok=False, failure_kind="transient")
    binding = resolve_step_binding(
        registry, ActionStep(index=0, capability="reminder", action="create", params={})
    )
    assert binding.tool_id == TOOL_ID
    executor = build_executor(registry, _reminder_capability(), health=health)
    execution = await executor.run(binding, _invocation(), _ctx())
    assert execution.status == "unavailable"


@pytest.mark.asyncio
async def test_environment_context_is_accepted_as_tool_context():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(
        registry, capability, settings=tool_settings()
    )
    execution = await executor.run(
        registry.resolve(TOOL_ID),
        _invocation(params={"content": "x", "due_at": "2026-06-02T08:00:00"}),
        ExecutionContext(user_id="u-1", now=NOW),
    )
    assert execution.status == "succeeded"
    assert execution.started_at == NOW


@pytest.mark.asyncio
async def test_started_at_falls_back_to_wall_clock_without_ctx_now():
    registry, capability = _succeeding_registry_and_capability()
    executor = build_executor(registry, capability)
    execution = await executor.run(
        registry.resolve(TOOL_ID), _invocation(), ToolContext(user_id="u")
    )
    assert isinstance(execution.started_at, datetime)


def test_tool_context_from_execution_context_keeps_world_fields_empty():
    tool_ctx = ToolContext.from_execution_context(
        ExecutionContext(user_id="u-1", record_id="r-1", now=NOW)
    )
    assert tool_ctx.user_id == "u-1"
    assert tool_ctx.character_id == "asuna"
    assert tool_ctx.record_id == "r-1"
    assert tool_ctx.now == NOW
    assert tool_ctx.run_kind == "foreground_chat"
    assert tool_ctx.run_id is None
    assert tool_ctx.source == "conversation"
    assert tool_ctx.world == {}
    assert tool_ctx.inventory == []
    assert tool_ctx.situations == []
    assert tool_ctx.scene == {}
    assert tool_ctx.relationship == {}
    assert tool_ctx.authorized_recipients == []
    assert tool_ctx.world_locations() is None
    assert tool_ctx.relationship_stage() is None


def test_tool_context_is_read_only_snapshot():
    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.user_id = "other"


def test_tool_context_fields_are_a_superset_of_execution_context():
    from dataclasses import fields as dataclass_fields

    execution_fields = {field.name for field in dataclass_fields(ExecutionContext)}
    tool_fields = {field.name for field in dataclass_fields(ToolContext)}
    assert execution_fields <= tool_fields
