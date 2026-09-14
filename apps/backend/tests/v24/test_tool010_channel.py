"""TOOL-010 §6.2/§6.3：通道工具执行链、错误映射、幂等与确认流（E2~E9）。"""

import ast
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.channels.base import ChannelErrorKind, OutboundMessage, SendResult
from app.channels.feishu.identity import FEISHU_CHANNEL
from app.channels.feishu.outbound import split_text
from app.models.action import ActionIntent, make_dedupe_key
from app.models.tool import ToolInvocation
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import ExecutionContext
from app.services.tool import channel_tools
from app.services.tool.channel_tools import (
    ADAPTER_MISSING_REASON,
    CHANNEL_CAPABILITY_NAME,
    CHANNEL_ERROR_FAILURE_KINDS,
    CHANNEL_NAME,
    CHANNEL_SCOPE,
    CHANNEL_SEND_TOOL_ID,
    CHANNEL_TEXT_MAX_CHARS,
    ChannelCapability,
    failure_kind_for,
    idempotency_key_for,
    is_retryable,
)
from app.services.tool.confirmation import (
    STATUS_APPROVED,
    STATUS_DENIED,
    ConfirmationService,
)
from app.services.tool.executor import ToolExecutor
from app.services.tool.normalizer import (
    EXTERNAL_EFFECT_PAYLOAD_KEY,
    EXTERNAL_MESSAGE_ID_PAYLOAD_KEY,
)
from app.services.tool.permission import (
    DECISION_ALLOW,
    DECISION_CONFIRM_REQUIRED,
    REASON_FIRST_TIME_CONFIRMATION,
    REASON_GRANT_MATCHED,
    ToolPermissionGate,
)
from app.services.tool.validator import CONTENT_BUDGET_CHARS
from tests.v24.tool003_support import stub_registry
from tests.v24.tool005_support import grant, permission_settings, snapshot
from tests.v24.tool010_support import (
    CHANNEL_ENVS,
    CHANNEL_TOOL_ID,
    EXTERNAL_ID,
    NOW,
    USER,
    RecordingAdapter,
    builtin_registry,
    enable,
    failure,
    reset_runtime_state,
    tool_context,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

CONTENT = "在吗，记得吃饭"

DEDUPE_KEY = "dk-tool010-channel"

# `permission.scope` 在声明里是单元素元组，授权范围必须与其逐字对齐。
CHANNEL_SCOPE_TUPLE: tuple[str, ...] = (CHANNEL_SCOPE,)


@pytest.fixture(autouse=True)
def _isolate_singletons(monkeypatch):
    """本文件默认在通道绑定态下运行（`channel.feishu.send` 声明为 enabled）；
    需要 disabled 的 E4 用例在用例内自行降级开关并重建注册表。"""
    enable(monkeypatch, **CHANNEL_ENVS)
    reset_runtime_state()
    yield
    reset_runtime_state()


def _settings(**overrides):
    values = {
        "v24_tool_system_enabled": True,
        "v24_tool_permission_enabled": True,
        "v24_tool_schema_validation_enabled": True,
        "v24_tool_observation_enabled": True,
        "v24_tool_channel_enabled": True,
        "feishu_enabled": True,
        "v24_tool_confirm_timeout_hours": 24,
        "v24_tool_confirm_ttl_reuse": True,
        "v24_tool_ext_allowed_hosts": "",
        "v24_tool_breaker_threshold": 3,
        "v24_tool_breaker_cooldown_seconds": 300,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _invocation(params: dict | None = None, dedupe_key: str = DEDUPE_KEY) -> ToolInvocation:
    payload = dict(params or {"content": CONTENT, "recipient": EXTERNAL_ID})
    return ToolInvocation(
        tool_id=CHANNEL_TOOL_ID,
        params=payload,
        rationale="用户要求发消息",
        source="conversation",
        intent=ActionIntent(
            action_type="send_notification",
            confidence="confident",
            params=payload,
            dedupe_key=make_dedupe_key("send_notification", payload),
        ),
        dedupe_key=dedupe_key,
    )


def _ctx(settings=None, *, now: datetime | None = None, dedupe_key: str = DEDUPE_KEY):
    return tool_context(
        settings if settings is not None else _settings(),
        now=now or NOW,
        dedupe_key=dedupe_key,
    )


def _executor(
    adapter: RecordingAdapter, settings=None, *, gate=None, registry=None
) -> ToolExecutor:
    resolved = settings if settings is not None else _settings()
    capability = ChannelCapability(adapter=adapter)
    capability_executor = CapabilityExecutor(stub_registry(capability), 2.0)
    return ToolExecutor(
        registry if registry is not None else builtin_registry(),
        capability_executor,
        settings=resolved,
        permission_gate=gate if gate is not None else ToolPermissionGate(resolved),
    )


def _granted(settings=None):
    return snapshot(
        grants=[grant(CHANNEL_TOOL_ID, CHANNEL_SCOPE_TUPLE)],
        settings=settings if settings is not None else _settings(),
        now=NOW,
    )


def _channel_decision(settings=None, *, grants=None, now: datetime | None = None):
    resolved = settings if settings is not None else _settings()
    gate = ToolPermissionGate(resolved)
    definition = builtin_registry().get(CHANNEL_TOOL_ID)
    decision = gate.evaluate(
        definition,
        _invocation(),
        snapshot(grants=grants or [], now=now or NOW, settings=resolved),
    )
    return gate, definition, decision


# --- §2.3 错误映射表逐行 ------------------------------------------------------


CHANNEL_ERROR_TABLE = (
    (ChannelErrorKind.RATE_LIMITED, "transient", True),
    (ChannelErrorKind.TIMEOUT, "timeout", True),
    (ChannelErrorKind.SERVER_ERROR, "transient", True),
    (ChannelErrorKind.AUTH, "permanent", False),
    (ChannelErrorKind.DISABLED, "permanent", False),
    (ChannelErrorKind.NOT_FOUND, "permanent", False),
    (ChannelErrorKind.INVALID_REQUEST, "permanent", False),
    (ChannelErrorKind.CLIENT_ERROR, "transient", True),
    (ChannelErrorKind.UNKNOWN, "transient", True),
)


@pytest.mark.parametrize(
    "error_kind,expected_kind,expected_retry", CHANNEL_ERROR_TABLE, ids=lambda value: str(value)
)
def test_error_mapping_table_row_by_row(error_kind, expected_kind, expected_retry):
    assert failure_kind_for(error_kind) == expected_kind
    assert is_retryable(expected_kind) is expected_retry


def test_error_mapping_covers_every_declared_channel_error_kind():
    assert set(CHANNEL_ERROR_FAILURE_KINDS) == set(ChannelErrorKind)
    assert set(CHANNEL_ERROR_FAILURE_KINDS.values()) <= {"transient", "timeout", "permanent"}


def test_retryable_kinds_match_v9_retry_policy():
    from app.application.action_engine import RETRYABLE_FAILURES

    assert channel_tools.RETRYABLE_FAILURE_KINDS == RETRYABLE_FAILURES
    assert channel_tools.NON_RETRYABLE_CHANNEL_ERRORS == ("auth", "disabled")
    for name in channel_tools.NON_RETRYABLE_CHANNEL_ERRORS:
        assert failure_kind_for(ChannelErrorKind(name)) == "permanent"


@pytest.mark.parametrize(
    "error_kind,expected_kind,expected_retry", CHANNEL_ERROR_TABLE, ids=lambda value: str(value)
)
async def test_channel_failure_surface_matches_mapping(error_kind, expected_kind, expected_retry):
    adapter = RecordingAdapter(failure(error_kind))
    result = await ChannelCapability(adapter=adapter).execute("send", _invocation().params, _ctx())
    assert result.status == ("timeout" if expected_kind == "timeout" else "failed")
    assert result.payload["failure_kind"] == expected_kind
    assert result.payload["retryable"] is expected_retry
    assert result.payload["channel_error"] == str(error_kind)
    assert result.payload["external_sent"] is False
    assert result.payload["message"]
    assert len(adapter.messages) == 1


async def test_e5_auth_failure_is_permanent_and_counts_in_health():
    registry = builtin_registry()
    adapter = RecordingAdapter(failure(ChannelErrorKind.AUTH))
    execution = await _executor(adapter, registry=registry).run(
        registry.resolve(CHANNEL_TOOL_ID),
        _invocation(),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert execution.status == "failed"
    assert execution.result["failure_kind"] == "permanent"
    assert execution.result["effects"] == []
    record = registry.health(CHANNEL_TOOL_ID)[CHANNEL_TOOL_ID]
    assert record.consecutive_failures == 1
    assert record.failure_rate_window == 1.0
    assert record.last_failure_at is not None


async def test_e6_rate_limited_is_retryable_and_counts_in_health():
    registry = builtin_registry()
    adapter = RecordingAdapter(failure(ChannelErrorKind.RATE_LIMITED))
    execution = await _executor(adapter, registry=registry).run(
        registry.resolve(CHANNEL_TOOL_ID),
        _invocation(),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert execution.status == "failed"
    assert execution.result["failure_kind"] == "transient"
    record = registry.health(CHANNEL_TOOL_ID)[CHANNEL_TOOL_ID]
    assert record.consecutive_failures == 1
    assert record.last_failure_at is not None


# --- 成功路径与 E7 ----------------------------------------------------------


async def test_success_reports_external_effect_with_message_id():
    adapter = RecordingAdapter(SendResult(ok=True, external_message_id="om-7"))
    execution = await _executor(adapter).run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation(),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert execution.status == "succeeded"
    assert execution.result["effects"] == [
        {
            "kind": "external",
            "ref": "om-7",
            "detail": "飞书通道发送",
            "reversible": False,
        }
    ]
    assert execution.result["observations"] == {"external.message_id": "om-7"}
    assert execution.result["payload"]["external_message_id"] == "om-7"
    assert adapter.texts == [CONTENT]


async def test_e7_success_without_external_message_id_is_not_a_failure():
    adapter = RecordingAdapter(SendResult(ok=True, external_message_id=None))
    execution = await _executor(adapter).run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation(),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert execution.status == "succeeded"
    assert execution.result["failure_kind"] is None
    assert execution.result["effects"][0]["ref"] == ""
    assert execution.result["payload"][EXTERNAL_EFFECT_PAYLOAD_KEY] is True
    assert execution.result["payload"][EXTERNAL_MESSAGE_ID_PAYLOAD_KEY] == ""


# --- E2 内容预算 -------------------------------------------------------------


async def test_content_budget_semantic_net_applies_to_undeclared_fields():
    """语义层 `content_within_budget` 是安全网：对未声明结构预算的字段同样生效。"""
    from app.models.tool import ToolSchema
    from app.services.tool.validator import ParamValidator
    from tests.v24.tool002_support import definition, parameter

    validator = ParamValidator()
    undecorated = definition(
        input_schema=ToolSchema(
            parameters=[parameter("content", required=True)],
            semantic_validators=("content_within_budget",),
        )
    )
    report = validator.validate(undecorated, {"content": "长" * (CONTENT_BUDGET_CHARS + 1)}, _ctx())
    assert [issue["code"] for issue in report.semantic] == ["content_over_budget"]
    assert report.semantic[0]["param"] == "content"

    query_tool = definition(
        id="builtin.probe.query",
        input_schema=ToolSchema(
            parameters=[parameter("query", required=True)],
            semantic_validators=("content_within_budget",),
        ),
    )
    assert [
        issue["code"]
        for issue in validator.validate(
            query_tool, {"query": "长" * (CONTENT_BUDGET_CHARS + 1)}, _ctx()
        ).semantic
    ] == ["content_over_budget"]


async def test_e2_over_budget_content_is_blocked_before_the_channel():
    adapter = RecordingAdapter()
    execution = await _executor(adapter).run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation({"content": "长" * (CHANNEL_TEXT_MAX_CHARS + 1), "recipient": EXTERNAL_ID}),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert execution.status == "invalid"
    assert adapter.messages == []
    assert [issue["code"] for issue in execution.validation["structural"]] == [
        "length_violated"
    ]
    assert execution.validation["structural"][0]["param"] == "content"


# --- E3 收件人授权 ----------------------------------------------------------


async def test_e3_unauthorized_recipient_is_invalid_and_never_confirms():
    adapter = RecordingAdapter()
    executor = _executor(adapter)
    execution = await executor.run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation({"content": CONTENT, "recipient": "ou_outside"}),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert execution.status == "invalid"
    assert adapter.messages == []
    assert [issue["code"] for issue in execution.validation["semantic"]] == [
        "recipient_not_authorized"
    ]
    assert execution.validation["semantic"][0]["param"] == "recipient"
    assert execution.permission["decision"] == DECISION_ALLOW


async def test_e3_unauthorized_recipient_blocks_even_without_permission_layer():
    adapter = RecordingAdapter()
    settings = _settings(v24_tool_system_enabled=False, v24_tool_permission_enabled=False)
    executor = _executor(adapter, settings)
    execution = await executor.run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation({"content": CONTENT, "recipient": "ou_outside"}),
        _ctx(settings),
    )
    assert execution.status == "invalid"
    assert adapter.messages == []


# --- E4 通道未绑定 ----------------------------------------------------------


async def test_e4_capability_reports_unavailable_when_channel_is_off():
    adapter = RecordingAdapter()
    result = await ChannelCapability(adapter=adapter).execute(
        "send",
        _invocation().params,
        _ctx(_settings(feishu_enabled=False)),
    )
    assert result.status == "unavailable"
    assert result.payload["failure_kind"] == "unavailable"
    assert result.payload["message"]
    assert adapter.messages == []


async def test_e4_executor_short_circuits_disabled_channel_tool(monkeypatch):
    enable(monkeypatch, v24_tool_system_enabled=False, v24_tool_channel_enabled=False)
    reset_runtime_state()
    registry = builtin_registry()
    adapter = RecordingAdapter()
    execution = await _executor(adapter, registry=registry).run(
        registry.resolve(CHANNEL_TOOL_ID), _invocation(), _ctx()
    )
    assert execution.status == "unavailable"
    assert adapter.messages == []
    assert registry.effective_status(CHANNEL_TOOL_ID) == "disabled"


# --- 幂等键 -----------------------------------------------------------------


async def test_idempotency_key_equals_invocation_dedupe_key():
    adapter = RecordingAdapter()
    await _executor(adapter).run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation(dedupe_key=DEDUPE_KEY),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert adapter.idempotency_keys == [DEDUPE_KEY]
    assert adapter.messages[0].channel == FEISHU_CHANNEL
    assert adapter.messages[0].recipient.external_id == EXTERNAL_ID


async def test_e9_same_content_and_recipient_reuse_same_idempotency_key():
    adapter = RecordingAdapter()
    executor = _executor(adapter)
    binding = builtin_registry().resolve(CHANNEL_TOOL_ID)
    grants = [grant(CHANNEL_TOOL_ID, CHANNEL_SCOPE_TUPLE)]
    for _ in range(2):
        await executor.run(
            binding,
            _invocation(),
            _ctx(),
            permission_snapshot=snapshot(grants=grants, settings=_settings()),
        )
    assert adapter.idempotency_keys == [DEDUPE_KEY, DEDUPE_KEY]
    assert len(set(adapter.idempotency_keys)) == 1


def test_idempotency_key_falls_back_deterministically():
    ctx = ExecutionContext(user_id=USER, record_id="r-1", now=NOW, dedupe_key="")
    first = idempotency_key_for(ctx, CONTENT, EXTERNAL_ID)
    second = idempotency_key_for(ctx, CONTENT, EXTERNAL_ID)
    other = idempotency_key_for(ctx, CONTENT, "ou_other")
    assert first == second
    assert first != other
    assert first.startswith("derived:")
    assert idempotency_key_for(
        ExecutionContext(user_id=USER, dedupe_key=DEDUPE_KEY), CONTENT, EXTERNAL_ID
    ) == DEDUPE_KEY


# --- 文本切分不变式 ---------------------------------------------------------


def _channel_tool_imports() -> list[str]:
    path = BACKEND_ROOT / "app/services/tool/channel_tools.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    return imported


def test_split_invariant_is_reused_not_rewritten():
    """切分属通道层职责：工具层既不 import 切分函数、也不自造分段实现。"""
    imported = _channel_tool_imports()
    assert not any(name.endswith("feishu.outbound") for name in imported)
    assert not any(name.endswith("feishu.delivery") for name in imported)
    for text in (CONTENT, "长" * CHANNEL_TEXT_MAX_CHARS, "第一段。第二段！第三段？"):
        parts = split_text(text, 4000)
        assert "".join(parts) == text
    assert split_text(CONTENT, 4000) == [CONTENT]
    assert split_text("长" * CHANNEL_TEXT_MAX_CHARS, 100) == ["长" * 100, "长" * 100]


async def test_adapter_receives_original_text_without_tool_side_rewriting():
    adapter = RecordingAdapter()
    text = "第一段。第二段！"
    await _executor(adapter).run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation({"content": text, "recipient": EXTERNAL_ID}),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert adapter.texts == [text]

    # 结构层空白折叠（TOOL-003）是唯一允许的改写，且仍非"分段"：
    # 折行内容要经既有通道层 `split_text` 才切分，工具层不介入。
    folded = RecordingAdapter()
    await _executor(folded).run(
        builtin_registry().resolve(CHANNEL_TOOL_ID),
        _invocation({"content": "第一段。\n\n第二段！", "recipient": EXTERNAL_ID}),
        _ctx(),
        permission_snapshot=_granted(),
    )
    assert folded.texts == ["第一段。 第二段！"]


# --- 适配器接缝（依赖倒置，R2） ----------------------------------------------


def test_channel_tools_never_import_channel_implementation():
    path = BACKEND_ROOT / "app/services/tool/channel_tools.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    channel_imports = [name for name in imported if name.startswith("app.channels.")]
    assert channel_imports == ["app.channels.base"]
    assert "app.channels.feishu" not in path.read_text(encoding="utf-8")


def test_channel_name_matches_channel_layer_constant():
    assert CHANNEL_NAME == FEISHU_CHANNEL
    assert CHANNEL_CAPABILITY_NAME == "channel_feishu"
    assert CHANNEL_SCOPE == "channel:feishu"
    assert CHANNEL_SEND_TOOL_ID == f"channel.{FEISHU_CHANNEL}.send"


def test_adapter_port_round_trip():
    adapter = RecordingAdapter()
    channel_tools.register_channel_adapter(CHANNEL_NAME, adapter)
    assert channel_tools.get_channel_adapter() is adapter
    assert channel_tools.get_channel_adapter(CHANNEL_NAME) is adapter
    assert channel_tools.get_channel_adapter("slack") is None
    channel_tools.reset_channel_adapters()
    assert channel_tools.get_channel_adapter() is None


async def test_unregistered_adapter_yields_unavailable_without_side_effects():
    channel_tools.reset_channel_adapters()
    result = await ChannelCapability().execute("send", _invocation().params, _ctx())
    assert result.status == "unavailable"
    assert result.payload["reason_kind"] == ADAPTER_MISSING_REASON
    assert result.payload["external_sent"] is False


async def test_adapter_exception_is_normalized_not_raised():
    class _Boom:
        async def send(self, message):
            raise RuntimeError("boom")

    result = await ChannelCapability(adapter=_Boom()).execute(
        "send", _invocation().params, _ctx()
    )
    assert result.status == "failed"
    assert result.payload["failure_kind"] == "transient"
    assert result.payload["channel_error"] == str(ChannelErrorKind.UNKNOWN)


# --- 确认流端到端（首发 → 批准 → TTL 复用 → 过期再确认） --------------------


def test_confirm_gate_requires_first_time_confirmation():
    _gate, _definition, decision = _channel_decision()
    assert decision.decision == DECISION_CONFIRM_REQUIRED
    assert decision.reason == REASON_FIRST_TIME_CONFIRMATION
    assert decision.confirm_kind == "first_time"
    assert decision.scope_required == CHANNEL_SCOPE_TUPLE
    assert decision.confirm_prompt
    assert len(decision.confirm_prompt) <= 60


def test_confirm_gate_allows_within_ttl_grant():
    now = datetime.now()
    _gate, _definition, decision = _channel_decision(
        grants=[grant(CHANNEL_TOOL_ID, CHANNEL_SCOPE_TUPLE, expires_at=now + timedelta(hours=1))],
        now=now,
    )
    assert decision.decision == DECISION_ALLOW
    assert decision.reason == REASON_GRANT_MATCHED


def test_confirm_gate_requires_confirmation_after_ttl():
    now = datetime.now()
    _gate, _definition, decision = _channel_decision(
        grants=[grant(CHANNEL_TOOL_ID, CHANNEL_SCOPE_TUPLE, expires_at=now - timedelta(seconds=1))],
        now=now,
    )
    assert decision.decision == DECISION_CONFIRM_REQUIRED
    assert decision.reason == REASON_FIRST_TIME_CONFIRMATION


@pytest.mark.asyncio
async def test_confirmation_round_trip_first_time_then_ttl_reuse_then_expired(
    db_session_factory,
):
    settings = _settings()
    service = ConfirmationService(settings)
    adapter = RecordingAdapter(SendResult(ok=True, external_message_id="om-1"))
    executor = _executor(adapter, settings)
    binding = builtin_registry().resolve(CHANNEL_TOOL_ID)
    inv = _invocation()

    first = await executor.run(binding, inv, _ctx(settings))
    assert first.status == "pending_confirmation"
    assert adapter.messages == []
    assert first.permission["decision"] == DECISION_CONFIRM_REQUIRED

    gate, definition, decision = _channel_decision(settings)
    request = service.request(inv, decision, _ctx(settings))
    assert request is not None
    assert request.tool_id == CHANNEL_TOOL_ID
    assert request.dedupe_key == DEDUPE_KEY
    assert request.invocation_snapshot["params"]["recipient"] == EXTERNAL_ID

    still_pending = await executor.run(binding, inv, _ctx(settings))
    assert still_pending.status == "pending_confirmation"
    assert adapter.messages == []

    outcome = service.resolve(request.request_id, approved=True)
    assert outcome.status == STATUS_APPROVED
    assert outcome.migrated is True

    reused = await executor.run(
        binding, inv, _ctx(settings, now=datetime.now() + timedelta(hours=1))
    )
    assert reused.status == "succeeded"
    assert len(adapter.messages) == 1
    assert adapter.idempotency_keys == [DEDUPE_KEY]
    assert reused.permission["decision"] == DECISION_ALLOW
    assert reused.permission["reason"] == REASON_GRANT_MATCHED

    expired = await executor.run(
        binding, inv, _ctx(settings, now=datetime.now() + timedelta(hours=25))
    )
    assert expired.status == "pending_confirmation"
    assert len(adapter.messages) == 1
    assert expired.permission["reason"] == REASON_FIRST_TIME_CONFIRMATION


@pytest.mark.asyncio
async def test_e8_denying_a_pending_request_puts_it_to_denied(db_session_factory):
    settings = _settings()
    service = ConfirmationService(settings)
    _gate, _definition, decision = _channel_decision(settings)
    request = service.request(_invocation(), decision, _ctx(settings))
    outcome = service.resolve(request.request_id, approved=False)
    assert outcome.status == STATUS_DENIED
    assert outcome.migrated is True
    assert service.pending(USER) == []


@pytest.mark.asyncio
async def test_e8_denying_after_approval_does_not_revert(db_session_factory):
    settings = _settings()
    service = ConfirmationService(settings)
    _gate, _definition, decision = _channel_decision(settings)
    request = service.request(_invocation(), decision, _ctx(settings))
    assert service.resolve(request.request_id, approved=True).status == STATUS_APPROVED
    replay = service.resolve(request.request_id, approved=False)
    assert replay.status == STATUS_APPROVED
    assert replay.migrated is False
    assert replay.reason == "already_resolved"


# --- E2/E3 之外的声明面复核 --------------------------------------------------


def test_channel_tool_is_not_offered_in_autonomy_profile():
    from app.services.tool.surface import ToolSurfaceResolver
    from tests.v24.tool004_support import surface_context

    settings = permission_settings()
    surface = ToolSurfaceResolver(builtin_registry(), settings).resolve(
        "autonomous_tick", surface_context(settings=settings)
    )
    assert CHANNEL_TOOL_ID not in surface.tool_ids


def test_outbound_message_contract_is_reused_verbatim():
    message = OutboundMessage(
        channel=FEISHU_CHANNEL,
        recipient=channel_tools.RecipientRef(channel=FEISHU_CHANNEL, external_id=EXTERNAL_ID),
        text=CONTENT,
        idempotency_key=DEDUPE_KEY,
    )
    assert message.reply_ref is None
    assert message.idempotency_key == DEDUPE_KEY


def test_channel_env_enablement_still_requires_feishu_binding(monkeypatch):
    from app.core.settings import get_settings
    from app.core.settings.enablement import enablement_violations

    enable(
        monkeypatch,
        v24_tool_system_enabled=True,
        v24_tool_channel_enabled=True,
        feishu_enabled=False,
    )
    violations = enablement_violations(get_settings())
    assert any("feishu_enabled" in violation for violation in violations)
    enable(monkeypatch, **CHANNEL_ENVS)
    assert enablement_violations(get_settings()) == []
