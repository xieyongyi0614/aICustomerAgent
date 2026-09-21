"""Runtime Event System（RT-005）：进程内同步事件总线。

把「模块通信语义缺位」（M2）显式化：同步派发、代码静态注册（Q2）、单订阅者失败隔离；
事件**不落业务表**，只追加 Trace step。跨域可靠投递仍走 Outbox、世界广播仍走
`world_events`（两者零改动，本模块零 DB 写入）。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from app.application.agent_runtime.contracts import (
    EVENT_RUN_CLOSED,
    EVENT_RUN_OPENED,
    EVENT_STAGE_COMPLETED,
    EVENT_TYPES,
    RuntimeEvent,
)
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

Handler = Callable[[RuntimeEvent], None]

_LOCK = threading.Lock()
_SUBSCRIBERS: dict[str, list[Handler]] = {}


def subscribe(event_type: str, handler: Handler) -> None:
    """代码静态注册；同 (event_type, handler) 幂等；未知 event_type 抛 ValueError。"""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"未知的事件类型：{event_type!r}")
    with _LOCK:
        handlers = _SUBSCRIBERS.setdefault(event_type, [])
        if handler not in handlers:
            handlers.append(handler)


def unsubscribe(event_type: str, handler: Handler) -> bool:
    with _LOCK:
        handlers = _SUBSCRIBERS.get(event_type)
        if not handlers or handler not in handlers:
            return False
        handlers.remove(handler)
        return True


def clear_subscribers() -> None:
    with _LOCK:
        _SUBSCRIBERS.clear()


def handler_count(event_type: str) -> int:
    with _LOCK:
        return len(_SUBSCRIBERS.get(event_type, ()))


def subscribers(event_type: str) -> tuple[Handler, ...]:
    with _LOCK:
        return tuple(_SUBSCRIBERS.get(event_type, ()))


def _record_trace(trace, status: str, event: RuntimeEvent) -> None:
    if trace is None:
        return
    try:
        trace.record(
            "runtime_event",
            0.0,
            status=status,
            event_type=event.event_type,
            run_id=event.run_id,
            correlation_id=event.correlation_id,
        )
    except Exception:
        logger.exception("事件 trace 记录失败，忽略")


def emit(event: RuntimeEvent, trace=None) -> int:
    """同步派发；开关关 → 立即返回 0；返回成功投递数（失败订阅者不计入）。"""
    if not get_settings().runtime_event_bus_enabled:
        return 0
    _record_trace(trace, "ok", event)
    delivered = 0
    for handler in subscribers(event.event_type):
        try:
            handler(event)
        except Exception:
            logger.exception("事件订阅者失败：%s", event.event_type)
            _record_trace(trace, "error", event)
        else:
            delivered += 1
    return delivered


def emit_run_opened(run_id: str, session_id: str | None, trace=None) -> int:
    return emit(
        RuntimeEvent(
            event_type=EVENT_RUN_OPENED,
            run_id=run_id,
            session_id=session_id,
            occurred_at=datetime.now(),
        ),
        trace,
    )


def emit_stage_completed(
    run_id: str,
    session_id: str | None,
    stage: str,
    *,
    duration_ms: float,
    status: str = "ok",
    correlation_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    trace=None,
) -> int:
    body: dict[str, Any] = dict(payload or {})
    body.update({"stage": stage, "duration_ms": duration_ms, "status": status})
    return emit(
        RuntimeEvent(
            event_type=EVENT_STAGE_COMPLETED,
            run_id=run_id,
            session_id=session_id,
            occurred_at=datetime.now(),
            payload=body,
            correlation_id=correlation_id,
        ),
        trace,
    )


def emit_run_closed(
    run_id: str, session_id: str | None, status: str, trace=None
) -> int:
    return emit(
        RuntimeEvent(
            event_type=EVENT_RUN_CLOSED,
            run_id=run_id,
            session_id=session_id,
            occurred_at=datetime.now(),
            payload={"status": status},
        ),
        trace,
    )
