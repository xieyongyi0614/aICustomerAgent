"""Outbound Gateway（RT-014）：出站归一 + 渠道适配器注册表。

Runtime 的**唯一出站面**（architecture §8.1）：`Agent Runtime → Outbound Gateway
→ 各 Channel Adapter`。本模块只做两件事——**解析适配器**与**归一投递结果**
（`SendResult`）；投递失败**不外抛**，由调用方按既有语义决定是否标记状态。

边界（RT-014 §3.2 / §4.3）：

- **契约零改动**（D6）：只依赖 `app.channels.base` 的 `OutboundMessage` /
  `SendResult` / `ChannelAdapter`；不新增错误类型，不改 `SendResult` 语义。
- **适配器由组合根注册**（D1）：本模块**不得** import 任何具体渠道实现
  （`app.channels.feishu` 等）；注册在 `app/main.py` 启动期完成，application 层
  只认 `ChannelAdapter` Protocol。
- **不新造幂等键**（D2）：键由调用方提供并**原样透传**，`feishu_deliveries`
  幂等台账语义零改动。
- **失败以 `SendResult` 表达**（D3）：任何异常归一为 `ok=False`，**不冒泡**到 Run。
- **逐渠道切**（D4）：`runtime_outbound_gateway_channels`（csv）控制已纳管渠道；
  未纳管渠道走既有 `delivery.deliver_reply` / `delivery.send_proactive`，行为逐字节不变。
- **不做重试 / 退避 / 队列 / 分片**（D5）：渠道策略不下沉到 Runtime。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.application.agent_runtime.inbound import CHANNEL_FEISHU
from app.channels.base import (
    ChannelAdapter,
    ChannelErrorKind,
    OutboundMessage,
    RecipientRef,
    SendResult,
)
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

TRACE_STEP_OUTBOUND = "outbound_deliver"
"""投递结果落 Trace 的 step 名（含 `ok` / `error` / `external_message_id`）。"""

_adapters: dict[str, ChannelAdapter] = {}


def register_adapter(channel: str, adapter: ChannelAdapter) -> None:
    """注册渠道适配器（**组合根职责**：`app/main.py` 启动期一次）。"""
    if not channel or not channel.strip():
        raise ValueError("channel 不能为空")
    _adapters[channel] = adapter


def resolve_adapter(channel: str) -> ChannelAdapter | None:
    return _adapters.get(channel)


def registered_channels() -> frozenset[str]:
    return frozenset(_adapters)


def clear_adapters() -> None:
    """卸载全部注册（仅供测试夹具使用；生产不会走到未注册状态）。"""
    _adapters.clear()


def enabled_channels() -> frozenset[str]:
    """已纳管出站归一渠道（csv；空白容错）。"""
    raw = getattr(get_settings(), "runtime_outbound_gateway_channels", "") or ""
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def is_enabled(channel: str) -> bool:
    return channel in enabled_channels()


def is_routable(channel: str) -> bool:
    """纳管且已注册适配器——调用方据此决定走网关还是既有路径。

    只纳管未注册（组合根没跑）时返回 False，调用方回退既有出口，避免回复静默丢失。
    """
    return is_enabled(channel) and resolve_adapter(channel) is not None


async def deliver(message: OutboundMessage, *, trace: Any = None) -> SendResult:
    """唯一投递出口：解析适配器 → `adapter.send` → 归一 `SendResult`（**不外抛**）。"""
    started = time.perf_counter()
    adapter = resolve_adapter(message.channel) if is_enabled(message.channel) else None
    if adapter is None:
        result = SendResult(ok=False, error=ChannelErrorKind.DISABLED)
        _record_trace(trace, message, result, started)
        return result
    try:
        result = await adapter.send(message)
    except Exception:
        logger.exception(
            "出站投递异常（已归一为 SendResult，不上抛）：channel=%s", message.channel
        )
        result = SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)
    _record_trace(trace, message, result, started)
    return result


async def deliver_reply(
    outcome, *, channel: str = CHANNEL_FEISHU, trace: Any = None
) -> SendResult:
    """回复投递入口：由 `TurnOutcome` 组装 `OutboundMessage` 后走 `deliver`。

    收件人解析沿用既有 `channel_identity_service.resolve_recipient`；解析不到时退回
    空 `external_id` —— 回复靠 `reply_ref` 锚点投递，这是既有 `delivery.deliver_reply`
    的语义，不改。
    """
    recipient = _resolve_recipient(outcome.user_id, channel)
    if recipient is None:
        logger.warning(
            "出站网关回复收件人未解析（改用锚点投递）：user_id=%s", outcome.user_id
        )
        recipient = RecipientRef(channel=channel, external_id="")
    message = OutboundMessage(
        channel=channel,
        recipient=recipient,
        text=outcome.outbound_text or "",
        reply_ref=outcome.source_message_ref,
        idempotency_key=None,
        metadata={"turn_id": outcome.turn_id} if outcome.turn_id else {},
    )
    return await deliver(message, trace=trace)


async def deliver_proactive(
    internal_user_id: str,
    text: str,
    idempotency_key: str,
    *,
    channel: str = CHANNEL_FEISHU,
    trace: Any = None,
) -> SendResult:
    """主动投递入口：组装 `OutboundMessage` 后走 `deliver`。

    幂等键由调用方提供（D2），网关只透传；缺失键与收件人不可解析的判定沿用既有
    `delivery.send_proactive` 语义（`INVALID_REQUEST` / `NOT_FOUND`）。
    """
    if not idempotency_key or not idempotency_key.strip():
        logger.error(
            "出站网关主动投递缺少幂等键：internal_user_id=%s", internal_user_id
        )
        return SendResult(ok=False, error=ChannelErrorKind.INVALID_REQUEST)
    recipient = _resolve_recipient(internal_user_id, channel)
    if recipient is None:
        logger.warning(
            "出站网关主动投递收件人未解析：internal_user_id=%s channel=%s",
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
    return await deliver(message, trace=trace)


def _resolve_recipient(internal_user_id: str, channel: str) -> RecipientRef | None:
    from app.services import channel_identity_service

    return channel_identity_service.resolve_recipient(internal_user_id, channel)


def _record_trace(
    trace: Any, message: OutboundMessage, result: SendResult, started: float
) -> None:
    if trace is None:
        return
    try:
        trace.record(
            TRACE_STEP_OUTBOUND,
            (time.perf_counter() - started) * 1000,
            status="ok" if result.ok else "error",
            ok=result.ok,
            error=result.error.value if result.error else None,
            channel=message.channel,
            external_message_id=result.external_message_id,
        )
    except Exception:
        logger.exception("出站投递结果落 Trace 失败，已忽略")
