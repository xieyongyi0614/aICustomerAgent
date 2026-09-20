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
from app.channels.feishu.adapter import FALLBACK_TEXTS
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


@pytest.fixture(autouse=True)
def _reenable_app_loggers():
    """防御 `logging.config.fileConfig(disable_existing_loggers=True)` 的跨用例副作用。

    套件内存在进程内执行 alembic 迁移的用例（其 env.py 调用 fileConfig），会把
    已存在的 app.* logger 置为 disabled，导致其后所有日志断言用例捕获为空。
    """
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if (name == "app" or name.startswith("app.")) and isinstance(logger, logging.Logger):
            logger.disabled = False
    yield


def encrypt_payload(key: str, payload: dict) -> str:
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad = 16 - len(plain) % 16
    encryptor = Cipher(
        algorithms.AES(hashlib.sha256(key.encode("utf-8")).digest()), modes.CBC(FIXED_IV)
    ).encryptor()
    return base64.b64encode(
        FIXED_IV + encryptor.update(plain + bytes([pad]) * pad) + encryptor.finalize()
    ).decode()


def _fresh_create_time_ms() -> str:
    return str(int(time.time() * 1000))


def event_payload(event_id="evt-e2e-1", chat_type="p2p", message_type="text", text="你好", open_id="ou_e2e_alice"):
    return {
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": _fresh_create_time_ms(),
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

    monkeypatch.setattr(adapter, "ingest_inbound_message", _spy)
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

    monkeypatch.setattr(adapter, "ingest_inbound_message", _slow_handler)
    started = time.perf_counter()
    response = await post_event(override_settings, payload=event_payload(event_id="evt-slow"))
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < 1.0
    assert await wait_for(lambda: len(entered) == 1, timeout=8.0)


@pytest.mark.asyncio
async def test_rate_limit_per_open_id(override_settings, dispatch_spy, monkeypatch):
    """超限不返回 429：飞书会重投同一 event_id，而该 id 已落去重表，
    重投会被静默吞掉（消息永久丢失）。改为回兜底文案并保持 200。"""
    replies = []

    async def _record(outcome):
        replies.append(outcome)

    monkeypatch.setattr(adapter.delivery, "deliver_reply", _record)
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
    assert limited.status_code == 200
    assert await wait_for(lambda: len(dispatch_spy) == 2)
    assert len(dispatch_spy) == 2
    assert await wait_for(lambda: len(replies) == 1)
    assert [outcome.error_kind for outcome in replies] == ["overloaded"]
    assert replies[0].outbound_text == FALLBACK_TEXTS["overloaded"]
    assert replies[0].source_message_ref == "om_e2e_1"


@pytest.mark.asyncio
async def test_rate_limited_message_is_not_lost_on_retry(override_settings, dispatch_spy, monkeypatch):
    """限流后飞书重投同一 event_id：不得被去重表静默吞掉，用户必须收到兜底文案。"""
    replies = []

    async def _record(outcome):
        replies.append(outcome)

    monkeypatch.setattr(adapter.delivery, "deliver_reply", _record)
    allowed = await post_event(
        override_settings,
        payload=event_payload(event_id="evt-lost-1"),
        chat_rate_limit_per_minute=1,
    )
    assert allowed.status_code == 200
    blocked = await post_event(
        override_settings,
        payload=event_payload(event_id="evt-lost-2"),
        chat_rate_limit_per_minute=1,
    )
    assert blocked.status_code == 200
    retry = await post_event(
        override_settings,
        payload=event_payload(event_id="evt-lost-2"),
        chat_rate_limit_per_minute=1,
    )
    assert retry.status_code == 200

    assert await wait_for(lambda: len(replies) == 1)
    assert [outcome.error_kind for outcome in replies] == ["overloaded"]
    assert replies[0].outbound_text == FALLBACK_TEXTS["overloaded"]
    assert await wait_for(lambda: len(dispatch_spy) == 1)
    assert len(dispatch_spy) == 1


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


def _encrypted_body(inner: dict) -> bytes:
    return serialize({"encrypt": encrypt_payload(ENCRYPT_KEY, inner)})


@pytest.mark.asyncio
async def test_encrypted_event_without_signature_uses_create_time_freshness(
    override_settings, dispatch_spy
):
    """无签名头的加密来件：create_time 新鲜 → 正常受理（修复重放不得误杀正常投递）。"""
    inner = event_payload(event_id="evt-nosig-fresh")
    inner["header"]["create_time"] = _fresh_create_time_ms()
    response = await post_event(
        override_settings, raw=_encrypted_body(inner), feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 200
    assert await wait_for(lambda: len(dispatch_spy) == 1)
    assert dispatch_spy[0].text == "你好"


@pytest.mark.asyncio
async def test_encrypted_replay_with_stale_create_time_403(override_settings, dispatch_spy):
    """F-01：捕获的密文在去重 TTL 之后重放，必须被 create_time 新鲜度拦下。"""
    inner = event_payload(event_id="evt-replay")
    inner["header"]["create_time"] = str(int((time.time() - 3600) * 1000))
    response = await post_event(
        override_settings, raw=_encrypted_body(inner), feishu_encrypt_key=ENCRYPT_KEY
    )
    assert response.status_code == 403
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_encrypted_stale_timestamp_header_403(override_settings, dispatch_spy):
    inner = event_payload(event_id="evt-stale-hdr")
    inner["header"]["create_time"] = _fresh_create_time_ms()
    response = await post_event(
        override_settings,
        raw=_encrypted_body(inner),
        headers={"X-Lark-Request-Timestamp": str(int(time.time()) - 3600)},
        feishu_encrypt_key=ENCRYPT_KEY,
    )
    assert response.status_code == 403
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_plaintext_stale_create_time_403(override_settings, dispatch_spy):
    """明文 + 空 Encrypt Key：验签早退不得连新鲜度校验一起跳过（否则可无限重放）。"""
    payload = event_payload(event_id="evt-plain-replay")
    payload["header"]["create_time"] = str(int((time.time() - 100000) * 1000))
    response = await post_event(override_settings, payload=payload)
    assert response.status_code == 403
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_plaintext_stale_timestamp_header_403(override_settings, dispatch_spy):
    payload = event_payload(event_id="evt-plain-hdr")
    response = await post_event(
        override_settings,
        payload=payload,
        headers={"X-Lark-Request-Timestamp": str(int(time.time()) - 100000)},
    )
    assert response.status_code == 403
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_plaintext_fresh_event_still_accepted(override_settings, dispatch_spy):
    """补上明文新鲜度校验后，正常投递不得被误杀。"""
    response = await post_event(override_settings, payload=event_payload(event_id="evt-plain-ok"))
    assert response.status_code == 200
    assert await wait_for(lambda: len(dispatch_spy) == 1)


@pytest.mark.asyncio
async def test_huge_timestamp_header_does_not_500(override_settings, dispatch_spy):
    """超长时间戳头不得触发未捕获 OverflowError（外部输入直达异常）。"""
    inner = event_payload(event_id="evt-huge-ts")
    inner["header"]["create_time"] = _fresh_create_time_ms()
    response = await post_event(
        override_settings,
        raw=_encrypted_body(inner),
        headers={"X-Lark-Request-Timestamp": "9" * 400},
        feishu_encrypt_key=ENCRYPT_KEY,
    )
    assert response.status_code == 403
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_body_over_limit_413(override_settings, dispatch_spy):
    response = await post_event(
        override_settings,
        raw=serialize(event_payload(event_id="evt-big")),
        feishu_max_body_bytes=16,
    )
    assert response.status_code == 413
    assert dispatch_spy == []


@pytest.mark.asyncio
async def test_duplicate_event_does_not_consume_rate_quota(override_settings, dispatch_spy):
    """F-03：去重前置后，飞书重投的重复事件不再吃掉该用户的限流配额。

    限流阈值设为 3：修复前「重复事件也记账」会累计 4 次调用而使最后一个 429。
    """
    payload = event_payload(event_id="evt-quota-0")
    for _ in range(2):
        response = await post_event(
            override_settings, payload=payload, chat_rate_limit_per_minute=3
        )
        assert response.status_code == 200
    for index in (1, 2):
        response = await post_event(
            override_settings,
            payload=event_payload(event_id=f"evt-quota-{index}"),
            chat_rate_limit_per_minute=3,
        )
        assert response.status_code == 200
    assert await wait_for(lambda: len(dispatch_spy) == 3)
    assert len(dispatch_spy) == 3


@pytest.mark.asyncio
async def test_dispatch_failure_is_logged_not_silent(override_settings, monkeypatch, caplog):
    """F-06：无可调度 loop 时协程被关闭，必须留痕而不是静默吞掉用户消息。"""

    def _refuse(coro):
        coro.close()
        return False

    monkeypatch.setattr(feishu_api.observability, "spawn_background", _refuse)
    with caplog.at_level(logging.ERROR, logger="app.api.v1.feishu"):
        response = await post_event(
            override_settings, payload=event_payload(event_id="evt-noloop")
        )
    assert response.status_code == 200
    assert any(
        "no dispatchable event loop" in record.getMessage() for record in caplog.records
    )
