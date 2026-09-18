"""TOOL-003 §6.2：action_engine 接线、steps[] 形状、integrate_result 兼容与冻结面。"""

import ast
import hashlib
from pathlib import Path

import pytest

from app.application import action_engine
from app.models.action import (
    ActionIntent,
    ActionPlan,
    ActionRecord,
    ActionResult,
    ActionStep,
    CapabilityResult,
)
from app.models.tool import ToolExecution
from app.repositories import action_repository
from app.services.action.registry import ExecutionContext, get_capability_registry
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from tests.v24.tool002_support import definition
from tests.v24.tool003_support import (
    NOW,
    StubCapability,
    registry_with,
    sensitive_definition,
    stub_registry,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "builtin.reminder.create"
V9_STEP_KEYS = {"index", "capability", "action", "params", "status", "result"}
TOOL_STEP_KEYS = V9_STEP_KEYS | {"tool_id", "permission", "validation", "duration_ms"}


def _intent(params: dict | None = None) -> ActionIntent:
    return ActionIntent(
        action_type="create_reminder", confidence="confident", params=params or {}
    )


def _plan(params: dict) -> ActionPlan:
    return ActionPlan(
        intent=_intent(params),
        steps=[ActionStep(index=0, capability="reminder", action="create", params=params)],
    )


def _record(intent: ActionIntent) -> ActionRecord:
    return action_engine.new_record(intent, "tool-user", session_id=None)


def _reminder_capability(behavior=None) -> StubCapability:
    return StubCapability(
        name="reminder", action="create", required=["content", "due_at"], behavior=behavior
    )


def _success_behavior(params, ctx):
    return CapabilityResult(
        status="succeeded",
        payload={
            "world_event_id": "evt-1",
            "due_at": "2026-06-02T08:00:00+00:00",
            "failure_kind": None,
        },
        usage={},
    )


def _wire(monkeypatch, capability, tool_registry) -> None:
    monkeypatch.setattr(action_engine, "get_capability_registry", lambda: stub_registry(capability))
    monkeypatch.setattr(action_engine, "get_tool_registry", lambda: tool_registry)


def _ctx(settings) -> ExecutionContext:
    return ExecutionContext(
        user_id="tool-user", character_id="asuna", record_id="r-1", now=NOW, settings=settings
    )


PARAMS = {"content": "买牛奶", "due_at": "2026-06-02T08:00:00"}


# --- Flag off 原路径逐字节一致 ------------------------------------------------


@pytest.mark.asyncio
async def test_master_flag_off_keeps_v9_step_shape(monkeypatch, override_settings, db_session_factory):
    override_settings(action_enabled=True, tool_system_enabled=False)
    capability = _reminder_capability(_success_behavior)
    _wire(monkeypatch, capability, registry_with(definition()))
    intent = _intent(PARAMS)
    record = _record(intent)
    result = await action_engine.execute_plan(
        record, _plan(PARAMS), _ctx(action_engine.get_settings())
    )
    assert result.status == "succeeded"
    assert record.status == "succeeded"
    step = record.steps[0]
    assert set(step) == V9_STEP_KEYS
    assert step["status"] == "succeeded"
    assert set(step["result"]) == {"status", "payload", "usage", "error"}
    assert step["result"]["payload"]["world_event_id"] == "evt-1"
    assert step["result"]["usage"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_master_flag_on_adds_tool_fields_incrementally(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(action_enabled=True, tool_system_enabled=True)
    capability = _reminder_capability(_success_behavior)
    _wire(monkeypatch, capability, registry_with(definition()))
    intent = _intent(PARAMS)
    record = _record(intent)
    result = await action_engine.execute_plan(
        record, _plan(PARAMS), _ctx(action_engine.get_settings())
    )
    assert result.status == "succeeded"
    step = record.steps[0]
    assert set(step) == TOOL_STEP_KEYS
    assert step["tool_id"] == TOOL_ID
    assert step["capability"] == "reminder"
    assert step["action"] == "create"
    assert step["params"] == PARAMS
    assert step["permission"] == {
        "level": "normal",
        "decision": "allow",
        "reason": "permission_layer_disabled_grant_free",
        "confirmed": False,
    }
    assert step["validation"] is None
    assert isinstance(step["duration_ms"], int)
    assert set(step["result"]) == {"status", "payload", "usage", "error"}
    assert capability.calls == [PARAMS]


@pytest.mark.asyncio
async def test_observation_flag_on_writes_tool_result_with_old_payload_key(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(
        action_enabled=True,
        tool_system_enabled=True,
        tool_observation_enabled=True,
    )
    capability = _reminder_capability(_success_behavior)
    _wire(monkeypatch, capability, registry_with(definition()))
    intent = _intent(PARAMS)
    record = _record(intent)
    await action_engine.execute_plan(record, _plan(PARAMS), _ctx(action_engine.get_settings()))
    result = record.steps[0]["result"]
    assert result["observations"] == {
        "world.event_id": "evt-1",
        "time.due_at": "2026-06-02T08:00:00+00:00",
    }
    assert [(effect["kind"], effect["ref"]) for effect in result["effects"]] == [("world", "evt-1")]
    assert result["payload"]["world_event_id"] == "evt-1"
    assert result["usage"]["tool_id"] == TOOL_ID


@pytest.mark.asyncio
async def test_steps_round_trip_through_action_records(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(
        action_enabled=True,
        tool_system_enabled=True,
        tool_observation_enabled=True,
        tool_schema_validation_enabled=True,
    )
    capability = _reminder_capability(_success_behavior)
    _wire(monkeypatch, capability, registry_with(definition()))
    intent = _intent(PARAMS)
    record = _record(intent)
    await action_engine.execute_plan(record, _plan(PARAMS), _ctx(action_engine.get_settings()))
    persisted = action_repository.get_record(record.id)
    assert persisted.steps == record.steps
    assert set(persisted.steps[0]) == TOOL_STEP_KEYS


# --- 状态映射表 --------------------------------------------------------------


def _stub_tool_run(status: str, failure_kind: str | None):
    async def _run(self, binding, invocation, ctx, *, index=0, permission_snapshot=None):
        return ToolExecution(
            index=index,
            tool_id=binding.tool_id,
            capability=binding.capability,
            action=binding.action,
            status=status,
            params=dict(invocation.params),
            permission={"level": "normal", "decision": "allow", "reason": "stub", "confirmed": False},
            validation=None,
            result={"status": status, "failure_kind": failure_kind, "error": status},
            started_at=NOW,
            duration_ms=0,
        )

    return _run


@pytest.mark.parametrize(
    "status,expected_status,expected_reason,expected_kind",
    [
        ("unavailable", "cancelled", "capability_unavailable", "unavailable"),
        ("denied", "cancelled", "permission_denied", "permanent"),
        ("invalid", "cancelled", "invalid_params", "permanent"),
        ("pending_confirmation", "planned", "pending_confirmation", "permanent"),
    ],
)
@pytest.mark.asyncio
async def test_short_circuit_status_mapping(
    monkeypatch,
    override_settings,
    db_session_factory,
    status,
    expected_status,
    expected_reason,
    expected_kind,
):
    override_settings(action_enabled=True, tool_system_enabled=True)
    capability = _reminder_capability(_success_behavior)
    _wire(monkeypatch, capability, registry_with(definition()))
    monkeypatch.setattr(
        action_engine.ToolExecutor, "run", _stub_tool_run(status, status if status != "pending_confirmation" else None)
    )
    intent = _intent(PARAMS)
    record = _record(intent)
    result = await action_engine.execute_plan(
        record, _plan(PARAMS), _ctx(action_engine.get_settings())
    )
    assert record.status == expected_status
    assert record.gate_reason == expected_reason
    assert record.attempt == 1
    assert record.next_retry_at is None
    assert result.status == "failed"
    assert result.failure_kind == expected_kind
    assert record.steps[0]["status"] == (
        "failed" if status in ("failed", "timeout") else "skipped"
    )


@pytest.mark.asyncio
async def test_unavailable_capability_result_maps_to_cancelled_e8(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(action_enabled=True, tool_system_enabled=True)
    capability = _reminder_capability(
        lambda params, ctx: CapabilityResult(
            status="unavailable", payload={"failure_kind": "unavailable"}, error="世界未启用"
        )
    )
    _wire(monkeypatch, capability, registry_with(definition()))
    intent = _intent(PARAMS)
    record = _record(intent)
    result = await action_engine.execute_plan(
        record, _plan(PARAMS), _ctx(action_engine.get_settings())
    )
    assert record.status == "cancelled"
    assert record.gate_reason == "capability_unavailable"
    assert record.attempt == 1
    assert result.failure_kind == "unavailable"


@pytest.mark.asyncio
async def test_timeout_keeps_v9_retry_semantics(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(
        action_enabled=True,
        tool_system_enabled=True,
        action_retry_max_attempts=3,
    )
    capability = _reminder_capability(
        lambda params, ctx: CapabilityResult(
            status="timeout", payload={"failure_kind": "timeout"}, error="能力执行超时"
        )
    )
    _wire(monkeypatch, capability, registry_with(definition()))
    intent = _intent(PARAMS)
    record = _record(intent)
    result = await action_engine.execute_plan(
        record, _plan(PARAMS), _ctx(action_engine.get_settings())
    )
    assert record.status == "executing"
    assert record.attempt == 2
    assert record.next_retry_at is not None
    assert result.failure_kind == "timeout"
    assert record.steps[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_timeout_exhausts_attempts_to_failed(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(
        action_enabled=True,
        tool_system_enabled=True,
        action_retry_max_attempts=1,
    )
    capability = _reminder_capability(
        lambda params, ctx: CapabilityResult(
            status="timeout", payload={"failure_kind": "timeout"}, error="能力执行超时"
        )
    )
    _wire(monkeypatch, capability, registry_with(definition()))
    intent = _intent(PARAMS)
    record = _record(intent)
    await action_engine.execute_plan(record, _plan(PARAMS), _ctx(action_engine.get_settings()))
    assert record.status == "failed"
    assert record.attempt == 1
    assert record.next_retry_at is None
    assert record.steps[0]["status"] == "failed"
    assert record.steps[0]["result"]["payload"]["failure_kind"] == "timeout"


@pytest.mark.asyncio
async def test_unresolvable_step_binding_marks_tool_unavailable(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(action_enabled=True, tool_system_enabled=True)
    capability = _reminder_capability(_success_behavior)
    _wire(monkeypatch, capability, ToolRegistry())
    intent = _intent(PARAMS)
    record = _record(intent)
    await action_engine.execute_plan(record, _plan(PARAMS), _ctx(action_engine.get_settings()))
    assert record.status == "cancelled"
    assert record.gate_reason == "capability_unavailable"
    assert record.steps[0]["tool_id"] is None
    assert record.steps[0]["result"]["status"] == "unavailable"
    assert capability.calls == []


@pytest.mark.asyncio
async def test_sensitive_params_are_redacted_in_persisted_steps(
    monkeypatch, override_settings, db_session_factory
):
    override_settings(action_enabled=True, tool_system_enabled=True)
    capability = StubCapability(name="notification", action="send")
    _wire(monkeypatch, capability, registry_with(sensitive_definition()))
    intent = ActionIntent(
        action_type="send_notification",
        confidence="confident",
        params={"content": "你好", "recipient": "u-9"},
    )
    record = _record(intent)
    plan = ActionPlan(
        intent=intent,
        steps=[
            ActionStep(
                index=0,
                capability="notification",
                action="send",
                params={"content": "你好", "recipient": "u-9"},
            )
        ],
    )
    await action_engine.execute_plan(record, plan, _ctx(action_engine.get_settings()))
    assert record.steps[0]["params"]["recipient"] == "***"
    assert record.steps[0]["params"]["content"] == "你好"


# --- integrate_result 兼容 ---------------------------------------------------


def _succeeded_record(steps: list[dict], action_type: str = "create_reminder") -> ActionRecord:
    intent = ActionIntent(action_type=action_type, confidence="confident", params=PARAMS)
    record = _record(intent)
    record.status = "succeeded"
    record.steps = steps
    return record


def test_integrate_result_prefers_new_effects_key(monkeypatch):
    record = _succeeded_record(
        [
            {
                "index": 0,
                "capability": "reminder",
                "action": "create",
                "params": PARAMS,
                "status": "succeeded",
                "result": {
                    "status": "succeeded",
                    "effects": [{"kind": "world", "ref": "evt-new", "detail": "", "reversible": True}],
                    "observations": {"world.event_id": "evt-new"},
                    "payload": {"world_event_id": "evt-old"},
                },
            }
        ]
    )
    action_engine.integrate_result(record, ActionResult(status="succeeded", effects=[]))
    refs = [effect["ref"] for effect in record.result["effects"]]
    assert refs == ["evt-new"]


def test_integrate_result_falls_back_to_old_payload_key(monkeypatch):
    record = _succeeded_record(
        [
            {
                "index": 0,
                "capability": "reminder",
                "action": "create",
                "params": PARAMS,
                "status": "succeeded",
                "result": {"status": "succeeded", "payload": {"world_event_id": "evt-old"}},
            }
        ]
    )
    action_engine.integrate_result(record, ActionResult(status="succeeded", effects=[]))
    assert [effect["kind"] for effect in record.result["effects"]] == ["world"]
    assert record.result["effects"][0]["ref"] == "evt-old"


def test_integrate_result_memory_channel_new_then_old():
    new_key = _succeeded_record(
        [
            {
                "index": 0,
                "status": "succeeded",
                "result": {
                    "effects": [{"kind": "memory", "ref": "mem-new", "detail": "已记住"}],
                    "payload": {"memory_id": "mem-old"},
                },
            }
        ],
        action_type="remember_fact",
    )
    old_key = _succeeded_record(
        [
            {
                "index": 0,
                "status": "succeeded",
                "result": {"payload": {"memory_id": "mem-old"}},
            }
        ],
        action_type="remember_fact",
    )
    action_engine.integrate_result(new_key, ActionResult(status="succeeded", effects=[]))
    action_engine.integrate_result(old_key, ActionResult(status="succeeded", effects=[]))
    assert [effect["ref"] for effect in new_key.result["effects"]] == ["mem-new"]
    assert [effect["ref"] for effect in old_key.result["effects"]] == ["mem-old"]


def test_integrate_result_ignores_malformed_effects():
    record = _succeeded_record(
        [
            {
                "index": 0,
                "status": "succeeded",
                "result": {
                    "effects": "not-a-list",
                    "payload": {"world_event_id": "evt-old"},
                },
            }
        ]
    )
    action_engine.integrate_result(record, ActionResult(status="succeeded", effects=[]))
    assert record.result["effects"][0]["ref"] == "evt-old"


def test_integrate_result_outbox_reads_deferred_op_from_payload(monkeypatch):
    captured: dict = {}

    def _capture(record, payload, idempotency_key):
        captured.update(payload)
        captured["idempotency_key"] = idempotency_key

    monkeypatch.setattr(action_repository, "save_record_with_outbox", _capture)
    record = _succeeded_record(
        [
            {
                "index": 0,
                "status": "succeeded",
                "result": {
                    "observations": {},
                    "payload": {
                        "deferred_world_op": {"op": "create_event", "args": ["u1"]},
                        "failure_kind": None,
                    },
                },
            }
        ]
    )
    record.status = "succeeded"
    action_engine._integrate_via_outbox(record)
    assert captured["world_ops"] == [{"op": "create_event", "args": ["u1"]}]
    assert captured["idempotency_key"] == record.id


def test_effect_ref_helper_reads_only_matching_kind():
    step_result = {"effects": [{"kind": "memory", "ref": "mem-1"}, {"kind": "world", "ref": "evt-9"}]}
    assert action_engine._effect_ref(step_result, "world") == "evt-9"
    assert action_engine._effect_ref(step_result, "memory") == "mem-1"
    assert action_engine._effect_ref(step_result, "note") is None
    assert action_engine._effect_ref({"effects": [{"kind": "world"}]}, "world") is None
    assert action_engine._effect_ref({}, "world") is None


# --- 冻结面与零迁移 ----------------------------------------------------------


def _segment_hash(segment: str) -> str:
    """行尾归一（LF）后的段哈希：CRLF 检出不应造成假失败（P2-4）。"""
    return hashlib.sha256(segment.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _class_source_hash(relative_path: str, class_name: str) -> str:
    source = (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return _segment_hash(ast.get_source_segment(source, node))
    raise AssertionError(f"未找到类定义: {relative_path}::{class_name}")


def _function_source_hash(relative_path: str, function_name: str) -> str:
    source = (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return _segment_hash(ast.get_source_segment(source, node))
    raise AssertionError(f"未找到函数定义: {relative_path}::{function_name}")


def test_action_state_machine_and_record_are_unchanged():
    assert _function_source_hash("app/models/action.py", "transition_action") == (
        "55a94cebad543ddf85aa5a79e2bc614db0ef3bbfaef08d3b5d8bf473437ff401"
    )


def test_capability_executor_is_reused_not_modified():
    assert _class_source_hash("app/services/action/executor.py", "CapabilityExecutor") == (
        "dfeafbf6627ecaff056667f762b5ed08982875c50b7793dac90e64387ba6e078"
    )


def test_action_record_model_priority_field_present():
    source = (BACKEND_ROOT / "app/models/action.py").read_text(encoding="utf-8")
    assert "priority: int = 100" in source
    assert "class ActionRecord" in source


def test_no_new_migrations_for_tool_system():
    versions = sorted(
        path.name for path in (BACKEND_ROOT / "migrations" / "versions").glob("*.py")
    )
    assert versions[-1].startswith("0048_")
    assert len(versions) == len({name[:4] for name in versions})
    for name in versions:
        assert "v24_tool" not in name
        source = (BACKEND_ROOT / "migrations" / "versions" / name).read_text(encoding="utf-8")
        assert "tool_executions" not in source
        assert "tool_definitions" not in source


def test_action_plan_max_steps_stays_one():
    from app.core.settings import get_settings

    assert get_settings().action_plan_max_steps == 1


def test_builtin_tool_registry_matches_v9_capability_registry():
    """TOOL-010｜**可用**工具的绑定必须可解析；`channel.feishu.send` 是声明态 disabled
    （通道未绑定），其 `channel_feishu` 能力随通道开关进入全局注册表。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    capabilities = get_capability_registry()
    for item in registry.list():
        if registry.effective_status(item.id) != "enabled":
            assert item.id == "channel.feishu.send"
            continue
        assert capabilities.has(item.capability, item.action), item.id
