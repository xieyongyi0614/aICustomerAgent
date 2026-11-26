"""V7.8 debug prompt 快照端点。"""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repositories import prompt_snapshot_repository
from app.application import chat_pipeline as agent_service
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


async def _await_until(predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_debug_prompt_endpoints(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_prompt_capture_mode="always",
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = []
    async for event in agent_service.stream_chat("s-v78-prompt-e2e", "default-user", "今天怎么样", llm=llm):
        events.append(event)
    turn_id = events[-1]["turn_id"]

    assert await _await_until(lambda: prompt_snapshot_repository.get_by_turn(turn_id) != [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get(f"/api/v1/debug/turns/{turn_id}/prompts")
        assert listing.status_code == 200
        rows = listing.json()
        assert any(row["call_site"] == "answer" for row in rows)
        assert any(row["section_budget"] for row in rows)

        snapshot_id = rows[0]["id"]
        detail = await client.get(f"/api/v1/debug/prompts/{snapshot_id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == snapshot_id

        assert (
            await client.get("/api/v1/debug/turns/no-such/prompts")
        ).status_code == 404
        assert (await client.get("/api/v1/debug/prompts/no-such")).status_code == 404
