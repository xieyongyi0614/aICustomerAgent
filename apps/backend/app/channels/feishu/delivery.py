"""飞书出站编排：形态判定 → 收件人解析 → 切分 → 逐段发送 → 幂等 → 收口（FEISHU-005）。

Reply（有锚点）与 Proactive（无锚点）共用同一切分/幂等/收口实现，差异仅在底层
API。所有入口**永不抛异常**；零 DB 访问；不 import 任何 Autonomy 模块（R3）。
"""

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

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
_mono = time.monotonic

ClaimHook = Callable[[str], Awaitable[bool]]
ReleaseHook = Callable[[str], Awaitable[None]]


def reset_delivery_state() -> None:
    global _mono
    with _delivered_lock:
        _delivered.clear()
    _mono = time.monotonic


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
        if not await _claim_delivery(key):
            continue
        try:
            result = await client.reply_message(message_ref, part)
        except BaseException:
            await _release_delivery(key)
            raise
        if not result.ok:
            await _release_delivery(key)
            logger.error(
                "feishu reply stopped: message_ref=%s segment=%d/%d error=%s",
                message_ref,
                index + 1,
                len(parts),
                result.error.value if result.error else "unknown",
            )
            return result
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
        if not await _claim_delivery(key):
            continue
        try:
            result = await client.send_message(message.recipient.external_id, part)
        except BaseException:
            await _release_delivery(key)
            raise
        if not result.ok:
            await _release_delivery(key)
            logger.error(
                "feishu proactive send stopped: recipient=%s segment=%d/%d error=%s",
                message.recipient.external_id,
                index + 1,
                len(parts),
                result.error.value if result.error else "unknown",
            )
            return result
    return SendResult(ok=True)


_claim_hook: ClaimHook | None = None
_release_hook: ReleaseHook | None = None


def set_persistent_idempotency(claim: ClaimHook, release: ReleaseHook) -> None:
    """由**组合根**安装持久化幂等实现（FEISHU-011 出站幂等落库）。

    通道层的依赖 allowlist 是 fail-closed 的（不得 import `app.repositories`），
    故持久化实现不能在这里直接构造，只能由 `app/main.py` 注入。未安装时走进程内表。
    """
    global _claim_hook, _release_hook
    _claim_hook = claim
    _release_hook = release


def clear_persistent_idempotency() -> None:
    global _claim_hook, _release_hook
    _claim_hook = None
    _release_hook = None


async def _claim_delivery(key: str) -> bool:
    """占位入口：装了持久化实现就走它（跨进程），否则走进程内表。"""
    if _claim_hook is not None:
        return await _claim_hook(key)
    return _claim_delivery_memory(key)


async def _release_delivery(key: str) -> None:
    if _release_hook is not None:
        await _release_hook(key)
        return
    _release_delivery_memory(key)


def _idempotency_ttl_seconds() -> int:
    """出站幂等窗口：`feishu_outbound_idempotency_ttl_seconds` 为 0 时沿用入站去重 TTL。"""
    settings = get_settings()
    return (
        settings.feishu_outbound_idempotency_ttl_seconds
        or settings.feishu_dedupe_ttl_seconds
    )


def _claim_delivery_memory(key: str) -> bool:
    """进程内「原子查 + 占位」：同一幂等键至多一个并发调用者拿到 True。

    幂等必须由**单次加锁内**的判定保证：若拆成「先查、再发（await）、后记账」，
    并发调用者会在 `await` 处交错而同时看到「未投递」，导致重复投递。
    发送失败时调用 `_release_delivery` 回滚，使重试仍可继续。

    窗口是「时长」，故用单调钟（`_mono`）而非 wall clock：回拨会让条目永不淘汰，
    使后续重投被自己的幂等表静默跳过（与 `events` 的时钟约定一致）。
    """
    ttl = _idempotency_ttl_seconds()
    now = _mono()
    with _delivered_lock:
        _evict_delivered(now, ttl)
        if key in _delivered:
            return False
        _delivered[key] = now
        return True


def _release_delivery_memory(key: str) -> None:
    with _delivered_lock:
        _delivered.pop(key, None)


def _evict_delivered(now: float, ttl: float) -> None:
    while _delivered:
        if now - next(iter(_delivered.values())) <= ttl:
            break
        _delivered.popitem(last=False)
