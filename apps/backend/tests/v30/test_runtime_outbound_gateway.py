"""RT-014 Outbound Gateway 测试：适配器解析 / 门控 / 幂等透传 / 失败语义 / 边界。"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_runtime import inbound as inbound_gateway
from app.application.agent_runtime import outbound as gateway
from app.channels.base import (
    ChannelErrorKind,
    OutboundMessage,
    RecipientRef,
    SendResult,
)

OUTBOUND_PATH = Path(gateway.__file__)
FORBIDDEN_IMPORTS = (
    "app.channels.feishu",
    "app.repositories",
    "app.chains",
    "app.prompts",
    "app.services.agent_service",
)

FEISHU = inbound_gateway.CHANNEL_FEISHU
EXTERNAL_USER_ID = "ou_rt014"


class StubAdapter:
    """最小 ChannelAdapter 实现：记录调用，可配置返回值或抛错。"""

    def __init__(
        self, result: SendResult | None = None, error: Exception | None = None
    ) -> None:
        self.calls: list[OutboundMessage] = []
        self._result = result
        self._error = error

    async def send(self, message: OutboundMessage) -> SendResult:
        self.calls.append(message)
        if self._error is not None:
            raise self._error
        return self._result or SendResult(ok=True, external_message_id="om_out")


class FakeTrace:
    """记录 Trace step 的轻量替身（与 TurnTraceSession.record 同签名）。"""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(
        self,
        name,
        _duration_ms,
        status="ok",
        _first_token_ms=None,
        error=None,
        **extra,
    ) -> None:
        self.steps.append({"name": name, "status": status, "error": error, **extra})


def _message(**overrides) -> OutboundMessage:
    kwargs = {
        "channel": FEISHU,
        "recipient": RecipientRef(channel=FEISHU, external_id=EXTERNAL_USER_ID),
        "text": "在的",
        "reply_ref": "om_1",
        "idempotency_key": None,
        "metadata": {},
    }
    kwargs.update(overrides)
    return OutboundMessage(**kwargs)


@pytest.fixture(autouse=True)
def _clean_registry():
    gateway.clear_adapters()
    yield
    gateway.clear_adapters()


class TestDeliver:
    pytestmark = pytest.mark.unit

    async def test_deliver_dispatches_to_registered_adapter(self, override_settings):
        adapter = StubAdapter()
        override_settings(runtime_outbound_gateway_channels="feishu")
        gateway.register_adapter(FEISHU, adapter)
        message = _message()

        result = await gateway.deliver(message)

        assert result.ok is True
        assert result.external_message_id == "om_out"
        assert len(adapter.calls) == 1
        assert adapter.calls[0] is message

    async def test_unknown_or_unmanaged_channel_returns_disabled(
        self, override_settings
    ):
        adapter = StubAdapter()
        gateway.register_adapter(FEISHU, adapter)
        override_settings(runtime_outbound_gateway_channels="")

        unmanaged = await gateway.deliver(_message())
        unknown = await gateway.deliver(_message(channel="discord"))

        override_settings(runtime_outbound_gateway_channels="feishu")
        gateway.clear_adapters()
        unregistered = await gateway.deliver(_message())

        assert unmanaged.ok is False
        assert unmanaged.error is ChannelErrorKind.DISABLED
        assert unknown.error is ChannelErrorKind.DISABLED
        assert unregistered.error is ChannelErrorKind.DISABLED
        assert not adapter.calls

    def test_gateway_disabled_by_default(self):
        assert gateway.enabled_channels() == frozenset()
        assert gateway.is_enabled(FEISHU) is False
        assert gateway.is_routable(FEISHU) is False
        assert gateway.registered_channels() == frozenset()
        assert gateway.resolve_adapter(FEISHU) is None

    async def test_adapter_exception_becomes_send_result(self, override_settings):
        override_settings(runtime_outbound_gateway_channels="feishu")
        gateway.register_adapter(
            FEISHU, StubAdapter(error=RuntimeError("channel down"))
        )

        result = await gateway.deliver(_message())

        assert result.ok is False
        assert result.error is ChannelErrorKind.UNKNOWN

    async def test_idempotency_key_is_passed_through(self, override_settings):
        adapter = StubAdapter()
        override_settings(runtime_outbound_gateway_channels="feishu")
        gateway.register_adapter(FEISHU, adapter)

        await gateway.deliver(
            _message(idempotency_key="proactive:feishu:ou_rt014:key-1")
        )

        assert adapter.calls[0].idempotency_key == "proactive:feishu:ou_rt014:key-1"

    def test_register_adapter_is_idempotent_and_overridable(self):
        first = StubAdapter()
        second = StubAdapter()

        gateway.register_adapter(FEISHU, first)
        gateway.register_adapter(FEISHU, second)

        assert gateway.resolve_adapter(FEISHU) is second
        assert gateway.registered_channels() == frozenset({FEISHU})

    def test_outbound_module_has_no_forbidden_imports(self):
        tree = ast.parse(OUTBOUND_PATH.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        offenders = [
            name
            for name in imported
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORTS
            )
        ]
        assert offenders == []

    async def test_deliver_records_trace_step(self, override_settings):
        override_settings(runtime_outbound_gateway_channels="feishu")
        gateway.register_adapter(FEISHU, StubAdapter())
        trace = FakeTrace()

        await gateway.deliver(_message(), trace=trace)

        assert len(trace.steps) == 1
        step = trace.steps[0]
        assert step["name"] == gateway.TRACE_STEP_OUTBOUND
        assert step["status"] == "ok"
        assert step["ok"] is True
        assert step["error"] is None
        assert step["external_message_id"] == "om_out"


class TestIntegration:
    pytestmark = pytest.mark.integration

    async def test_deliver_writes_no_tables(
        self, override_settings, db_session_factory
    ):
        from app.core.db import Base

        override_settings(runtime_outbound_gateway_channels="feishu")
        gateway.register_adapter(FEISHU, StubAdapter(error=RuntimeError("boom")))

        def _counts():
            with db_session_factory() as session:
                return {
                    table.name: session.query(table).count()
                    for table in Base.metadata.sorted_tables
                }

        before = _counts()

        await gateway.deliver(_message())

        assert _counts() == before

    async def test_proactive_executor_uses_gateway(
        self, override_settings, monkeypatch, db_session_factory
    ):
        from app.channels.feishu import delivery
        from app.core.db import Base
        from app.services import channel_identity_service
        from app.services.delivery import outbound as proactive_delivery
        from app.services import proactive_executor

        def _identity_rows():
            with db_session_factory() as session:
                return session.query(
                    Base.metadata.tables["channel_identities"]
                ).count()

        resolved = channel_identity_service.resolve(FEISHU, EXTERNAL_USER_ID)
        rows_before = _identity_rows()
        legacy_calls: list[tuple] = []

        async def _spy(user_id, text, key):
            legacy_calls.append((user_id, text, key))
            return SendResult(ok=True, external_message_id="om-legacy")

        monkeypatch.setattr(delivery, "send_proactive", _spy)
        port = proactive_delivery.ProactiveOutbound(channel=FEISHU, send=_spy)
        adapter = StubAdapter()
        gateway.register_adapter(FEISHU, adapter)
        action = SimpleNamespace(
            user_id=resolved.internal_user_id, dedupe_key="proactive:key-1"
        )

        override_settings(runtime_outbound_gateway_channels="feishu")
        managed = await proactive_executor._send_via_outbound(port, action, "在的", None)

        assert managed.ok is True
        assert len(adapter.calls) == 1
        assert adapter.calls[0].idempotency_key == "proactive:key-1"
        assert not legacy_calls

        gateway.clear_adapters()
        override_settings(runtime_outbound_gateway_channels="")
        legacy = await proactive_executor._send_via_outbound(port, action, "在的", None)

        assert legacy.ok is True
        assert legacy.external_message_id == "om-legacy"
        assert len(legacy_calls) == 1
        assert _identity_rows() == rows_before
