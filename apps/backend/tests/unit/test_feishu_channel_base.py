import ast
import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.channels.base import (
    ChannelAdapter,
    ChannelErrorKind,
    ChannelIdentity,
    ChannelReply,
    InboundMessage,
    OutboundMessage,
    RecipientRef,
    SendResult,
    TEXT_MAX_CHARS,
)

BASE_PATH = Path("app/channels/base.py")

INBOUND_FIELD_EXPECTATIONS = {
    "InboundMessage": {"channel", "external_user_id", "text", "received_at", "external_thread_id", "reply_ref", "metadata"},
    "ChannelIdentity": {"channel", "external_user_id", "tenant", "display_name"},
    "ChannelReply": {"text", "reply_ref", "metadata"},
}

OUTBOUND_FIELD_EXPECTATIONS = {
    "RecipientRef": {"channel", "external_id"},
    "OutboundMessage": {"channel", "recipient", "text", "reply_ref", "idempotency_key", "metadata"},
    "SendResult": {"ok", "external_message_id", "error"},
}

FORBIDDEN_INBOUND_FIELDS = {
    "open_id",
    "union_id",
    "tenant_key",
    "chat_id",
    "message_id",
    "event_id",
    "app_id",
    "tenant_access_token",
    "encrypt_key",
    "signature",
}

FORBIDDEN_OUTBOUND_FIELDS = {
    "open_id",
    "union_id",
    "chat_id",
    "message_id",
    "reply_message_id",
    "receive_id",
    "receive_id_type",
    "msg_type",
    "tenant_access_token",
    "app_id",
}


def _fields_of(dataclass_type):
    return {f.name for f in dataclasses.fields(dataclass_type)}


def _now():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_inbound_field_whitelists():
    for name, expected in INBOUND_FIELD_EXPECTATIONS.items():
        dataclass_type = globals()[name]
        assert _fields_of(dataclass_type) == expected, name


def test_outbound_field_whitelists():
    for name, expected in OUTBOUND_FIELD_EXPECTATIONS.items():
        dataclass_type = globals()[name]
        assert _fields_of(dataclass_type) == expected, name


def test_forbidden_feishu_field_names_absent():
    all_field_names = set()
    for dataclass_type in (
        InboundMessage,
        ChannelIdentity,
        ChannelReply,
        RecipientRef,
        OutboundMessage,
        SendResult,
    ):
        all_field_names |= _fields_of(dataclass_type)
    for forbidden in FORBIDDEN_INBOUND_FIELDS | FORBIDDEN_OUTBOUND_FIELDS:
        assert forbidden not in all_field_names, forbidden


def test_dataclasses_are_frozen():
    message = InboundMessage(
        channel="feishu",
        external_user_id="ou_x",
        text="hello",
        received_at=_now(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        message.channel = "web"
    recipient = RecipientRef(channel="feishu", external_id="ou_x")
    outbound = OutboundMessage(channel="feishu", recipient=recipient, text="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        outbound.text = "changed"


def test_inbound_guards_reject_empty_fields():
    with pytest.raises(ValueError):
        InboundMessage(channel="", external_user_id="ou_x", text="hi", received_at=_now())
    with pytest.raises(ValueError):
        InboundMessage(channel="feishu", external_user_id="", text="hi", received_at=_now())
    with pytest.raises(ValueError):
        InboundMessage(channel="feishu", external_user_id="ou_x", text="   ", received_at=_now())
    with pytest.raises(ValueError):
        ChannelIdentity(channel="", external_user_id="ou_x")
    with pytest.raises(ValueError):
        ChannelReply(text="")


def test_inbound_rejects_naive_datetime():
    with pytest.raises(ValueError):
        InboundMessage(
            channel="feishu",
            external_user_id="ou_x",
            text="hi",
            received_at=datetime(2026, 1, 1),
        )


def test_inbound_long_text_truncated_with_metadata_flag():
    long_text = "x" * (TEXT_MAX_CHARS + 10)
    message = InboundMessage(
        channel="feishu",
        external_user_id="ou_x",
        text=long_text,
        received_at=_now(),
    )
    assert len(message.text) == TEXT_MAX_CHARS
    assert message.metadata["truncated"] is True

    reply = ChannelReply(text="y" * (TEXT_MAX_CHARS + 1))
    assert len(reply.text) == TEXT_MAX_CHARS
    assert reply.metadata["truncated"] is True

    short = InboundMessage(
        channel="feishu", external_user_id="ou_x", text="ok", received_at=_now()
    )
    assert short.metadata.get("truncated", False) is False


def test_outbound_reply_and_proactive_forms_constructible():
    recipient = RecipientRef(channel="feishu", external_id="ou_x")
    proactive = OutboundMessage(channel="feishu", recipient=recipient, text="hello")
    assert proactive.reply_ref is None
    assert proactive.idempotency_key is None
    reply = OutboundMessage(
        channel="feishu",
        recipient=recipient,
        text="hello",
        reply_ref="om_ref",
    )
    assert reply.reply_ref == "om_ref"


def test_send_result_shapes():
    ok = SendResult(ok=True, external_message_id="om_1")
    assert ok.ok is True
    assert ok.error is None
    failed = SendResult(ok=False, error=ChannelErrorKind.TIMEOUT)
    assert failed.ok is False
    assert failed.error == ChannelErrorKind.TIMEOUT


def test_channel_error_kind_closed_set():
    assert {kind.value for kind in ChannelErrorKind} == {
        "not_found",
        "auth",
        "rate_limited",
        "timeout",
        "server_error",
        "client_error",
        "disabled",
        "invalid_request",
        "unknown",
    }
    assert len(ChannelErrorKind) == 9
    for feishu_code in ("10003", "99991400"):
        assert feishu_code not in {kind.value for kind in ChannelErrorKind}


def test_channel_adapter_protocol_runtime_checkable():
    class _StubAdapter:
        async def send(self, message: OutboundMessage) -> SendResult:
            return SendResult(ok=True)

    class _NotAnAdapter:
        pass

    assert isinstance(_StubAdapter(), ChannelAdapter)
    assert not isinstance(_NotAnAdapter(), ChannelAdapter)


def test_base_py_standard_library_only():
    tree = ast.parse(BASE_PATH.read_text(encoding="utf-8"))
    allowed_roots = {
        "__future__",
        "collections",
        "dataclasses",
        "datetime",
        "enum",
        "typing",
    }
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "base.py 禁止相对导入"
            imported_roots.add((node.module or "").split(".")[0])
    assert imported_roots <= allowed_roots, imported_roots - allowed_roots
    assert not any(root == "app" for root in imported_roots)


def test_package_inits_do_not_import_client():
    for init_path in ("app/channels/__init__.py", "app/channels/feishu/__init__.py"):
        tree = ast.parse(Path(init_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("client" not in alias.name for alias in node.names), init_path
            elif isinstance(node, ast.ImportFrom):
                assert "client" not in (node.module or ""), init_path
