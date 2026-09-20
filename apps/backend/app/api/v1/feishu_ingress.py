"""飞书 webhook 的轻量 router（FEISHU-011 方案 C2）。

飞书回调地址指向本端点；router 只做一件事：**算出该事件属于哪个分片，把原始请求
转发给对应实例**。它不做任何鉴权决策——签名 / token / 新鲜度 / 去重全部留给下游实例，
于是安全闸只有一处（应用），router 即使被伪造请求打也不会绕过它们。

两条不可动摇的约束：

1. **必须转发原始 body 与原始签名头**。飞书签名覆盖的是**密文 body**，若 router 转发
   解密后的明文，下游的签名校验必然失败（403）。故 router 只是"读一下"再原样转发。
2. **转发失败不得自行改投其他实例**。改投会破坏「同会话恒落同实例」这一方案 C 的
   前提，导致同会话并发。正确做法是返回 5xx 让飞书重投，等目标实例恢复。

取不到 `open_id` 时（challenge、结构非法、无 Encrypt Key 无法解密）固定转发 shard 0：
这些请求要么与用户无关（challenge 任何实例都能应答），要么会在下游被校验拦下，
故不需要精确路由。
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.v1.feishu_http import read_body_limited, reject
from app.channels.feishu import events, shards
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

feishu_ingress_router = APIRouter()

DOWNSTREAM_PATH = "/api/v1/feishu/events"

FORWARDED_HEADERS = (
    "content-type",
    "x-lark-request-timestamp",
    "x-lark-request-nonce",
    "x-lark-signature",
)


@feishu_ingress_router.post("/feishu/ingress/events")
async def feishu_ingress_events(request: Request) -> Response:
    """C2 router：限长 → 取 open_id → 算分片 → 原样转发 → 原样回传下游响应。"""
    settings = get_settings()
    if not (settings.feishu_enabled and settings.feishu_router_enabled):
        return reject(404, "Not Found")

    targets = settings.router_target_urls()
    if not targets:
        logger.error("feishu router enabled but FEISHU_ROUTER_INSTANCE_URLS is empty")
        return reject(503, "router not configured")

    raw = await read_body_limited(request, settings.feishu_max_body_bytes)
    if raw is None:
        logger.warning("feishu router rejected: request body over limit")
        return reject(413, "request body too large")

    shard = _target_shard(raw, settings, len(targets))
    url = targets[shard].rstrip("/") + DOWNSTREAM_PATH
    headers = _forward_headers(request)
    try:
        status, body = await asyncio.to_thread(
            _forward, url, raw, headers, settings.feishu_router_timeout_seconds
        )
    except Exception:
        # 不自行改投：改投会破坏「同会话恒落同实例」。让飞书重投，等目标实例恢复。
        logger.warning(
            "feishu router forward failed: shard=%d url=%s", shard, url, exc_info=True
        )
        return reject(503, "shard instance unavailable")
    return Response(content=body, status_code=status, media_type="application/json")


def _target_shard(raw: bytes, settings, target_count: int) -> int:
    open_id = extract_open_id(raw, settings.feishu_encrypt_key)
    if open_id is None:
        return 0
    return shards.shard_of(open_id, target_count)


def extract_open_id(raw: bytes, encrypt_key: str) -> str | None:
    """从原始 body 取 `open_id`；取不到返回 None（由调用方决定兜底路由）。

    加密体必须先用 Encrypt Key 解密——飞书加密事件的**外层只有 `encrypt` 一个字段**，
    不含任何可用于分流的明文标识。
    """
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    encrypted = payload.get("encrypt")
    if isinstance(encrypted, str) and encrypted:
        if not encrypt_key:
            return None
        try:
            payload = events.decrypt(encrypt_key, encrypted)
        except Exception:
            logger.info("feishu router: decrypt failed, falling back to shard 0")
            return None
    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    sender = event.get("sender")
    if not isinstance(sender, dict):
        return None
    sender_id = sender.get("sender_id")
    if not isinstance(sender_id, dict):
        return None
    open_id = sender_id.get("open_id")
    return open_id if isinstance(open_id, str) and open_id else None


def _forward_headers(request: Request) -> dict[str, str]:
    """只转发飞书签名相关头：其余（Host / Content-Length 等）由 urllib 重算。"""
    return {
        name: request.headers[name]
        for name in FORWARDED_HEADERS
        if request.headers.get(name)
    }


def _forward(url: str, raw: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    """同步转发（在 `asyncio.to_thread` 中调用）；下游 4xx/5xx 也原样返回。"""
    request = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
