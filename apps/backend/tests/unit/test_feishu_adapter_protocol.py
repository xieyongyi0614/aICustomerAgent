import ast
import inspect
from pathlib import Path

import pytest

from app.channels.base import (
    ChannelAdapter,
    ChannelErrorKind,
    OutboundMessage,
    RecipientRef,
    SendResult,
)
from app.channels.feishu import client as feishu_client
from app.channels.feishu.delivery import FeishuChannelAdapter

DELIVERY_PATH = Path("app/channels/feishu/delivery.py")


def _message(reply_ref="om_x", key=None):
    return OutboundMessage(
        channel="feishu",
        recipient=RecipientRef(channel="feishu", external_id="ou_a"),
        text="hi",
        reply_ref=reply_ref,
        idempotency_key=key,
    )


def test_adapter_satisfies_channel_adapter_protocol():
    assert isinstance(FeishuChannelAdapter(), ChannelAdapter)


def test_send_signature_matches_protocol():
    protocol_params = [
        name
        for name in inspect.signature(ChannelAdapter.send).parameters
        if name != "self"
    ]
    adapter_params = [
        name
        for name in inspect.signature(FeishuChannelAdapter.send).parameters
        if name != "self"
    ]
    assert adapter_params == protocol_params == ["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: RuntimeError("boom"),
        lambda: ValueError("bad"),
        lambda: KeyError("k"),
        lambda: OSError("io"),
        lambda: TimeoutError(),
    ],
)
async def test_send_never_raises(monkeypatch, exc_factory):
    async def _exploding_token():
        raise exc_factory()

    monkeypatch.setattr(feishu_client, "get_tenant_access_token", _exploding_token)
    result = await FeishuChannelAdapter().send(_message())
    assert isinstance(result, SendResult)
    assert result.ok is False
    assert result.error == ChannelErrorKind.UNKNOWN


@pytest.mark.asyncio
async def test_send_proactive_path_never_raises(monkeypatch):
    async def _exploding_token():
        raise RuntimeError("boom")

    monkeypatch.setattr(feishu_client, "get_tenant_access_token", _exploding_token)
    result = await FeishuChannelAdapter().send(_message(reply_ref=None, key="k1"))
    assert isinstance(result, SendResult)
    assert result.ok is False


def test_delivery_module_import_boundary():
    banned_prefixes = (
        "app.repositories",
        "app.services.memory",
        "app.services.world",
        "app.services.state",
        "app.services.relationship",
        "app.chains",
        "app.application",
    )
    banned_substrings = ("autonomy", "life_loop", "scheduler", "proactive_policy")
    tree = ast.parse(DELIVERY_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        for module in modules:
            lowered = module.lower()
            assert not any(module.startswith(prefix) for prefix in banned_prefixes), module
            assert not any(banned in lowered for banned in banned_substrings), module
