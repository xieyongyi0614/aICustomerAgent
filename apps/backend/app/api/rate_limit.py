"""进程内滑动窗口限流：仅保护 POST /api/v1/chat/message（每次调用触发多次 LLM 调用）。

chat_rate_limit_per_minute <= 0 时关闭；窗口按客户端 IP（X-Forwarded-For 优先）隔离。
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.settings import get_settings

CHAT_PATH = "/api/v1/chat/message"
_SWEEP_INTERVAL_SECONDS = 300.0

_windows: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()
_last_sweep = 0.0


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allow(key: str, limit_per_minute: int, now: float) -> bool:
    window_start = now - 60.0
    with _lock:
        window = _windows[key]
        while window and window[0] <= window_start:
            window.popleft()
        if len(window) >= limit_per_minute:
            window.append(now)
            return False
        window.append(now)
        return True


def _sweep_idle_windows(now: float) -> None:
    """回收已空且不再活跃的窗口（防 `_windows` 按客户端 IP 无界增长）。

    每个来过一次请求的 IP 都会留下一个 deque；过期条目虽被 `_allow` 弹出，
    **空 deque 与键不会消失** → 长期运行内存随访问过的 IP 数单调增长。
    本函数删除空窗口，由中间件按固定间隔调用（摊销成本，不在热路径逐请求扫）。
    """
    window_start = now - 60.0
    with _lock:
        stale = [
            key
            for key, window in _windows.items()
            if not window or window[-1] <= window_start
        ]
        for key in stale:
            del _windows[key]


async def chat_rate_limit_middleware(request: Request, call_next):
    limit = get_settings().chat_rate_limit_per_minute
    if limit > 0 and request.method == "POST" and request.url.path == CHAT_PATH:
        now = time.monotonic()
        _maybe_sweep(now)
        if not _allow(_client_key(request), limit, now):
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
            )
    return await call_next(request)


def _maybe_sweep(now: float) -> None:
    """按间隔触发空闲窗口回收（摊销，不在每个请求上做全表扫描）。"""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL_SECONDS:
        return
    _last_sweep = now
    _sweep_idle_windows(now)
