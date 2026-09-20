"""飞书出站编排：形态判定 → 收件人解析 → 切分 → 逐段发送 → 幂等 → 收口（FEISHU-005）。

Reply（有锚点）与 Proactive（无锚点）共用同一切分/幂等/收口实现，差异仅在底层
API。所有入口**永不抛异常**；零 DB 访问（幂等存储经注入的 hook，见文件末尾）；不
import 任何 Autonomy 模块（R3）。

**幂等存储是必需能力，不是可选项**：占位判定必须跨进程共享，否则多 worker / 多实例下
同一逻辑消息会被每个实例各投一次（重复回复用户）。实现由组合根 `app/main.py` 在飞书
启用时**无条件安装**（`set_persistent_idempotency`）——通道层不得 import
`app.repositories`（依赖 allowlist fail-closed），故只能注入。
"""

import logging
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

ClaimHook = Callable[[str], Awaitable[bool]]
ReleaseHook = Callable[[str], Awaitable[None]]


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
    """由**组合根**安装持久化幂等实现（FEISHU-012）。

    通道层的依赖 allowlist 是 fail-closed 的（不得 import `app.repositories`），故持久化
    实现只能由 `app/main.py` 在飞书启用时**无条件安装**——出站幂等是必需能力，没有开关。
    """
    global _claim_hook, _release_hook, _missing_hook_logged
    _claim_hook = claim
    _release_hook = release
    _missing_hook_logged = False


def clear_persistent_idempotency() -> None:
    """卸载注入（仅供测试夹具使用；生产不会走到未安装状态）。"""
    global _claim_hook, _release_hook, _missing_hook_logged
    _claim_hook = None
    _release_hook = None
    _missing_hook_logged = False


_claim_hook: ClaimHook | None = None
_release_hook: ReleaseHook | None = None
_missing_hook_logged = False


async def _claim_delivery(key: str) -> bool:
    """占位入口：调注入的持久化实现（跨进程唯一约束）。

    **未安装 hook 属配置缺陷**（组合根没跑）：记一次 error 后**放行发送**。放行而非
    跳过，是因为「重复一条消息」远比「用户收不到回复」可接受。
    """
    global _missing_hook_logged
    if _claim_hook is None:
        if not _missing_hook_logged:
            _missing_hook_logged = True
            logger.error(
                "feishu outbound idempotency hook 未安装，已降级为放行发送（可能重复投递）："
                "应由 app/main.py 在 FEISHU_ENABLED 时安装"
            )
        return True
    return await _claim_hook(key)


async def _release_delivery(key: str) -> None:
    """回滚占位，使重试仍可继续（发送失败/抛异常时调用）。"""
    if _release_hook is None:
        return
    await _release_hook(key)
