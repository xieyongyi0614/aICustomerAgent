"""飞书出站编排：形态判定 → 收件人解析 → 切分 → 逐段发送 → 幂等 → 收口（FEISHU-005）。

Reply（有锚点）与 Proactive（无锚点）共用同一切分/幂等/收口实现，差异仅在底层
API。所有入口**永不抛异常**；零 DB 访问；不 import 任何 Autonomy 模块（R3）。
"""

import logging
import threading
import time
from collections import OrderedDict

from app.channels.base import (
    ChannelAdapter,
    ChannelErrorKind,
    OutboundMessage,
    RecipientRef,
    SendResult,
)
from app.channels.feishu import client
from app.channels.feishu.identity import FEISHU_CHANNEL
from app.channels.feishu.outbound import normalize_text, split_text
from app.core.settings import get_settings
from app.services import channel_identity_service

logger = logging.getLogger(__name__)

# 插入序即时间序：过期项从头部批量摘除（O(过期数)），避免每次调用全表扫描。
_delivered: OrderedDict[str, float] = OrderedDict()
_delivered_lock = threading.Lock()


def reset_delivery_state() -> None:
    with _delivered_lock:
        _delivered.clear()


class FeishuChannelAdapter:
    async def send(self, message: OutboundMessage) -> SendResult:
        try:
            return await _send(message)
        except Exception:
            logger.exception("feishu outbound send failed unexpectedly")
            return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)


async def deliver_reply(outcome) -> SendResult:
    recipient = channel_identity_service.resolve_recipient(
        outcome.user_id, FEISHU_CHANNEL
    )
    if recipient is None:
        logger.warning(
            "feishu reply recipient unresolved (reply proceeds via anchor): user_id=%s",
            outcome.user_id,
        )
        recipient = RecipientRef(channel=FEISHU_CHANNEL, external_id="")
    message = OutboundMessage(
        channel=FEISHU_CHANNEL,
        recipient=recipient,
        text=outcome.outbound_text or "",
        reply_ref=outcome.source_message_ref,
        idempotency_key=None,
        metadata={"turn_id": outcome.turn_id} if outcome.turn_id else {},
    )
    return await FeishuChannelAdapter().send(message)


async def send_proactive(
    internal_user_id: str,
    text: str,
    idempotency_key: str,
    channel: str = FEISHU_CHANNEL,
) -> SendResult:
    if not idempotency_key or not idempotency_key.strip():
        logger.error(
            "feishu proactive rejected: missing idempotency_key internal_user_id=%s",
            internal_user_id,
        )
        return SendResult(ok=False, error=ChannelErrorKind.INVALID_REQUEST)
    recipient = channel_identity_service.resolve_recipient(internal_user_id, channel)
    if recipient is None:
        logger.warning(
            "feishu proactive recipient unresolved: internal_user_id=%s channel=%s",
            internal_user_id,
            channel,
        )
        return SendResult(ok=False, error=ChannelErrorKind.NOT_FOUND)
    message = OutboundMessage(
        channel=channel,
        recipient=recipient,
        text=text,
        reply_ref=None,
        idempotency_key=idempotency_key,
    )
    return await FeishuChannelAdapter().send(message)


async def _send(message: OutboundMessage) -> SendResult:
    text = normalize_text(message.text)
    if not text:
        logger.warning(
            "feishu outbound skipped: empty text channel=%s", message.channel
        )
        return SendResult(ok=False, error=ChannelErrorKind.INVALID_REQUEST)
    parts = split_text(text, get_settings().feishu_max_reply_chars)
    if message.reply_ref:
        return await _send_reply_parts(message.reply_ref, parts)
    if not message.idempotency_key or not message.idempotency_key.strip():
        logger.error(
            "feishu proactive rejected: missing idempotency_key channel=%s recipient=%s",
            message.channel,
            message.recipient.external_id,
        )
        return SendResult(ok=False, error=ChannelErrorKind.INVALID_REQUEST)
    return await _send_proactive_parts(message, parts)


async def _send_reply_parts(message_ref: str, parts: list[str]) -> SendResult:
    external_message_id = None
    for index, part in enumerate(parts):
        key = f"reply:{message_ref}:{index}"
        if _already_delivered(key):
            continue
        result = await client.reply_message(message_ref, part)
        if not result.ok:
            logger.error(
                "feishu reply stopped: message_ref=%s segment=%d/%d error=%s",
                message_ref,
                index + 1,
                len(parts),
                result.error.value if result.error else "unknown",
            )
            return result
        _mark_delivered(key)
        if result.external_message_id:
            external_message_id = result.external_message_id
    return SendResult(ok=True, external_message_id=external_message_id)


async def _send_proactive_parts(
    message: OutboundMessage, parts: list[str]
) -> SendResult:
    base_key = (
        f"proactive:{message.channel}:{message.recipient.external_id}:"
        f"{message.idempotency_key}"
    )
    for index, part in enumerate(parts):
        key = f"{base_key}:{index}"
        if _already_delivered(key):
            continue
        result = await client.send_message(message.recipient.external_id, part)
        if not result.ok:
            logger.error(
                "feishu proactive send stopped: recipient=%s segment=%d/%d error=%s",
                message.recipient.external_id,
                index + 1,
                len(parts),
                result.error.value if result.error else "unknown",
            )
            return result
        _mark_delivered(key)
    return SendResult(ok=True)


def _already_delivered(key: str) -> bool:
    ttl = get_settings().feishu_dedupe_ttl_seconds
    now = time.time()
    with _delivered_lock:
        while _delivered:
            oldest = next(iter(_delivered))
            if now - _delivered[oldest] <= ttl:
                break
            del _delivered[oldest]
        return key in _delivered


def _mark_delivered(key: str) -> None:
    with _delivered_lock:
        _delivered[key] = time.time()
