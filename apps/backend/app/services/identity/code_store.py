"""验证码存储契约与 Redis 实现：短 TTL 一次性状态。

键面（<hash> = sha256(规范化邮箱)）：
  ``email_code:<hash>``     码哈希，TTL = 验证码有效期，GETDEL 保证单次消费
  ``email_code_cd:<hash>``  发送冷却，SETNX 抢占（原子防并发重发）
  ``email_code_h:<hash>``   小时发送计数（INCR + EXPIRE NX）
  ``email_code_d:<hash>``   日发送计数（INCR + EXPIRE NX）
  ``email_code_att:<hash>`` 校验失败尝试计数，超限作废当前码
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis

from app.core import redis_client

_CODE_PREFIX = "email_code:"
_COOLDOWN_PREFIX = "email_code_cd:"
_HOURLY_PREFIX = "email_code_h:"
_DAILY_PREFIX = "email_code_d:"
_ATTEMPTS_PREFIX = "email_code_att:"

HOURLY_WINDOW_SECONDS = 3600
DAILY_WINDOW_SECONDS = 86400


@dataclass(frozen=True, slots=True)
class SendGate:
    allowed: bool
    retry_after_seconds: int = 0


class VerificationCodeStore(Protocol):
    async def reserve_send(
        self,
        email: str,
        *,
        cooldown_seconds: int,
        hourly_cap: int,
        daily_cap: int,
    ) -> SendGate: ...

    async def save_code(self, email: str, code_hash: str, *, ttl_seconds: int) -> None: ...

    async def peek_code(self, email: str) -> str | None: ...

    async def consume_code(self, email: str) -> str | None: ...

    async def bump_attempts(
        self, email: str, *, max_attempts: int, ttl_seconds: int
    ) -> int: ...

    async def clear(self, email: str) -> None: ...


def email_bucket(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


class RedisCodeStore:
    def __init__(self, client: Redis | None = None):
        self._client = client

    def _redis(self) -> Redis:
        if self._client is not None:
            return self._client
        return redis_client.get_redis()

    async def reserve_send(
        self,
        email: str,
        *,
        cooldown_seconds: int,
        hourly_cap: int,
        daily_cap: int,
    ) -> SendGate:
        client = self._redis()
        bucket = email_bucket(email)
        hourly = await client.get(f"{_HOURLY_PREFIX}{bucket}")
        if hourly is not None and int(hourly) >= hourly_cap:
            return SendGate(False, _positive(await client.ttl(f"{_HOURLY_PREFIX}{bucket}")))
        daily = await client.get(f"{_DAILY_PREFIX}{bucket}")
        if daily is not None and int(daily) >= daily_cap:
            return SendGate(False, _positive(await client.ttl(f"{_DAILY_PREFIX}{bucket}")))
        cooldown_key = f"{_COOLDOWN_PREFIX}{bucket}"
        acquired = await client.set(cooldown_key, "1", ex=cooldown_seconds, nx=True)
        if not acquired:
            return SendGate(False, _positive(await client.ttl(cooldown_key)))
        hourly_key = f"{_HOURLY_PREFIX}{bucket}"
        await client.incr(hourly_key)
        await client.expire(hourly_key, HOURLY_WINDOW_SECONDS, nx=True)
        daily_key = f"{_DAILY_PREFIX}{bucket}"
        await client.incr(daily_key)
        await client.expire(daily_key, DAILY_WINDOW_SECONDS, nx=True)
        return SendGate(True)

    async def save_code(self, email: str, code_hash: str, *, ttl_seconds: int) -> None:
        client = self._redis()
        await client.set(f"{_CODE_PREFIX}{email_bucket(email)}", code_hash, ex=ttl_seconds)

    async def peek_code(self, email: str) -> str | None:
        client = self._redis()
        return await client.get(f"{_CODE_PREFIX}{email_bucket(email)}")

    async def consume_code(self, email: str) -> str | None:
        client = self._redis()
        return await client.getdel(f"{_CODE_PREFIX}{email_bucket(email)}")

    async def bump_attempts(
        self, email: str, *, max_attempts: int, ttl_seconds: int
    ) -> int:
        client = self._redis()
        bucket = email_bucket(email)
        attempts_key = f"{_ATTEMPTS_PREFIX}{bucket}"
        count = int(await client.incr(attempts_key))
        await client.expire(attempts_key, ttl_seconds, nx=True)
        if count >= max_attempts:
            await client.delete(f"{_CODE_PREFIX}{bucket}")
        return count

    async def clear(self, email: str) -> None:
        client = self._redis()
        bucket = email_bucket(email)
        await client.delete(
            f"{_CODE_PREFIX}{bucket}",
            f"{_COOLDOWN_PREFIX}{bucket}",
            f"{_HOURLY_PREFIX}{bucket}",
            f"{_DAILY_PREFIX}{bucket}",
            f"{_ATTEMPTS_PREFIX}{bucket}",
        )


def _positive(ttl: int) -> int:
    return ttl if ttl > 0 else 1
