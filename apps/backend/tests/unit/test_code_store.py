"""RedisCodeStore 单测：冷却 / 频控 / 单次消费 / 尝试作废。"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.services.identity.code_store import RedisCodeStore, email_bucket

pytestmark = pytest.mark.unit


@pytest.fixture
async def store():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield RedisCodeStore(client)
    await client.aclose()


async def test_reserve_send_allows_once_within_cooldown(store):
    first = await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=6, daily_cap=20)
    assert first.allowed is True
    second = await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=6, daily_cap=20)
    assert second.allowed is False
    assert second.retry_after_seconds > 0


async def test_reserve_send_is_normalizing_email(store):
    await store.reserve_send("A@X.com", cooldown_seconds=60, hourly_cap=6, daily_cap=20)
    gate = await store.reserve_send("  a@x.com ", cooldown_seconds=60, hourly_cap=6, daily_cap=20)
    assert gate.allowed is False


async def test_hourly_cap_denies_after_window_count(store):
    client = store._redis()
    for _ in range(2):
        await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=2, daily_cap=20)
        await client.delete(f"email_code_cd:{email_bucket('a@x.com')}")
    gate = await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=2, daily_cap=20)
    assert gate.allowed is False
    assert gate.retry_after_seconds > 0


async def test_daily_cap_survives_hourly_clear(store):
    await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=6, daily_cap=1)
    client = store._redis()
    await client.delete(f"email_code_cd:{email_bucket('a@x.com')}")
    await client.delete(f"email_code_h:{email_bucket('a@x.com')}")
    gate = await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=6, daily_cap=1)
    assert gate.allowed is False


async def test_code_single_consume(store):
    await store.save_code("a@x.com", "hash-1", ttl_seconds=300)
    assert await store.peek_code("a@x.com") == "hash-1"
    assert await store.consume_code("a@x.com") == "hash-1"
    assert await store.consume_code("a@x.com") is None
    assert await store.peek_code("a@x.com") is None


async def test_bump_attempts_revokes_code_at_max(store):
    await store.save_code("a@x.com", "hash-1", ttl_seconds=300)
    assert await store.bump_attempts("a@x.com", max_attempts=3, ttl_seconds=300) == 1
    assert await store.bump_attempts("a@x.com", max_attempts=3, ttl_seconds=300) == 2
    assert await store.peek_code("a@x.com") == "hash-1"
    assert await store.bump_attempts("a@x.com", max_attempts=3, ttl_seconds=300) == 3
    assert await store.peek_code("a@x.com") is None


async def test_clear_removes_all_buckets(store):
    await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=6, daily_cap=20)
    await store.save_code("a@x.com", "hash-1", ttl_seconds=300)
    await store.clear("a@x.com")
    assert await store.peek_code("a@x.com") is None
    gate = await store.reserve_send("a@x.com", cooldown_seconds=60, hourly_cap=6, daily_cap=20)
    assert gate.allowed is True
