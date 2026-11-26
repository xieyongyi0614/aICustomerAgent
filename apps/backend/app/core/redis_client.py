"""Redis 异步客户端：懒建单例，测试经 set_redis 注入。

未配置 REDIS_URL 时 get_redis 抛 RuntimeError；是否降级为 503 由 API 层裁决。
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.settings import get_settings

_client: aioredis.Redis | None = None


def is_configured() -> bool:
    return bool(get_settings().redis_url)


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        url = get_settings().redis_url
        if not url:
            raise RuntimeError("REDIS_URL not configured")
        _client = aioredis.from_url(url, decode_responses=True)
    return _client


def set_redis(client: aioredis.Redis | None) -> None:
    global _client
    _client = client


async def ping_redis() -> bool:
    if not is_configured():
        return False
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
