"""V7.8 debug trace 端点：内存优先、DB 回退、request_id 直查、会话列表。"""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repositories import trace_repository
from app.services import agent_service


def _structured():
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "achievement"},
            "behavior": {"behavior": "celebrate", "reason": "用户达成成就"},
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "好消息",
            "inner_state": "开心",
            "current_topic": "项目上线",
        },
    }


async def _run_turn(llm, session_id):
    events = []
    async for event in agent_service.stream_chat(session_id, "default-user", "今天怎么样", llm=llm):
        events.append(event)
    return events


async def _await_until(predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_debug_trace_endpoints_with_db_fallback(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/v1/debug/turns/no-such/trace")
        assert missing.status_code == 404

        llm = fake_llm(response=["好耶"], structured_responses=_structured())
        events = await _run_turn(llm, "s-v78-e2e")
        turn_id = events[-1]["turn_id"]
        request_id = events[-1]["request_id"]

        assert await _await_until(lambda: trace_repository.get_by_turn(turn_id) is not None)

        by_turn = await client.get(f"/api/v1/debug/turns/{turn_id}/trace")
        assert by_turn.status_code == 200

        by_request = await client.get(f"/api/v1/debug/traces/{request_id}")
        assert by_request.status_code == 200
        body = by_request.json()
        assert body["request_id"] == request_id
        assert body["kind"] == "turn"
        assert body["turn_id"] == turn_id
        assert {"llm", "state_update"} <= {step["name"] for step in body["steps"]}

        listing = await client.get("/api/v1/debug/traces", params={"conversation_id": "s-v78-e2e"})
        assert listing.status_code == 200
        assert len(listing.json()) == 1

        assert (await client.get("/api/v1/debug/traces/missing-id")).status_code == 404


@pytest.mark.asyncio
async def test_lru_evicted_turn_falls_back_to_db(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_persist_enabled=True,
        trace_capacity=1,
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    first = await _run_turn(llm, "s-v78-evict-a")
    second = await _run_turn(llm, "s-v78-evict-b")
    first_turn_id = first[-1]["turn_id"]
    second_turn_id = second[-1]["turn_id"]
    assert first_turn_id != second_turn_id

    assert await _await_until(lambda: trace_repository.get_by_turn(first_turn_id) is not None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        evicted = await client.get(f"/api/v1/debug/turns/{first_turn_id}/trace")
        assert evicted.status_code == 200
        assert evicted.json()["turn_id"] == first_turn_id
        newest = await client.get(f"/api/v1/debug/turns/{second_turn_id}/trace")
        assert newest.status_code == 200
