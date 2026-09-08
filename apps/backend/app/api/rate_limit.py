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

_windows: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


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


async def chat_rate_limit_middleware(request: Request, call_next):
    limit = get_settings().chat_rate_limit_per_minute
    if limit > 0 and request.method == "POST" and request.url.path == CHAT_PATH:
        if not _allow(_client_key(request), limit, time.monotonic()):
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
            )
    return await call_next(request)
