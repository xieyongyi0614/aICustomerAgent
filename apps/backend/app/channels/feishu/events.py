"""飞书事件纯函数：解密 / 验签 / challenge / 解析过滤 / 去重 / 限流（FEISHU-002）。

协议依据飞书官方文档「接收事件」（encrypt-key-encryption-configuration-case，已复核）：
- 签名 = sha256(timestamp + nonce + encrypt_key + 原始 body).hexdigest()，header
  `X-Lark-Request-Timestamp` / `X-Lark-Request-Nonce` / `X-Lark-Signature`；
- 解密 = base64 解码 → 前 16 字节为 IV → AES-256-CBC(key=sha256(encrypt_key)) →
  PKCS#7 去填充，明文即事件 JSON（官方示例向量实测无 16 字节随机前缀）。
"""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.channels.base import InboundMessage
from app.channels.feishu.errors import FeishuAuthError, FeishuConfigError
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

CHANNEL_NAME = "feishu"
MESSAGE_EVENT_TYPE = "im.message.receive_v1"
CHALLENGE_TYPE = "url_verification"
RATE_WINDOW_SECONDS = 60.0
AES_BLOCK_SIZE = 16

_now = time.time
_seen_events: dict[str, float] = {}
_seen_lock = threading.Lock()
_rate_windows: dict[str, deque[float]] = {}
_rate_lock = threading.Lock()


def decrypt_bytes(encrypt_key: str, ciphertext_b64: str) -> bytes:
    if not encrypt_key:
        raise FeishuConfigError("decrypt", detail="encrypt key not configured")
    try:
        raw = base64.b64decode(ciphertext_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise FeishuConfigError("decrypt", detail="ciphertext is not valid base64") from exc
    if len(raw) < 2 * AES_BLOCK_SIZE or (len(raw) - AES_BLOCK_SIZE) % AES_BLOCK_SIZE:
        raise FeishuConfigError("decrypt", detail="ciphertext length invalid")
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    decryptor = Cipher(algorithms.AES(key), modes.CBC(raw[:AES_BLOCK_SIZE])).decryptor()
    padded = decryptor.update(raw[AES_BLOCK_SIZE:]) + decryptor.finalize()
    pad = padded[-1]
    if pad < 1 or pad > AES_BLOCK_SIZE or padded[-pad:] != bytes([pad]) * pad:
        raise FeishuConfigError("decrypt", detail="invalid pkcs7 padding")
    return padded[:-pad]


def decrypt(encrypt_key: str, ciphertext_b64: str) -> dict:
    plain = decrypt_bytes(encrypt_key, ciphertext_b64)
    try:
        payload = json.loads(plain.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FeishuConfigError("decrypt", detail="decrypted payload is not valid json") from exc
    if not isinstance(payload, dict):
        raise FeishuConfigError("decrypt", detail="decrypted payload is not an object")
    return payload


def verify_token(header_token: str | None, expected: str) -> None:
    if (
        not expected
        or not header_token
        or not hmac.compare_digest(header_token.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise FeishuAuthError("verify_token", detail="verification token mismatch")


def verify_signature(
    raw: bytes,
    timestamp: str | None,
    nonce: str | None,
    encrypt_key: str,
    signature: str | None,
) -> None:
    if not encrypt_key:
        if not signature:
            logger.warning(
                "FEISHU_ENCRYPT_KEY 为空: 无法校验请求签名，安全性降级"
            )
        return
    if not signature:
        raise FeishuAuthError("verify_signature", detail="signature header missing")
    timestamp_value = _timestamp_value(timestamp)
    if timestamp_value is None:
        raise FeishuAuthError("verify_signature", detail="request timestamp invalid")
    if abs(_now() - timestamp_value) > get_settings().feishu_signature_window_seconds:
        raise FeishuAuthError("verify_signature", detail="request timestamp out of window")
    expected = calculate_signature(timestamp or "", nonce or "", encrypt_key, raw)
    if not hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8")):
        raise FeishuAuthError("verify_signature", detail="signature mismatch")


def calculate_signature(timestamp: str, nonce: str, encrypt_key: str, raw: bytes) -> str:
    material = (timestamp + nonce + encrypt_key).encode("utf-8") + raw
    return hashlib.sha256(material).hexdigest()


def _timestamp_value(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        return float(int(timestamp))
    except ValueError:
        return None


def is_challenge(payload: dict) -> bool:
    return payload.get("type") == CHALLENGE_TYPE


def challenge_of(payload: dict) -> str | None:
    challenge = payload.get("challenge")
    if not isinstance(challenge, str) or not challenge:
        return None
    return challenge


@dataclass(frozen=True, slots=True)
class ParsedMessageEvent:
    event_id: str
    event_type: str
    message_id: str
    chat_id: str
    chat_type: str
    message_type: str
    text: str
    open_id: str
    create_time_ms: str | None = None
    tenant_key: str | None = None
    app_id: str | None = None
    union_id: str | None = None
    user_id: str | None = None


def parse_message_event(payload: dict) -> ParsedMessageEvent | None:
    if not isinstance(payload, dict):
        return None
    header = payload.get("header")
    event = payload.get("event")
    if not isinstance(header, dict) or not isinstance(event, dict):
        return None
    event_id = header.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        logger.warning("feishu event ignored: event_id missing")
        return None
    event_type = header.get("event_type")
    if event_type != MESSAGE_EVENT_TYPE:
        logger.info("feishu event ignored: event_type=%s", event_type)
        return None
    message = event.get("message")
    sender = event.get("sender")
    if not isinstance(message, dict) or not isinstance(sender, dict):
        logger.info("feishu event ignored: message/sender malformed")
        return None
    chat_type = message.get("chat_type")
    if chat_type != "p2p":
        logger.info("feishu event ignored: chat_type=%s", chat_type)
        return None
    message_type = message.get("message_type")
    if message_type != "text":
        logger.info("feishu event ignored: message_type=%s", message_type)
        return None
    text = _extract_text(message.get("content"))
    if not text:
        logger.info("feishu event ignored: text content empty or invalid")
        return None
    sender_id = sender.get("sender_id")
    if not isinstance(sender_id, dict):
        logger.info("feishu event ignored: sender_id malformed")
        return None
    open_id = sender_id.get("open_id")
    if not isinstance(open_id, str) or not open_id:
        logger.info("feishu event ignored: open_id missing")
        return None
    message_id = message.get("message_id")
    chat_id = message.get("chat_id")
    if not isinstance(message_id, str) or not message_id:
        logger.info("feishu event ignored: message_id missing")
        return None
    if not isinstance(chat_id, str) or not chat_id:
        logger.info("feishu event ignored: chat_id missing")
        return None
    return ParsedMessageEvent(
        event_id=event_id,
        event_type=event_type,
        message_id=message_id,
        chat_id=chat_id,
        chat_type=chat_type,
        message_type=message_type,
        text=text,
        open_id=open_id,
        create_time_ms=_optional_str(header.get("create_time")),
        tenant_key=_optional_str(header.get("tenant_key")),
        app_id=_optional_str(header.get("app_id")),
        union_id=_optional_str(sender_id.get("union_id")),
        user_id=_optional_str(sender_id.get("user_id")),
    )


def to_inbound_message(parsed: ParsedMessageEvent) -> InboundMessage:
    metadata = {
        key: value
        for key, value in (
            ("tenant_key", parsed.tenant_key),
            ("union_id", parsed.union_id),
            ("user_id", parsed.user_id),
            ("chat_type", parsed.chat_type),
            ("message_type", parsed.message_type),
        )
        if value
    }
    return InboundMessage(
        channel=CHANNEL_NAME,
        external_user_id=parsed.open_id,
        text=parsed.text,
        received_at=_received_at(parsed.create_time_ms),
        external_thread_id=parsed.chat_id,
        reply_ref=parsed.message_id,
        metadata=metadata,
    )


def _extract_text(content: object) -> str | None:
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    text = data.get("text")
    if not isinstance(text, str):
        return None
    return text.strip() or None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _received_at(create_time_ms: str | None) -> datetime:
    if create_time_ms:
        try:
            return datetime.fromtimestamp(int(create_time_ms) / 1000, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    return datetime.now(timezone.utc)


def accept_event(event_id: str) -> bool:
    ttl = get_settings().feishu_dedupe_ttl_seconds
    now = _now()
    with _seen_lock:
        expired = [key for key, seen_at in _seen_events.items() if now - seen_at > ttl]
        for key in expired:
            del _seen_events[key]
        if event_id in _seen_events:
            return False
        _seen_events[event_id] = now
        return True


def allow_rate(open_id: str) -> bool:
    limit = get_settings().chat_rate_limit_per_minute
    if limit <= 0:
        return True
    now = _now()
    with _rate_lock:
        window = _rate_windows.setdefault(open_id, deque())
        while window and now - window[0] > RATE_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


def reset_event_state() -> None:
    global _now
    with _seen_lock:
        _seen_events.clear()
    with _rate_lock:
        _rate_windows.clear()
    _now = time.time
