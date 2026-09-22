"""Autonomy Bridge（RT-017）：主动行为触发 → 投递的关联标识与出口协调。

只做三件事：`proactive:{dedupe_key}` 关联标识、投递出口协调（经 RT-014 网关，
未纳管回落既有端口）、`ProactiveTriggered` / `ProactiveDelivered` 事件。
不改触发判定数学、dedupe_key 生成、`proactive_executor` 状态机。
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime import outbound as outbound_gateway
from app.application.agent_runtime.contracts import (
    EVENT_PROACTIVE_DELIVERED,
    EVENT_PROACTIVE_TRIGGERED,
    RuntimeEvent,
)
from app.channels.base import ChannelErrorKind, SendResult

logger = logging.getLogger(__name__)

TRACE_STEP_PROACTIVE = "proactive_coordinate"


def proactive_correlation_id(dedupe_key: str) -> str:
    return f"proactive:{dedupe_key}"


def emit_proactive_triggered(
    dedupe_key: str,
    *,
    reason: str | None = None,
    trigger_type: str | None = None,
    run_id: str | None = None,
    user_id: str | None = None,
    trace=None,
) -> int:
    return event_bus.emit(
        RuntimeEvent(
            event_type=EVENT_PROACTIVE_TRIGGERED,
            run_id=run_id,
            session_id=None,
            occurred_at=datetime.now(),
            correlation_id=proactive_correlation_id(dedupe_key),
            payload={
                "dedupe_key": dedupe_key,
                "reason": reason,
                "trigger_type": trigger_type,
                "user_id": user_id,
            },
        ),
        trace,
    )


def emit_proactive_delivered(
    dedupe_key: str,
    *,
    ok: bool,
    error: str | None = None,
    external_message_id: str | None = None,
    run_id: str | None = None,
    user_id: str | None = None,
    trace=None,
) -> int:
    return event_bus.emit(
        RuntimeEvent(
            event_type=EVENT_PROACTIVE_DELIVERED,
            run_id=run_id,
            session_id=None,
            occurred_at=datetime.now(),
            correlation_id=proactive_correlation_id(dedupe_key),
            payload={
                "dedupe_key": dedupe_key,
                "ok": ok,
                "error": error,
                "external_message_id": external_message_id,
                "user_id": user_id,
            },
        ),
        trace,
    )


async def coordinate_delivery(
    action_id: str,
    *,
    dedupe_key: str,
    user_id: str,
    text: str,
    outbound=None,
    run_id: str | None = None,
    trace=None,
) -> SendResult:
    """主动投递协调：网关优先，未纳管回落既有端口；失败不外抛。"""
    correlation_id = proactive_correlation_id(dedupe_key)
    try:
        if outbound is not None and outbound_gateway.is_routable(outbound.channel):
            result = await outbound_gateway.deliver_proactive(
                user_id,
                text,
                dedupe_key,
                channel=outbound.channel,
                trace=trace,
            )
        elif outbound is not None:
            result = await outbound.send(user_id, text, dedupe_key)
        else:
            result = SendResult(ok=False, error=ChannelErrorKind.NOT_FOUND)
    except Exception:
        logger.exception("主动投递协调异常：%s", action_id)
        result = SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)

    emit_proactive_delivered(
        dedupe_key,
        ok=result.ok,
        error=_error_value(result),
        external_message_id=result.external_message_id,
        run_id=run_id,
        user_id=user_id,
        trace=trace,
    )
    if trace is not None:
        try:
            trace.record(
                TRACE_STEP_PROACTIVE,
                0.0,
                status="ok" if result.ok else "error",
                ok=result.ok,
                error=_error_value(result),
                correlation_id=correlation_id,
                action_id=action_id,
                external_message_id=result.external_message_id,
            )
        except Exception:
            logger.exception("主动投递 trace 记录失败，已忽略")
    return result


def _error_value(result: SendResult) -> str | None:
    if result.error is None:
        return None
    return getattr(result.error, "value", result.error)
