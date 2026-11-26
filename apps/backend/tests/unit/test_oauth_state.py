"""飞书授权 state 单测：签发 / 回写结果 / 单次领取 / 过期 / 载荷非法 / 单例注入。"""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from app.services.identity.feishu import oauth_state
from app.services.identity.feishu.oauth_state import (
    BIND_MODE,
    ERROR_DENIED,
    LOGIN_MODE,
    OAuthOutcome,
    OAuthState,
    RedisOAuthStateStore,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def store(redis_client):
    return RedisOAuthStateStore(redis_client)


async def test_issue_then_peek_has_no_outcome(store):
    state = await store.issue(OAuthState(state="", mode=LOGIN_MODE), ttl_seconds=300)

    payload = await store.peek(state)

    assert payload is not None
    assert payload.mode == LOGIN_MODE
    assert payload.user_id is None
    assert payload.outcome is None


async def test_bind_state_carries_initiator(store):
    state = await store.issue(
        OAuthState(state="", mode=BIND_MODE, user_id="u-1"), ttl_seconds=300
    )

    payload = await store.peek(state)

    assert (payload.mode, payload.user_id) == (BIND_MODE, "u-1")


async def test_each_issue_yields_distinct_state(store):
    first = await store.issue(OAuthState(state="", mode=LOGIN_MODE), ttl_seconds=300)
    second = await store.issue(OAuthState(state="", mode=LOGIN_MODE), ttl_seconds=300)

    assert first != second
    assert await store.peek(first) is not None
    assert await store.peek(second) is not None


async def test_save_outcome_preserves_mode_and_take_consumes_once(store):
    state = await store.issue(
        OAuthState(state="", mode=BIND_MODE, user_id="u-1"), ttl_seconds=300
    )
    stored = await store.save_outcome(
        state, OAuthOutcome(open_id="ou_1", union_id="on_1"), ttl_seconds=300
    )

    taken = await store.take(state)

    assert stored is True
    assert taken.mode == BIND_MODE
    assert taken.user_id == "u-1"
    assert taken.outcome.open_id == "ou_1"
    assert taken.outcome.union_id == "on_1"
    assert taken.outcome.ok is True
    assert await store.take(state) is None
    assert await store.peek(state) is None


async def test_save_outcome_on_unknown_state_is_rejected(store):
    assert await store.save_outcome("ghost", OAuthOutcome(open_id="ou_1"), ttl_seconds=300) is False
    assert await store.save_outcome("", OAuthOutcome(open_id="ou_1"), ttl_seconds=300) is False


async def test_outcome_error_is_not_ok(store):
    state = await store.issue(OAuthState(state="", mode=LOGIN_MODE), ttl_seconds=300)
    await store.save_outcome(state, OAuthOutcome(error=ERROR_DENIED), ttl_seconds=300)

    taken = await store.take(state)

    assert taken.outcome.ok is False
    assert taken.outcome.error == ERROR_DENIED


async def test_empty_and_unknown_state_are_rejected(store):
    assert await store.peek("") is None
    assert await store.peek("no-such-state") is None
    assert await store.take("") is None
    assert await store.take("no-such-state") is None


async def test_unknown_mode_payload_is_rejected(redis_client, store):
    await redis_client.set(
        "feishu_oauth_state:weird", '{"mode": "refresh", "user_id": null}', ex=60
    )

    assert await store.peek("weird") is None


async def test_invalid_json_payload_is_rejected(redis_client, store):
    await redis_client.set("feishu_oauth_state:junk", "not-json", ex=60)

    assert await store.peek("junk") is None


async def test_expired_state_is_rejected(redis_client, store):
    await redis_client.set("feishu_oauth_state:stale", '{"mode": "login"}', px=1)
    await asyncio.sleep(0.05)

    assert await store.peek("stale") is None


def test_state_store_singleton_is_overridable():
    original = oauth_state.get_state_store()
    fake = object()
    oauth_state.set_state_store(fake)
    try:
        assert oauth_state.get_state_store() is fake
    finally:
        oauth_state.set_state_store(original)


def test_new_state_token_is_url_safe_and_unique():
    first = oauth_state.new_state_token()
    second = oauth_state.new_state_token()

    assert first != second
    assert first.replace("-", "").replace("_", "").isalnum()
