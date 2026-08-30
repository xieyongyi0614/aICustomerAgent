"""V7.8 debug LLM 调用端点：明细过滤与 summary 聚合。"""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repositories import llm_call_repository
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
        "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "ok"},
        "IntentionDecision": {
            "intention": "celebrate_with_user",
            "confidence": 0.9,
            "reason": "ok",
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "好消息",
            "inner_state": "开心",
            "current_topic": "项目上线",
        },
    }


async def _await_until(predicate, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_debug_llm_calls_endpoints(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = []
    async for event in agent_service.stream_chat("s-v78-llm-e2e", "default-user", "今天怎么样", llm=llm):
        events.append(event)
    request_id = events[-1]["request_id"]

    assert await _await_until(lambda: llm_call_repository.get_by_request(request_id) != [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/api/v1/debug/llm-calls", params={"request_id": request_id})
        assert listing.status_code == 200
        rows = listing.json()
        assert {row["call_site"] for row in rows} >= {"answer", "router"}
        assert all(row["request_id"] == request_id for row in rows)

        filtered = await client.get(
            "/api/v1/debug/llm-calls", params={"request_id": request_id, "call_site": "answer"}
        )
        assert [row["call_site"] for row in filtered.json()] == ["answer"]

        summary = await client.get("/api/v1/debug/llm-calls/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["calls"] >= len(rows)
        assert body["errors"] == 0
        assert "answer" in body["by_call_site"]
        assert "latency_p95_ms" in body["by_call_site"]["answer"]
