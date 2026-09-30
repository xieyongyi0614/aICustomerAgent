"""Proactive 出口能力收口（FEISHU-006 §12.2b）：003 建身份 → 005 投递 → 隔离 → 无 Autonomy 参与。"""

import json

import pytest

from app.channels.feishu import client as feishu_client
from app.channels.feishu import delivery
from app.channels.feishu.delivery import send_proactive
from app.repositories import (
    channel_identity_repository,
    conversation_repository,
    memory_repository,
    relationship_repository,
    world_repository,
)
from app.services.identity import channel as channel_identity_service

TOKEN_URL_PART = "tenant_access_token"
APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_pro6",
    "feishu_app_secret": "secret-pro6-value",
    "feishu_verification_token": "vtoken-pro6",
}

TOKEN_BODY = {"code": 0, "msg": "ok", "tenant_access_token": "t-pro6-token", "expire": 7200}
SUCCESS_BODY = {"code": 0, "msg": "ok", "data": {"message_id": "om_pro6_new"}}


class ClosureTransport:
    def __init__(self, responder):
        self.calls = []
        self._responder = responder

    async def post_json(self, url, body, timeout, headers=None):
        self.calls.append({"url": url, "body": dict(body)})
        status, payload = self._responder(url, body)
        return feishu_client.HttpResponse(status=status, json=payload, raw_len=64)


def _im_calls(transport):
    return [c for c in transport.calls if TOKEN_URL_PART not in c["url"]]


def _ok_responder(url, body):
    if TOKEN_URL_PART in url:
        return 200, TOKEN_BODY
    return 200, SUCCESS_BODY


def _error_responder(url, body):
    if TOKEN_URL_PART in url:
        return 200, TOKEN_BODY
    return 500, {"code": 99991400, "msg": "err"}


@pytest.fixture(autouse=True)
def _reset_state(override_settings):
    override_settings(**APP_SETTINGS)
    feishu_client.reset_feishu_client()
    yield
    feishu_client.reset_feishu_client()


def test_closure_identity_table_is_the_source(db_session_factory):
    identity = channel_identity_service.resolve("feishu", "ou_CL_A")
    row = channel_identity_repository.find("feishu", "ou_CL_A")
    assert row is not None
    assert identity.internal_user_id == "feishu:ou_CL_A"
    assert identity.internal_user_id != identity.external_id
    assert identity.external_id == "ou_CL_A"


@pytest.mark.asyncio
async def test_closure_proactive_send_via_resolved_recipient(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_CL_A")
    transport = ClosureTransport(_ok_responder)
    feishu_client.set_transport(transport)
    result = await send_proactive("feishu:ou_CL_A", "在吗？", "k1")
    assert result.ok is True
    im_calls = _im_calls(transport)
    assert len(im_calls) == 1
    assert "receive_id_type=open_id" in im_calls[0]["url"]
    assert im_calls[0]["body"]["receive_id"] == "ou_CL_A"
    assert im_calls[0]["body"]["receive_id"] != "feishu:ou_CL_A"


@pytest.mark.asyncio
async def test_closure_proactive_unknown_user_zero_request(db_session_factory):
    transport = ClosureTransport(_ok_responder)
    feishu_client.set_transport(transport)
    result = await send_proactive("feishu:ou_ghost_cl", "hi", "k1")
    assert result.ok is False
    assert result.error.value == "not_found"
    assert _im_calls(transport) == []


@pytest.mark.asyncio
async def test_closure_proactive_missing_key_rejected(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_CL_K")
    transport = ClosureTransport(_ok_responder)
    feishu_client.set_transport(transport)
    result = await send_proactive("feishu:ou_CL_K", "hi", "")
    assert result.ok is False
    assert result.error.value == "invalid_request"
    assert _im_calls(transport) == []


@pytest.mark.asyncio
async def test_closure_proactive_idempotent_and_multi_user(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_CL_M1")
    channel_identity_service.resolve("feishu", "ou_CL_M2")
    transport = ClosureTransport(_ok_responder)
    feishu_client.set_transport(transport)

    await send_proactive("feishu:ou_CL_M1", "一", "k1")
    await send_proactive("feishu:ou_CL_M1", "一", "k1")
    await send_proactive("feishu:ou_CL_M1", "二", "k2")
    await send_proactive("feishu:ou_CL_M2", "给 M2", "k1")
    im_calls = _im_calls(transport)
    assert len(im_calls) == 3
    assert [c["body"]["receive_id"] for c in im_calls] == [
        "ou_CL_M1",
        "ou_CL_M1",
        "ou_CL_M2",
    ]


@pytest.mark.asyncio
async def test_closure_proactive_pure_outbound_zero_db_writes(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_CL_W")
    transport = ClosureTransport(_error_responder)
    feishu_client.set_transport(transport)
    before_memories = len(memory_repository.list_by_user("feishu:ou_CL_W"))
    result = await send_proactive("feishu:ou_CL_W", "hi", "k1")
    assert result.ok is False
    assert conversation_repository.get_latest_for_user("feishu:ou_CL_W") is None
    assert len(memory_repository.list_by_user("feishu:ou_CL_W")) == before_memories == 0
    assert world_repository.get_world("feishu:ou_CL_W") is None
    assert (
        channel_identity_repository.list_by_internal_user("feishu:ou_CL_W")[0].external_id
        == "ou_CL_W"
    )


@pytest.mark.asyncio
async def test_closure_no_autonomy_modules_in_outbound_import_graph():
    import ast
    from pathlib import Path

    banned = ("autonomy", "life_loop", "scheduler", "proactive_executor", "trigger_evaluator")
    for rel in ("channels/feishu/delivery.py", "channels/feishu/outbound.py", "channels/feishu/client.py", "channels/base.py"):
        path = Path("app") / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                lowered = module.lower()
                assert not any(banned in lowered for banned in banned), (
                    f"{path}:{node.lineno} 出站路径违规 import: {module}"
                )
