"""飞书 HTTP 入口的共用助手：限长读体与统一拒绝响应。

被 `webhook.py`（webhook 端点）与 `ingress.py`（C2 轻量 router）共用。
"""

from fastapi import Request
from fastapi.responses import JSONResponse


async def read_body_limited(request: Request, max_bytes: int) -> bytes | None:
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


def reject(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})
