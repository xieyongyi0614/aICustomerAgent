"""飞书 Webhook 入口：原始 body → 限长 → 校验 → 解密 → challenge → 解析 → 去重 → 限流 → 快速 ack → 后台派发。"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.application import observability
from app.channels.feishu import adapter, events
from app.channels.feishu.errors import FeishuAuthError, FeishuConfigError
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

feishu_router = APIRouter()


@feishu_router.post("/feishu/events")
async def feishu_events(request: Request) -> JSONResponse:
    """入站闸门链：限长 → 验签 → 解密 → 新鲜度 → token → challenge → 解析 → 去重 → 限流 → 派发。

    两条不可回退的顺序约束：

    1. **新鲜度校验必须覆盖所有来件**。签名路径（Encrypt Key 与签名头齐备）内部已含新鲜度
       校验；明文来件、空 Encrypt Key、缺签名头这三种组合下签名路径不生效，必须独立补校验，
       否则捕获到的 body 可在去重 TTL 过期后被无限重放。
    2. **限流不得以 4xx 拒收**。飞书对非 2xx 会重投同一个 `event_id`，而该 id 此时已落去重表，
       重投会被静默吞掉——用户既收不到回复、也无任何留痕。故限流改为回兜底文案并返回 200。
    """
    settings = get_settings()
    if not settings.feishu_enabled:
        return _reject(404, "Not Found")
    raw = await _read_body(request, settings.feishu_max_body_bytes)
    if raw is None:
        logger.warning("feishu webhook rejected: request body over limit")
        return _reject(413, "request body too large")
    try:
        payload = json.loads(raw)
    except ValueError:
        return _reject(400, "request body is not valid json")
    if not isinstance(payload, dict):
        return _reject(400, "request body is not a json object")

    encrypted = isinstance(payload.get("encrypt"), str)
    signature = request.headers.get("x-lark-signature")
    timestamp = request.headers.get("x-lark-request-timestamp")
    freshness_covered_by_signature = bool(settings.feishu_encrypt_key and signature)
    if not encrypted or signature:
        # 明文一律严格验签；加密体带签名头时同样验签。
        try:
            events.verify_signature(
                raw,
                timestamp,
                request.headers.get("x-lark-request-nonce"),
                settings.feishu_encrypt_key,
                signature,
            )
        except FeishuAuthError as exc:
            logger.warning("feishu webhook rejected: %s", exc)
            return _reject(403, "signature verification failed")

    if encrypted:
        try:
            payload = events.decrypt(settings.feishu_encrypt_key, payload["encrypt"])
        except FeishuConfigError:
            logger.error(
                "feishu webhook decrypt failed（Encrypt Key 与控制台不一致？）: raw_len=%d",
                len(raw),
            )
            return _reject(400, "event decrypt failed")

    if not freshness_covered_by_signature:
        try:
            events.verify_encrypted_freshness(timestamp, payload)
        except FeishuAuthError as exc:
            logger.warning("feishu webhook rejected: %s", exc)
            return _reject(403, "stale request rejected")

    inner_token = _verification_token(payload)
    if inner_token is None:
        logger.warning("feishu webhook rejected: verification token missing")
        return _reject(401, "verification token missing")
    try:
        events.verify_token(inner_token, settings.feishu_verification_token)
    except FeishuConfigError as exc:
        logger.error(
            "feishu webhook rejected: %s（FEISHU_VERIFICATION_TOKEN 未配置？）", exc
        )
        return _reject(401, "verification token mismatch")
    except FeishuAuthError:
        logger.warning("feishu webhook rejected: verification token mismatch")
        return _reject(401, "verification token mismatch")

    if events.is_challenge(payload):
        challenge = events.challenge_of(payload)
        if challenge is None:
            return _reject(400, "challenge field missing")
        return JSONResponse(content={"challenge": challenge})

    if not encrypted and not isinstance(payload.get("header"), dict):
        return _reject(400, "event header missing")

    parsed = events.parse_message_event(payload)
    if parsed is None:
        return _reply_unsupported(payload)

    # 去重先于限流：飞书重投的重复事件不得消耗该用户的限流配额。
    if not events.accept_event(parsed.event_id):
        return JSONResponse(content={})

    inbound = events.to_inbound_message(parsed)
    if not events.allow_rate(parsed.open_id):
        logger.warning("feishu webhook rate limited: open_id=%s", parsed.open_id)
        if not observability.spawn_background(adapter.reject_inbound_message(inbound)):
            logger.error(
                "feishu overloaded reply dropped: no dispatchable event loop event_id=%s",
                parsed.event_id,
            )
        return JSONResponse(content={})

    logger.info(
        "feishu event accepted: event_id=%s message_id=%s open_id=%s chat_id=%s",
        parsed.event_id,
        parsed.message_id,
        parsed.open_id,
        parsed.chat_id,
    )
    if not observability.spawn_background(adapter.ingest_inbound_message(inbound)):
        logger.error(
            "feishu event dropped: no dispatchable event loop event_id=%s",
            parsed.event_id,
        )
    return JSONResponse(content={})


def _reply_unsupported(payload: dict) -> JSONResponse:
    """非文本 / 空白私聊消息：回一句兜底文案，且与正常消息共用去重与限流闸门。

    群聊、非消息事件、缺回复锚点一律不回复（`parse_unhandled_message` 返回 `None`）。
    限流命中时连兜底也不回——用户本就在刷屏，此时再回只会放大。
    """
    unhandled = events.parse_unhandled_message(payload)
    if unhandled is None:
        return JSONResponse(content={})
    if not events.accept_event(unhandled.event_id):
        return JSONResponse(content={})
    if not events.allow_rate(unhandled.open_id):
        logger.warning(
            "feishu unsupported reply skipped: rate limited open_id=%s", unhandled.open_id
        )
        return JSONResponse(content={})
    logger.info(
        "feishu unsupported message: event_id=%s reason=%s open_id=%s",
        unhandled.event_id,
        unhandled.reason,
        unhandled.open_id,
    )
    if not observability.spawn_background(adapter.reply_unsupported_message(unhandled)):
        logger.error(
            "feishu unsupported reply dropped: no dispatchable event loop event_id=%s",
            unhandled.event_id,
        )
    return JSONResponse(content={})


async def _read_body(request: Request, max_bytes: int) -> bytes | None:
    """按块读取并限长；超限返回 None（不把超大 body 读进内存）。"""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > max_bytes:
                return None
        except ValueError:
            return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _verification_token(payload: dict) -> str | None:
    header = payload.get("header")
    if isinstance(header, dict):
        token = header.get("token")
        if isinstance(token, str) and token:
            return token
    token = payload.get("token")
    return token if isinstance(token, str) and token else None


def _reject(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})
