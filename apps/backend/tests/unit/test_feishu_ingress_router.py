"""C2 轻量 router：分片选择、原样转发与失败语义（FEISHU-011 方案 C2）。"""

import base64
import hashlib
import json
import os

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from httpx import ASGITransport, AsyncClient

from app.api.v1.feishu import ingress as feishu_ingress
from app.main import app

URL = "/api/v1/feishu/ingress/events"
DOWNSTREAM = "/api/v1/feishu/events"

ROUTER_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_router",
    "feishu_app_secret": "secret-router-value",
    "feishu_verification_token": "vtoken-router",
    "feishu_router_enabled": True,
    "feishu_instance_count": 2,
    "feishu_router_instance_urls": "http://i0.test,http://i1.test",
    "feishu_dedupe_persistent_enabled": True,
}

# ou_e2e_alice 在 2 片下归属 shard 1（golden 值见 test_feishu_shards.py）
OPEN_ID_SHARD_1 = "ou_e2e_alice"
OPEN_ID_SHARD_0 = "ou_B_iso"


def body_for(open_id: str | None, *, token: str = "vtoken-router") -> bytes:
    payload: dict = {
        "header": {
            "event_id": "evt-router-1",
            "event_type": "im.message.receive_v1",
            "token": token,
        },
        "event": {
            "message": {
                "message_id": "om_router_1",
                "chat_id": "oc_router_1",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": "hi"}),
            }
        },
    }
    if open_id is not None:
        payload["event"]["sender"] = {"sender_id": {"open_id": open_id}}
    return json.dumps(payload).encode()


def encrypt_payload(key: str, payload: dict) -> str:
    """与飞书一致：`base64(iv + AES-256-CBC(pkcs7(plain)))`，密钥 = sha256(encrypt_key)。"""
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad = 16 - len(plain) % 16
    iv = os.urandom(16)
    encryptor = Cipher(
        algorithms.AES(hashlib.sha256(key.encode("utf-8")).digest()), modes.CBC(iv)
    ).encryptor()
    ciphertext = encryptor.update(plain + bytes([pad]) * pad) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode()


@pytest.fixture
def forward_spy(monkeypatch):
    calls: list[dict] = []

    def _fake(url, raw, headers, timeout):
        calls.append({"url": url, "raw": raw, "headers": headers, "timeout": timeout})
        return 200, b'{"ok":true}'

    monkeypatch.setattr(feishu_ingress, "_forward", _fake)
    return calls


async def post(raw: bytes, headers: dict | None = None):
    send_headers = {"Content-Type": "application/json"}
    if headers:
        send_headers.update(headers)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(URL, content=raw, headers=send_headers)


@pytest.mark.asyncio
async def test_router_disabled_returns_404(override_settings, forward_spy):
    response = await post(body_for(OPEN_ID_SHARD_1))
    override_settings(**{**ROUTER_SETTINGS, "feishu_router_enabled": False})
    assert response.status_code == 404
    assert forward_spy == []


@pytest.mark.asyncio
async def test_routes_to_shard_of_open_id(override_settings, forward_spy):
    override_settings(**ROUTER_SETTINGS)
    response = await post(body_for(OPEN_ID_SHARD_1))
    assert response.status_code == 200
    assert [call["url"] for call in forward_spy] == [f"http://i1.test{DOWNSTREAM}"]


@pytest.mark.asyncio
async def test_routes_shard_zero_open_id(override_settings, forward_spy):
    override_settings(**ROUTER_SETTINGS)
    await post(body_for(OPEN_ID_SHARD_0))
    assert [call["url"] for call in forward_spy] == [f"http://i0.test{DOWNSTREAM}"]


@pytest.mark.asyncio
async def test_forwards_original_body_and_signature_headers(override_settings, forward_spy):
    """必须转发**原始 body**：飞书签名覆盖的是密文 body，转发明文会让下游验签失败。"""
    override_settings(**ROUTER_SETTINGS)
    raw = body_for(OPEN_ID_SHARD_1)
    await post(
        raw,
        headers={
            "X-Lark-Request-Timestamp": "1767196800",
            "X-Lark-Request-Nonce": "nonce-1",
            "X-Lark-Signature": "sig-abc",
            "X-Not-Forwarded": "should-not-pass",
        },
    )
    call = forward_spy[0]
    assert call["raw"] == raw
    assert call["headers"]["x-lark-request-timestamp"] == "1767196800"
    assert call["headers"]["x-lark-request-nonce"] == "nonce-1"
    assert call["headers"]["x-lark-signature"] == "sig-abc"
    assert "x-not-forwarded" not in call["headers"]


@pytest.mark.asyncio
async def test_router_does_not_authenticate(override_settings, forward_spy):
    """router 不做鉴权决策：token 错也照转，由下游拒绝（安全闸只有一处）。"""
    override_settings(**ROUTER_SETTINGS)
    response = await post(body_for(OPEN_ID_SHARD_1, token="wrong-token"))
    assert response.status_code == 200
    assert len(forward_spy) == 1


@pytest.mark.asyncio
async def test_request_without_open_id_goes_to_shard_zero(override_settings, forward_spy):
    """challenge / 结构非法：与用户无关，固定 shard 0（任何实例都能应答或拒绝）。"""
    override_settings(**ROUTER_SETTINGS)
    challenge = json.dumps(
        {"type": "url_verification", "token": "vtoken-router", "challenge": "c-1"}
    ).encode()
    response = await post(challenge)
    assert response.status_code == 200
    assert [call["url"] for call in forward_spy] == [f"http://i0.test{DOWNSTREAM}"]


@pytest.mark.asyncio
async def test_encrypted_body_without_key_goes_to_shard_zero(override_settings, forward_spy):
    """无 Encrypt Key 无法解密 → 取不到 open_id → shard 0（下游会自行处理）。"""
    override_settings(**ROUTER_SETTINGS)
    raw = json.dumps({"encrypt": "P37w+VZImNgPEO1RBhJ6RtKl7n6zymIbEG1pReEzghk="}).encode()
    await post(raw)
    assert [call["url"] for call in forward_spy] == [f"http://i0.test{DOWNSTREAM}"]


@pytest.mark.asyncio
async def test_undecryptable_ciphertext_goes_to_shard_zero(override_settings, forward_spy):
    override_settings(**{**ROUTER_SETTINGS, "feishu_encrypt_key": "test key"})
    raw = json.dumps({"encrypt": "not-a-valid-ciphertext"}).encode()
    await post(raw)
    assert [call["url"] for call in forward_spy] == [f"http://i0.test{DOWNSTREAM}"]


@pytest.mark.asyncio
async def test_encrypted_body_routes_by_decrypted_open_id(override_settings, forward_spy):
    """加密体必须解密后才能分流——外层只有 `encrypt`，无任何明文标识。"""
    override_settings(**{**ROUTER_SETTINGS, "feishu_encrypt_key": "test key"})
    inner = json.loads(body_for(OPEN_ID_SHARD_1))
    raw = json.dumps({"encrypt": encrypt_payload("test key", inner)}).encode()
    await post(raw)
    assert [call["url"] for call in forward_spy] == [f"http://i1.test{DOWNSTREAM}"]


@pytest.mark.asyncio
async def test_body_over_limit_returns_413(override_settings, forward_spy):
    override_settings(**{**ROUTER_SETTINGS, "feishu_max_body_bytes": 64})
    response = await post(body_for(OPEN_ID_SHARD_1))
    assert response.status_code == 413
    assert forward_spy == []


@pytest.mark.asyncio
async def test_downstream_response_returned_verbatim(override_settings, monkeypatch):
    override_settings(**ROUTER_SETTINGS)
    monkeypatch.setattr(
        feishu_ingress, "_forward", lambda url, raw, headers, timeout: (403, b'{"detail":"nope"}')
    )
    response = await post(body_for(OPEN_ID_SHARD_1))
    assert response.status_code == 403
    assert response.json() == {"detail": "nope"}


@pytest.mark.asyncio
async def test_transport_failure_returns_503_without_failover(override_settings, monkeypatch):
    """目标不可达 → 503，**不得自行改投其他实例**（改投会破坏同会话串行）。"""
    override_settings(**ROUTER_SETTINGS)
    calls: list[str] = []

    def _boom(url, raw, headers, timeout):
        calls.append(url)
        raise OSError("connection refused")

    monkeypatch.setattr(feishu_ingress, "_forward", _boom)
    response = await post(body_for(OPEN_ID_SHARD_1))
    assert response.status_code == 503
    assert calls == [f"http://i1.test{DOWNSTREAM}"]


@pytest.mark.asyncio
async def test_router_enabled_satisfies_multi_instance_contract(override_settings, forward_spy):
    """`FEISHU_ROUTER_ENABLED` 本身即是「ingress 已分流」的声明，无需再开另一个开关。"""
    override_settings(**ROUTER_SETTINGS)
    await post(body_for(OPEN_ID_SHARD_1))
    assert len(forward_spy) == 1


def test_extract_open_id_handles_non_dict_json():
    assert feishu_ingress.extract_open_id(b"[1,2,3]", "") is None
    assert feishu_ingress.extract_open_id(b"not json", "") is None
    assert feishu_ingress.extract_open_id(b'{"event":{}}', "") is None
    assert feishu_ingress.extract_open_id(b'{"event":{"sender":{}}}', "") is None
    assert (
        feishu_ingress.extract_open_id(b'{"event":{"sender":{"sender_id":{}}}}', "") is None
    )
