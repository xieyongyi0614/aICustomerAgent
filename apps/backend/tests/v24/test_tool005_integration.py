"""TOOL-005 §6.2/§6.3：执行器接线、确认轮次闭环、维护步挂接与冻结面（形状 diff 断言）。"""

import ast
import inspect
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application import action_engine, post_process
from app.core.db import TriggerRegistryRow
from app.core.settings import get_settings
from app.models.action import (
    ACTION_STATUSES,
    GATE_REASONS,
    ActionIntent,
    make_dedupe_key,
)
from app.repositories import action_repository
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import get_capability_registry
from app.services.tool.confirmation import (
    STATUS_EXPIRED,
    STATUS_PENDING,
    ConfirmationService,
    get_confirmation_service,
    reset_session_grants,
)
from app.services.tool.context import ToolContext
from app.services.tool.executor import (
    PERMISSION_LAYER_OFF_REASON,
    PermissionSnapshot,
    ToolExecutor,
)
from app.services.tool.permission import (
    DECISION_ALLOW,
    DECISION_CONFIRM_REQUIRED,
    REASON_UNTRUSTED_NAMESPACE,
    PermissionDecision,
    ToolPermissionGate,
)
from app.services.tool.registry import ToolRegistry, get_tool_registry, register_builtin_tools
import app.repositories.trigger_registry_repository as trigger_repository
from tests.v24.tool003_support import StubCapability, build_executor, registry_with, stub_registry
from tests.v24.tool003_support import tool_settings
from tests.v24.tool005_support import (
    NOW,
    NORMAL_TOOL_ID,
    SENSITIVE_TOOL_ID,
    UNTRUSTED_TOOL_ID,
    invocation,
    normal_definition,
    notification_capability,
    permission_settings,
    sensitive_definition,
    untrusted_definition,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
USER = "u-tool005-round"
CONTENT = "明天开会"

POST_PROCESS_STEP_SEQUENCE = (
    "run_scene_update",
    "run_state_update",
    "run_goal_review",
    "run_summary",
    "run_memory_extract",
    "run_budget_observer",
    "run_evaluation",
    "run_world_update",
    "run_character_action_sync",
    "run_action_planning",
)

LIFE_LOOP_MAINTENANCE_SEQUENCE = (
    "world_maintenance",
    "world_simulation",
    "action_retry",
    "action_schedule",
    "outbox_consume",
    "trigger_reconcile",
)

PERMISSION_ON_SETTINGS = ("tool_system_enabled", "tool_permission_enabled")


@pytest.fixture(autouse=True)
def _clean_session_grants():
    reset_session_grants()
    yield
    reset_session_grants()


def _send_intent(content: str = CONTENT) -> ActionIntent:
    params = {"content": content}
    return ActionIntent(
        action_type="send_notification",
        confidence="confident",
        params=params,
        dedupe_key=make_dedupe_key("send_notification", params),
    )


def _remind_intent(fact: str = "小明喜欢喝咖啡") -> ActionIntent:
    params = {"fact": fact}
    return ActionIntent(
        action_type="remember_fact",
        confidence="confident",
        params=params,
        dedupe_key=make_dedupe_key("remember_fact", params),
    )


def _executor_settings(**overrides):
    values = {
        "tool_system_enabled": True,
        "tool_permission_enabled": True,
    }
    values.update(overrides)
    return tool_settings(**values)


def _tool_ctx(settings=None, user_id: str = USER) -> ToolContext:
    return ToolContext(user_id=user_id, now=NOW, settings=settings or permission_settings())


def _reminder_capability() -> StubCapability:
    return StubCapability(name="reminder", action="create", required=["content"])


def _memory_capability() -> StubCapability:
    return StubCapability(name="memory", action="save", required=["fact"])


def _enable(override_settings, **extra):
    override_settings(
        action_enabled=True,
        world_enabled=False,
        tool_system_enabled=True,
        tool_permission_enabled=True,
        **extra,
    )


def _wire_notification(monkeypatch, capability) -> None:
    monkeypatch.setattr(
        action_engine, "get_capability_registry", lambda: stub_registry(capability)
    )


class _SpyTrace:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(self, name: str, duration_ms: float = 0.0, status: str = "ok", **extra) -> None:
        entry = {"step": name, "status": status, "duration_ms": duration_ms}
        entry.update(extra)
        self.steps.append(entry)

    def step_names(self) -> list[str]:
        return [entry["step"] for entry in self.steps]


# --- 执行器权限段接线（TOOL-005 §2.1、§6.2） ------------------------------------


@pytest.mark.asyncio
async def test_executor_confirm_required_has_zero_external_calls(monkeypatch):
    registry = registry_with(sensitive_definition())
    capability = notification_capability()
    writes: list[str] = []
    monkeypatch.setattr(
        trigger_repository, "register", lambda *a, **k: writes.append("register")
    )
    executor = build_executor(
        registry, capability, settings=_executor_settings()
    )
    execution = await executor.run(
        registry.resolve(SENSITIVE_TOOL_ID), invocation(SENSITIVE_TOOL_ID), _tool_ctx()
    )
    assert execution.status == "pending_confirmation"
    assert execution.permission["decision"] == DECISION_CONFIRM_REQUIRED
    assert execution.permission["reason"] == "first_time_confirmation"
    assert capability.calls == []
    assert writes == []


@pytest.mark.asyncio
async def test_executor_denied_has_zero_external_calls(monkeypatch):
    registry = registry_with(untrusted_definition())
    capability = _memory_capability()
    writes: list[str] = []
    monkeypatch.setattr(
        trigger_repository, "register", lambda *a, **k: writes.append("register")
    )
    monkeypatch.setattr(trigger_repository, "list_recent", lambda *a, **k: [])
    executor = build_executor(registry, capability, settings=_executor_settings())
    execution = await executor.run(
        registry.resolve(UNTRUSTED_TOOL_ID), invocation(UNTRUSTED_TOOL_ID), _tool_ctx()
    )
    assert execution.status == "denied"
    assert execution.result["failure_kind"] == "denied"
    assert execution.permission["reason"] == REASON_UNTRUSTED_NAMESPACE
    assert capability.calls == []
    assert writes == []


@pytest.mark.asyncio
async def test_executor_level_allow_invokes_capability():
    registry = registry_with(normal_definition())
    capability = _reminder_capability()
    executor = build_executor(registry, capability, settings=_executor_settings())
    execution = await executor.run(
        registry.resolve(NORMAL_TOOL_ID),
        invocation(NORMAL_TOOL_ID, {"content": "x"}, action_type="create_reminder"),
        _tool_ctx(),
    )
    assert execution.status == "succeeded"
    assert execution.permission["decision"] == DECISION_ALLOW
    assert execution.permission["reason"] == "level_no_grant_required"
    assert capability.calls == [{"content": "x"}]


@pytest.mark.asyncio
async def test_executor_does_not_build_snapshot_when_given_one(monkeypatch):
    settings = _executor_settings()
    gate = ToolPermissionGate(settings)
    built: list[str] = []
    original = gate.build_snapshot

    def _build(user_id, now, resolved=None):
        built.append(user_id)
        return original(user_id, now, resolved)

    monkeypatch.setattr(gate, "build_snapshot", _build)
    registry = registry_with(normal_definition())
    capability = _reminder_capability()
    executor = ToolExecutor(
        registry,
        CapabilityExecutor(stub_registry(capability), 2.0),
        settings=settings,
        permission_gate=gate,
    )
    invocation_value = invocation(NORMAL_TOOL_ID, {"content": "x"}, action_type="create_reminder")
    binding = registry.resolve(NORMAL_TOOL_ID)
    await executor.run(
        binding,
        invocation_value,
        _tool_ctx(settings),
        permission_snapshot=PermissionSnapshot(user_id=USER, now=NOW, settings=settings),
    )
    assert built == []

    await executor.run(binding, invocation_value, _tool_ctx(settings))
    assert built == [USER]


@pytest.mark.asyncio
async def test_executor_master_gate_off_keeps_placeholder_allow_e14():
    registry = registry_with(untrusted_definition())
    capability = _memory_capability()
    settings = _executor_settings(tool_system_enabled=False)
    executor = build_executor(registry, capability, settings=settings)
    execution = await executor.run(
        registry.resolve(UNTRUSTED_TOOL_ID),
        invocation(UNTRUSTED_TOOL_ID),
        _tool_ctx(permission_settings(tool_system_enabled=False)),
    )
    assert execution.status == "succeeded"
    assert execution.permission["decision"] == DECISION_ALLOW
    assert execution.permission["reason"] == PERMISSION_LAYER_OFF_REASON
    assert capability.calls != []


def test_placeholder_reason_constant_removed():
    source = (BACKEND_ROOT / "app/services/tool/executor.py").read_text(encoding="utf-8")
    assert "permission_gate_placeholder_allow_all" not in source
    assert "PERMISSION_LAYER_OFF_REASON = REASON_LAYER_OFF" in source


# --- action_engine 端到端：确认登记与话术投影 ----------------------------------


async def _start_confirmation_flow(capability, user_id: str = USER):
    record = await action_engine.run_action_planning(
        user_id, _send_intent(), source="conversation"
    )
    request = get_confirmation_service().pending(user_id)[0]
    return record, request


@pytest.mark.asyncio
async def test_action_engine_maps_confirmation_to_planned_with_zero_calls(
    monkeypatch, override_settings, db_session_factory
):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)

    record = await action_engine.run_action_planning(USER, _send_intent())

    assert capability.calls == []
    assert record.status == "planned"
    assert record.gate_reason == "pending_confirmation"
    assert record.steps[0]["status"] == "skipped"
    assert record.steps[0]["permission"]["decision"] == DECISION_CONFIRM_REQUIRED
    assert CONTENT in record.result["error"]
    assert record.result["error"].endswith("吗？")

    pending = get_confirmation_service().pending(USER)
    assert len(pending) == 1
    assert pending[0].tool_id == SENSITIVE_TOOL_ID
    assert pending[0].dedupe_key == record.dedupe_key
    assert pending[0].invocation_snapshot["params"] == {"content": CONTENT}


@pytest.mark.asyncio
async def test_action_engine_denied_tool_never_reaches_confirmation(
    monkeypatch, override_settings, db_session_factory
):
    _enable(override_settings)
    registry = ToolRegistry()
    registry.register(untrusted_definition(), get_capability_registry().get("memory"))
    monkeypatch.setattr(action_engine, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(
        "app.services.action.planner.get_tool_registry", lambda: registry
    )
    reached: list[str] = []

    async def _never(self, step, ctx):
        reached.append(step.action)
        raise AssertionError("拒绝路径不得触达能力")

    monkeypatch.setattr(CapabilityExecutor, "run", _never)

    record = await action_engine.run_action_planning(USER, _remind_intent())

    assert reached == []
    assert record.status == "cancelled"
    assert record.gate_reason == "permission_denied"
    assert record.steps[0]["permission"]["decision"] == "deny"
    assert record.steps[0]["permission"]["reason"] == REASON_UNTRUSTED_NAMESPACE
    assert get_confirmation_service().pending(USER) == []


# --- 批准 / 否定 / 过期轮次 -----------------------------------------------------


async def _approved_round(monkeypatch, override_settings, db_session_factory):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)
    record, request = await _start_confirmation_flow(capability)

    seen: list[tuple[str, dict]] = []
    original_run = ToolExecutor.run

    async def _spy(self, binding, inv, ctx, *, index=0, permission_snapshot=None):
        seen.append((inv.dedupe_key, dict(inv.params)))
        return await original_run(
            self, binding, inv, ctx, index=index, permission_snapshot=permission_snapshot
        )

    monkeypatch.setattr(ToolExecutor, "run", _spy)
    resumed = await action_engine.run_confirmation_round(
        USER, request.request_id, approved=True, session_id="s-1"
    )
    return capability, record, request, seen, resumed


@pytest.mark.asyncio
async def test_approved_round_reuses_snapshot_and_dedupe_key(
    monkeypatch, override_settings, db_session_factory
):
    capability, record, _request, seen, resumed = await _approved_round(
        monkeypatch, override_settings, db_session_factory
    )
    assert resumed is not None
    assert resumed.id == record.id
    assert seen == [(record.dedupe_key, {"content": CONTENT})]
    assert capability.calls == [{"content": CONTENT}]
    assert len(action_repository.list_records(USER)) == 1
    assert resumed.status == "succeeded"
    assert resumed.gate_reason is None
    assert resumed.session_id == "s-1"


@pytest.mark.asyncio
async def test_approved_round_lands_grant_and_allows_second_call(
    monkeypatch, override_settings, db_session_factory
):
    _capability, record, request, _seen, _resumed = await _approved_round(
        monkeypatch, override_settings, db_session_factory
    )
    settings = get_settings()
    service = get_confirmation_service()
    grant = _grant_for(service, request.request_id)
    assert grant is not None
    assert grant.scope == ("self",)

    gate = ToolPermissionGate(settings)
    snapshot = gate.build_snapshot(USER, datetime.now(), settings)
    decision = gate.evaluate(sensitive_definition(), invocation(SENSITIVE_TOOL_ID), snapshot)
    assert decision.decision == DECISION_ALLOW
    assert decision.reason == "grant_matched"
    assert record.dedupe_key


def _grant_for(service: ConfirmationService, request_id: str):
    request = service.get(request_id)
    for record in service.grant_records(USER, datetime.now()):
        if record["tool_id"] == request.tool_id and record["source"] == "user_confirm":
            return SimpleNamespace(
                scope=tuple(record["scope"]), expires_at=record["expires_at"]
            )
    return None


@pytest.mark.asyncio
async def test_denied_round_cancels_record_without_execution(
    monkeypatch, override_settings, db_session_factory
):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)
    record, request = await _start_confirmation_flow(capability)

    resumed = await action_engine.run_confirmation_round(
        USER, request.request_id, approved=False
    )

    assert capability.calls == []
    assert resumed is not None and resumed.id == record.id
    assert resumed.status == "cancelled"
    assert resumed.gate_reason == "permission_denied"
    assert len(action_repository.list_records(USER)) == 1
    assert get_confirmation_service().pending(USER) == []


@pytest.mark.asyncio
async def test_expired_request_is_not_executed_e5(
    monkeypatch, override_settings, db_session_factory
):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)
    record, request = await _start_confirmation_flow(capability)

    _age_request(request.request_id, db_session_factory)

    resumed = await action_engine.run_confirmation_round(
        USER, request.request_id, approved=True
    )

    assert capability.calls == []
    assert resumed is not None and resumed.status == "cancelled"
    assert resumed.gate_reason == "permission_denied"
    assert len(action_repository.list_records(USER)) == 1
    assert get_confirmation_service().get(request.request_id).status == STATUS_EXPIRED


def _age_request(request_id: str, db_session_factory) -> None:
    stale = datetime.now() - timedelta(hours=48)
    row = trigger_repository.get(request_id)
    payload = dict(row.payload)
    payload["expires_at"] = stale.isoformat()
    session = db_session_factory()
    session.query(TriggerRegistryRow).filter(
        TriggerRegistryRow.trigger_key == request_id
    ).update({"payload": payload, "due_at": stale})
    session.commit()


@pytest.mark.asyncio
async def test_unknown_request_round_is_noop(monkeypatch, override_settings, db_session_factory):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)
    assert (
        await action_engine.run_confirmation_round(
            USER, "tool_confirm:nobody:missing", approved=True
        )
        is None
    )
    assert capability.calls == []


@pytest.mark.asyncio
async def test_confirmation_round_skipped_when_action_disabled(
    override_settings, db_session_factory
):
    override_settings(action_enabled=False)
    assert await action_engine.run_confirmation_round(USER, "any", approved=True) is None


# --- 过期清理复用既有维护步 ----------------------------------------------------


def test_expire_planned_hook_cleans_due_confirmations(
    override_settings, db_session_factory
):
    _enable(override_settings)
    service = ConfirmationService(get_settings())
    stale_ctx = ToolContext(
        user_id=USER, now=datetime.now() - timedelta(hours=48), settings=get_settings()
    )
    request = service.request(
        invocation(SENSITIVE_TOOL_ID, {"content": CONTENT}),
        PermissionDecision(
            decision=DECISION_CONFIRM_REQUIRED,
            level="sensitive",
            reason="first_time_confirmation",
            confirm_prompt="要我现在把这条消息发出去吗？",
            scope_required=("self",),
            confirm_kind="first_time",
        ),
        stale_ctx,
    )
    assert request is not None
    assert service.get(request.request_id).status == STATUS_PENDING

    action_engine._expire_planned()

    assert service.get(request.request_id).status == STATUS_EXPIRED


def _maintenance_call_names(source: str) -> tuple[str, ...]:
    calls: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "_record_maintenance_run":
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            calls.append((node.lineno, str(node.args[0].value)))
    return tuple(name for _lineno, name in sorted(calls))


def test_life_loop_maintenance_sequence_unchanged():
    """维护步序列零改动；life_loop 不新增确认清理路径（P2-1 只加 `has_due` 口径参数）。

    P2-1 后 life_loop 会 import 确认模块的 `non_todo_payload_kinds`（到期口径排除），
    故断言从"整文件不含 confirmation 字样"收紧为"不含确认服务 / 清理调用"。
    """
    source = (BACKEND_ROOT / "app/application/life_loop.py").read_text(encoding="utf-8")
    assert _maintenance_call_names(source) == LIFE_LOOP_MAINTENANCE_SEQUENCE
    assert "ConfirmationService" not in source
    assert "_expire_pending_confirmations" not in source
    assert not [step for step in LIFE_LOOP_MAINTENANCE_SEQUENCE if "confirmation" in step]


def test_life_loop_passes_due_exclusion_only_when_master_gate_on(override_settings):
    """P2-1 调用侧：工具总闸 off → 不传排除（V9 口径）；on → 传两类非待办 kind。"""
    from app.application import life_loop

    calls: list[object] = []
    original = trigger_repository.has_due

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("exclude_payload_kinds"))
        return False

    trigger_repository.has_due = _spy
    try:
        override_settings(tool_system_enabled=False)
        life_loop._cycle_reason("u-exclusion", NOW)
        override_settings(tool_system_enabled=True)
        life_loop._cycle_reason("u-exclusion", NOW)
    finally:
        trigger_repository.has_due = original

    assert calls == [None, ("tool_confirmation", "tool_grant")]


def test_expire_planned_calls_confirmation_cleanup():
    source = inspect.getsource(action_engine._expire_planned)
    assert "_expire_pending_confirmations()" in source


# --- post_process 确认轮次（步骤序列零改动） -----------------------------------


def test_post_process_step_sequence_unchanged():
    assert tuple(handler.__name__ for handler in post_process.STEP_HANDLERS) == (
        POST_PROCESS_STEP_SEQUENCE
    )


def _post_ctx(user_input: str, action_intent=None) -> SimpleNamespace:
    return SimpleNamespace(
        session_id="s-1",
        user_id=USER,
        user_input=user_input,
        ai_reply="嗯",
        action_intent=action_intent,
        selected_goal=None,
        trace=_SpyTrace(),
    )


@pytest.mark.asyncio
async def test_post_process_consumes_confirmation_reply(
    monkeypatch, override_settings, db_session_factory
):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)
    record, _request = await _start_confirmation_flow(capability)

    ctx = _post_ctx("好", action_intent=_send_intent("另一条消息"))
    await post_process.run_action_planning(ctx)

    assert capability.calls == [{"content": CONTENT}]
    assert len(action_repository.list_records(USER)) == 1
    assert "confirmation_round" in ctx.trace.step_names()
    assert action_repository.get_record(record.id).status == "succeeded"


@pytest.mark.asyncio
async def test_post_process_keeps_pending_for_unrelated_reply(
    monkeypatch, override_settings, db_session_factory
):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)
    _record, request = await _start_confirmation_flow(capability)

    ctx = _post_ctx("今天天气不错")
    await post_process.run_action_planning(ctx)

    assert capability.calls == []
    assert get_confirmation_service().get(request.request_id).status == STATUS_PENDING
    assert "confirmation_round" not in ctx.trace.step_names()
    assert len(action_repository.list_records(USER)) == 1


@pytest.mark.asyncio
async def test_post_process_confirmation_round_disabled_without_flag(override_settings):
    override_settings(action_enabled=True, tool_permission_enabled=False)
    assert await post_process._run_confirmation_round(_post_ctx("好")) is False


@pytest.mark.asyncio
async def test_post_process_pending_confirmation_enters_trace_material(
    monkeypatch, override_settings, db_session_factory
):
    _enable(override_settings)
    capability = notification_capability()
    _wire_notification(monkeypatch, capability)

    ctx = _post_ctx("帮我给大家发条消息", action_intent=_send_intent())
    await post_process.run_action_planning(ctx)

    planning = next(
        entry for entry in ctx.trace.steps if entry["step"] == "action_planning"
    )
    material = planning["pending_confirmation"]
    assert material["tool_id"] == SENSITIVE_TOOL_ID
    assert CONTENT in material["prompt"]


# --- 回复素材：确认话术进 ActionContext ----------------------------------------


def _persist_pending_record() -> str:
    record = action_engine.new_record(_send_intent(), USER, session_id="s-1")
    record.status = "planned"
    record.gate_reason = "pending_confirmation"
    record.result = {"status": "failed", "error": "要我现在把「明天开会」发出去吗？"}
    action_repository.save_record(record)
    return record.id


def test_pending_confirmation_prompt_enters_action_context(override_settings, db_session_factory):
    _enable(override_settings)
    _persist_pending_record()

    from app.services.action.context import build_action_context, render_action_section

    rendered = render_action_section(build_action_context(USER))
    assert "要我现在把「明天开会」发出去吗？" in rendered


def test_action_context_unchanged_without_permission_flag(override_settings, db_session_factory):
    override_settings(action_enabled=True, tool_permission_enabled=False)
    _persist_pending_record()

    from app.services.action.context import build_action_context, render_action_section

    rendered = render_action_section(build_action_context(USER))
    assert "发送通知" in rendered
    assert "要我现在把" not in rendered


# --- 冻结面：枚举 / 闸门顺序 ----------------------------------------------------


def test_action_status_enum_unchanged():
    assert ACTION_STATUSES == (
        "created",
        "planned",
        "executing",
        "succeeded",
        "failed",
        "cancelled",
    )


def test_gate_reasons_unchanged():
    assert GATE_REASONS == (
        "disabled",
        "ambiguous_params",
        "capability_unavailable",
        "duplicate",
        "quota_exceeded",
        "effect_already_satisfied",
        "target_not_found",
        "permission_denied",
        "invalid_params",
        "pending_confirmation",
    )


def test_v9_six_gates_order_unchanged():
    from app.services.action import planner

    source = inspect.getsource(planner.evaluate_gates)
    markers = (
        "disabled",
        "ambiguous_params",
        "_check_g3",
        "_check_g4",
        "quota_exceeded",
        "_check_g6",
    )
    positions = [source.index(marker) for marker in markers]
    assert positions == sorted(positions)


def test_six_gates_run_before_permission_gate():
    planning_source = inspect.getsource(action_engine.run_action_planning)
    assert planning_source.index("evaluate_gates") < planning_source.index("execute_plan")
    executor_source = inspect.getsource(ToolExecutor.run)
    assert executor_source.index("_evaluate_permission") < executor_source.index("_invoke")


def test_builtin_registry_matches_tool005_expectations():
    registry = ToolRegistry()
    register_builtin_tools(registry)
    notification = registry.get(SENSITIVE_TOOL_ID)
    assert notification.permission.confirm == "first_time"
    assert notification.permission.level == "sensitive"
    assert tuple(notification.permission.scope) == ("self",)
    assert registry.get("world.env.query").permission.level == "safe"


def test_tool_registry_singleton_requires_master_gate(override_settings):
    override_settings(tool_system_enabled=False)
    assert get_tool_registry() is None
