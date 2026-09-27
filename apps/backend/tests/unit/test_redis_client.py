"""Redis 客户端单测：注入、懒建与关闭语义。"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.core import redis_client

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis(client)
    yield client
    redis_client.set_redis(None)


async def test_get_redis_returns_injected_client(fake_redis):
    assert await redis_client.get_redis().ping() is True
    assert redis_client.get_redis() is fake_redis


async def test_close_redis_clears_singleton(fake_redis):
    await redis_client.close_redis()
    assert redis_client._client is None


def test_get_redis_without_url_raises(monkeypatch):
    monkeypatch.setattr(redis_client, "_client", None)
    with pytest.raises(RuntimeError):
        redis_client.get_redis()
