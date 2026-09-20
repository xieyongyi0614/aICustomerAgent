import json

import pytest

from app.channels.feishu import client as feishu_client
from app.channels.feishu.delivery import (
    send_proactive,
)
from app.repositories import conversation_repository, memory_repository
from app.services import channel_identity_service

TOKEN_URL_PART = "tenant_access_token"
APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_pro",
    "feishu_app_secret": "secret-pro-value",
    "feishu_verification_token": "vtoken-pro",
}

TOKEN_BODY = {"code": 0, "msg": "ok", "tenant_access_token": "t-pro-token", "expire": 7200}
SUCCESS_BODY = {"code": 0, "msg": "ok", "data": {"message_id": "om_pro_new"}}


class ProTransport:
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


@pytest.mark.asyncio
async def test_proactive_resolves_identity_and_sends(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_A")
    transport = ProTransport(_ok_responder)
    feishu_client.set_transport(transport)
    result = await send_proactive("feishu:ou_A", "在吗？", "k1")
    assert result.ok is True
    im_calls = _im_calls(transport)
    assert len(im_calls) == 1
    assert "receive_id_type=open_id" in im_calls[0]["url"]
    assert im_calls[0]["body"]["receive_id"] == "ou_A"
    assert im_calls[0]["body"]["msg_type"] == "text"
    assert im_calls[0]["body"]["content"] == json.dumps({"text": "在吗？"}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_proactive_open_id_differs_from_internal_user_id(db_session_factory):
    identity = channel_identity_service.resolve("feishu", "ou_XYZ")
    transport = ProTransport(_ok_responder)
    feishu_client.set_transport(transport)
    await send_proactive(identity.internal_user_id, "hi", "kX")
    im_calls = _im_calls(transport)
    assert identity.internal_user_id == "feishu:ou_XYZ"
    assert identity.internal_user_id != identity.external_id
    assert im_calls[0]["body"]["receive_id"] == "ou_XYZ"


@pytest.mark.asyncio
async def test_proactive_unknown_user_no_request_no_guess(db_session_factory):
    transport = ProTransport(_ok_responder)
    feishu_client.set_transport(transport)
    result = await send_proactive("feishu:ou_ghost", "hi", "k1")
    assert result.ok is False
    assert result.error.value == "not_found"
    assert _im_calls(transport) == []


@pytest.mark.asyncio
async def test_proactive_missing_idempotency_key_rejected(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_K")
    transport = ProTransport(_ok_responder)
    feishu_client.set_transport(transport)
    for key in (None, "", "   "):
        result = await send_proactive("feishu:ou_K", "hi", key)
        assert result.ok is False
        assert result.error.value == "invalid_request"
    assert _im_calls(transport) == []


@pytest.mark.asyncio
async def test_proactive_idempotent_same_key_single_request(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_idem")
    transport = ProTransport(_ok_responder)
    feishu_client.set_transport(transport)
    await send_proactive("feishu:ou_idem", "第一条", "k1")
    await send_proactive("feishu:ou_idem", "第一条", "k1")
    assert len(_im_calls(transport)) == 1


@pytest.mark.asyncio
async def test_proactive_different_keys_both_sent(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_keys")
    transport = ProTransport(_ok_responder)
    feishu_client.set_transport(transport)
    await send_proactive("feishu:ou_keys", "一", "k1")
    await send_proactive("feishu:ou_keys", "二", "k2")
    assert len(_im_calls(transport)) == 2


@pytest.mark.asyncio
async def test_proactive_retry_exhausts_without_raising(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_retry")
    transport = ProTransport(_error_responder)
    feishu_client.set_transport(transport)
    result = await send_proactive("feishu:ou_retry", "hi", "k1")
    assert result.ok is False
    assert len(_im_calls(transport)) == 3


@pytest.mark.asyncio
async def test_proactive_failure_touches_nothing(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_iso")
    transport = ProTransport(_error_responder)
    feishu_client.set_transport(transport)
    before_conversations = (
        conversation_repository.get_latest_for_user("feishu:ou_iso") is not None
    )
    before_memories = len(memory_repository.list_by_user("feishu:ou_iso"))
    await send_proactive("feishu:ou_iso", "hi", "k1")
    assert (
        conversation_repository.get_latest_for_user("feishu:ou_iso") is not None
    ) == before_conversations
    assert len(memory_repository.list_by_user("feishu:ou_iso")) == before_memories == 0


@pytest.mark.asyncio
async def test_proactive_multi_users_no_cross_talk(db_session_factory):
    channel_identity_service.resolve("feishu", "ou_MA")
    channel_identity_service.resolve("feishu", "ou_MB")
    transport = ProTransport(_ok_responder)
    feishu_client.set_transport(transport)
    await send_proactive("feishu:ou_MA", "给A", "kA")
    await send_proactive("feishu:ou_MB", "给B", "kB")
    im_calls = _im_calls(transport)
    assert [call["body"]["receive_id"] for call in im_calls] == ["ou_MA", "ou_MB"]
    assert [json.loads(call["body"]["content"])["text"] for call in im_calls] == ["给A", "给B"]
