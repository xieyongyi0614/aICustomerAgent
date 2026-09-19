import base64
import hashlib
import json
import logging
import time

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from httpx import ASGITransport, AsyncClient

from app.api.v1 import feishu as feishu_api
from app.channels.feishu import adapter, events
from app.main import app

URL = "/api/v1/feishu/events"
VERIFICATION_TOKEN = "vtoken-e2e-123"
ENCRYPT_KEY = "feishu-e2e-encrypt-key"
APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_e2e",
    "feishu_app_secret": "secret-e2e-value",
    "feishu_verification_token": VERIFICATION_TOKEN,
    "feishu_encrypt_key": "",
}

FIXED_IV = bytes(range(16))


@pytest.fixture(autouse=True)
def _reset_feishu_state():
    events.reset_event_state()
    adapter.reset_feishu_adapter()
    yield
    events.reset_event_state()
    adapter.reset_feishu_adapter()


def encrypt_payload(key: str, payload: dict) -> str:
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad = 16 - len(plain) % 16
    encryptor = Cipher(
        algorithms.AES(hashlib.sha256(key.encode("utf-8")).digest()), modes.CBC(FIXED_IV)
    ).encryptor()
    return base64.b64encode(
        FIXED_IV + encryptor.update(plain + bytes([pad]) * pad) + encryptor.finalize()
    ).decode()


def event_payload(event_id="evt-e2e-1", chat_type="p2p", message_type="text", text="你好", open_id="ou_e2e_alice"):
    return {
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": "1767196800000",
            "tenant_key": "tk_e2e",
            "app_id": "cli_e2e",
            "token": VERIFICATION_TOKEN,
        },
        "event": {
            "sender": {"sender_id": {"open_id": open_id, "union_id": "un_e2e", "user_id": "uid_e2e"}},
            "message": {
                "message_id": "om_e2e_1",
                "chat_id": "oc_e2e_1",
                "chat_type": chat_type,
                "message_type": message_type,
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        },
    }


def serialize(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def signature_headers(body: bytes, key: str = ENCRYPT_KEY, timestamp=None, nonce="nonce-e2e") -> dict:
    timestamp = timestamp or str(int(time.time()))
    return {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": events.calculate_signature(timestamp, nonce, key, body),
    }


@pytest.fixture
def dispatch_spy(monkeypatch):
    calls = []

    async def _spy(inbound):
        calls.append(inbound)

    monkeypatch.setattr(adapter, "handle_inbound_message", _spy)
    return calls


async def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        import asyncio

        await asyncio.sleep(0.02)
    return predicate()


async def post_event(override_settings=None, *, payload=None, raw=None, headers=None, **settings):
    applied = {**APP_SETTINGS, **(settings or {})}
    if override_settings is not None:
        override_settings(**applied)
    body = raw if raw is not None else serialize(payload or event_payload())
    send_headers = {"Content-Type": "application/json"}
    if headers:
        send_headers.update(headers)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(URL, content=body, headers=send_headers)


@pytest.mark.asyncio
async def test_disabled_returns_404(override_settings, dispatch_spy):
    response = await post_event(override_settings, payload=event_payload(), feishu_enabled=False)
    assert response.status_code == 404
    assert dispatch_spy == []
    assert events._seen_events == {}


@pytest.mark.asyncio
async def test_challenge_echoed_verbatim(override_settings, dispatch_spy):
    payload = {"type": "url_verification", "token": VERIFICATION_TOKEN, "challenge": "ajls384kdd/+=?"}
    response = await post_event(override_settings, payload=payload)
    assert response.status_code == 200
    assert response.json() == {"challenge": "ajls384kdd/+=?"}
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_challenge_missing_field_returns_400(override_settings, dispatch_spy):
    payload = {"type": "url_verification", "token": VERIFICATION_TOKEN}
    response = await post_event(override_settings, payload=payload)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_valid_event_dispatches_once(override_settings, dispatch_spy):
    response = await post_event(override_settings, payload=event_payload())
    assert response.status_code == 200
    assert response.json() == {}
    assert await wait_for(lambda: len(dispatch_spy) == 1)
    inbound = dispatch_spy[0]
    assert inbound.external_user_id == "ou_e2e_alice"
    assert inbound.reply_ref == "om_e2e_1"
    assert inbound.external_thread_id == "oc_e2e_1"
    assert inbound.text == "你好"


@pytest.mark.asyncio
async def test_wrong_token_401_and_no_dispatch(override_settings, dispatch_spy):
    payload = event_payload()
    payload["header"]["token"] = "forged-token"
    response = await post_event(override_settings, payload=payload)
    assert response.status_code == 401
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_missing_token_401(override_settings, dispatch_spy):
    payload = event_payload()
    del payload["header"]["token"]
    response = await post_event(override_settings, payload=payload)
    assert response.status_code == 401
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_wrong_signature_403_and_no_dispatch(override_settings, dispatch_spy):
    payload = {"encrypt": encrypt_payload(ENCRYPT_KEY, event_payload())}
    body = serialize(payload)
    headers = signature_headers(body)
    headers["X-Lark-Signature"] = "0" * 64
    response = await post_event(
        override_settings, raw=body, headers=headers, feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 403
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_expired_timestamp_403(override_settings, dispatch_spy):
    payload = {"encrypt": encrypt_payload(ENCRYPT_KEY, event_payload())}
    body = serialize(payload)
    stale_timestamp = str(int(time.time()) - 301)
    headers = signature_headers(body, timestamp=stale_timestamp)
    response = await post_event(
        override_settings, raw=body, headers=headers, feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 403
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_encrypted_event_end_to_end(override_settings, dispatch_spy):
    payload = {"encrypt": encrypt_payload(ENCRYPT_KEY, event_payload(event_id="evt-enc-1"))}
    body = serialize(payload)
    response = await post_event(
        override_settings, raw=body, headers=signature_headers(body), feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 200
    assert await wait_for(lambda: len(dispatch_spy) == 1)
    assert dispatch_spy[0].text == "你好"
    assert dispatch_spy[0].external_user_id == "ou_e2e_alice"


@pytest.mark.asyncio
async def test_encrypted_challenge_end_to_end(override_settings, dispatch_spy):
    inner = {"type": "url_verification", "token": VERIFICATION_TOKEN, "challenge": "enc-ch-1"}
    payload = {"encrypt": encrypt_payload(ENCRYPT_KEY, inner)}
    body = serialize(payload)
    response = await post_event(
        override_settings, raw=body, headers=signature_headers(body), feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "enc-ch-1"}


@pytest.mark.asyncio
async def test_encrypted_challenge_without_signature_headers_200(override_settings, dispatch_spy):
    """URL 校验请求可能不带签名头：解密成功即验真，challenge 照常回显。"""
    inner = {"type": "url_verification", "token": VERIFICATION_TOKEN, "challenge": "enc-ch-2"}
    payload = {"encrypt": encrypt_payload(ENCRYPT_KEY, inner)}
    body = serialize(payload)
    response = await post_event(
        override_settings, raw=body, feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "enc-ch-2"}
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_unencrypted_event_end_to_end(override_settings, dispatch_spy):
    payload = event_payload(event_id="evt-plain-1")
    body = serialize(payload)
    response = await post_event(
        override_settings,
        raw=body,
        headers=signature_headers(body),
        feishu_encrypt_key=ENCRYPT_KEY,
    )
    assert response.status_code == 200
    assert await wait_for(lambda: len(dispatch_spy) == 1)


@pytest.mark.asyncio
async def test_encrypted_wrong_key_400_no_dispatch(override_settings, dispatch_spy):
    payload = {"encrypt": encrypt_payload("other-key", event_payload())}
    body = serialize(payload)
    response = await post_event(
        override_settings, raw=body, headers=signature_headers(body), feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 400
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_encrypt_key_empty_with_ciphertext_400(override_settings, dispatch_spy):
    payload = {"encrypt": encrypt_payload(ENCRYPT_KEY, event_payload())}
    body = serialize(payload)
    response = await post_event(override_settings, raw=body, headers=signature_headers(body))
    assert response.status_code == 400
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_decryptable_but_malformed_inner_200_no_dispatch(override_settings, dispatch_spy):
    payload = {"encrypt": encrypt_payload(ENCRYPT_KEY, {"surprise": True})}
    body = serialize(payload)
    response = await post_event(
        override_settings, raw=body, headers=signature_headers(body), feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 200
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_non_json_body_400(override_settings, dispatch_spy):
    response = await post_event(override_settings, raw=b"this is not json")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_missing_event_header_400(override_settings, dispatch_spy):
    response = await post_event(
        override_settings, payload={"token": VERIFICATION_TOKEN, "event": {}}
    )
    assert response.status_code == 400
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_missing_both_token_and_header_401(override_settings, dispatch_spy):
    response = await post_event(override_settings, payload={"event": {}})
    assert response.status_code == 401
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_duplicate_event_dispatched_once(override_settings, dispatch_spy):
    payload = event_payload(event_id="evt-dup-e2e")
    first = await post_event(override_settings, payload=payload)
    second = await post_event(override_settings, payload=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert await wait_for(lambda: len(dispatch_spy) == 1)
    await wait_for(lambda: len(dispatch_spy) > 1, timeout=0.3)
    assert len(dispatch_spy) == 1


@pytest.mark.asyncio
async def test_group_message_ignored(override_settings, dispatch_spy):
    response = await post_event(
        override_settings, payload=event_payload(event_id="evt-group", chat_type="group")
    )
    assert response.status_code == 200
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_image_message_ignored(override_settings, dispatch_spy):
    response = await post_event(
        override_settings, payload=event_payload(event_id="evt-image", message_type="image")
    )
    assert response.status_code == 200
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_ack_not_blocked_by_slow_handler(override_settings, monkeypatch):
    entered = []

    async def _slow_handler(inbound):
        entered.append(inbound)
        import asyncio

        await asyncio.sleep(3.0)

    monkeypatch.setattr(adapter, "handle_inbound_message", _slow_handler)
    started = time.perf_counter()
    response = await post_event(override_settings, payload=event_payload(event_id="evt-slow"))
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < 1.0
    assert await wait_for(lambda: len(entered) == 1, timeout=8.0)


@pytest.mark.asyncio
async def test_rate_limit_per_open_id(override_settings, dispatch_spy):
    for index in range(2):
        response = await post_event(
            override_settings,
            payload=event_payload(event_id=f"evt-rate-{index}"),
            chat_rate_limit_per_minute=2,
        )
        assert response.status_code == 200
    limited = await post_event(
        override_settings,
        payload=event_payload(event_id="evt-rate-2"),
        chat_rate_limit_per_minute=2,
    )
    assert limited.status_code == 429
    assert await wait_for(lambda: len(dispatch_spy) == 2)
    assert len(dispatch_spy) == 2


@pytest.mark.asyncio
async def test_no_secrets_in_rejection_logs(override_settings, dispatch_spy, caplog):
    payload = {"encrypt": "definitely-not-valid-base64!!!"}
    body = serialize(payload)
    with caplog.at_level(logging.INFO):
        response = await post_event(
            override_settings, raw=body, headers=signature_headers(body), feishu_encrypt_key=ENCRYPT_KEY
        )
    assert response.status_code == 400
    text = caplog.text + response.text
    for secret in (ENCRYPT_KEY, APP_SETTINGS["feishu_app_secret"], VERIFICATION_TOKEN):
        assert secret not in text
