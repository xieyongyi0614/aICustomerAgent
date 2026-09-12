"""飞书 Webhook 入口：原始 body → 校验 → 解密 → challenge → 解析 → 去重 → 快速 ack → 后台派发。"""

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
    settings = get_settings()
    if not settings.feishu_enabled:
        return _reject(404, "Not Found")
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except ValueError:
        return _reject(400, "request body is not valid json")
    if not isinstance(payload, dict):
        return _reject(400, "request body is not a json object")

    outer_token = _verification_token(payload)
    if outer_token is not None:
        try:
            events.verify_token(outer_token, settings.feishu_verification_token)
        except FeishuAuthError:
            logger.warning("feishu webhook rejected: verification token mismatch")
            return _reject(401, "verification token mismatch")
    try:
        events.verify_signature(
            raw,
            request.headers.get("x-lark-request-timestamp"),
            request.headers.get("x-lark-request-nonce"),
            settings.feishu_encrypt_key,
            request.headers.get("x-lark-signature"),
        )
    except FeishuAuthError:
        logger.warning("feishu webhook rejected: signature or timestamp invalid")
        return _reject(403, "signature verification failed")

    decrypted = False
    if "encrypt" in payload:
        try:
            payload = events.decrypt(settings.feishu_encrypt_key, payload["encrypt"])
            decrypted = True
        except FeishuConfigError:
            logger.error("feishu webhook decrypt failed: raw_len=%d", len(raw))
            return _reject(400, "event decrypt failed")

    inner_token = _verification_token(payload)
    if inner_token is not None:
        try:
            events.verify_token(inner_token, settings.feishu_verification_token)
        except FeishuAuthError:
            logger.warning("feishu webhook rejected: verification token mismatch")
            return _reject(401, "verification token mismatch")
    elif not decrypted:
        logger.warning("feishu webhook rejected: verification token missing")
        return _reject(401, "verification token missing")

    if events.is_challenge(payload):
        challenge = events.challenge_of(payload)
        if challenge is None:
            return _reject(400, "challenge field missing")
        return JSONResponse(content={"challenge": challenge})

    if not decrypted and not isinstance(payload.get("header"), dict):
        return _reject(400, "event header missing")

    parsed = events.parse_message_event(payload)
    if parsed is None:
        return JSONResponse(content={})

    if not events.allow_rate(parsed.open_id):
        logger.warning("feishu webhook rate limited: open_id=%s", parsed.open_id)
        return _reject(429, "too many requests")

    if not events.accept_event(parsed.event_id):
        return JSONResponse(content={})

    inbound = events.to_inbound_message(parsed)
    observability.spawn_background(adapter.handle_inbound_message(inbound))
    return JSONResponse(content={})


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
