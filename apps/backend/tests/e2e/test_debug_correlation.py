"""V7.8 Evaluation Correlation：bundle 五部分齐备 + request_id 贯通 + x-request-id 头。"""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repositories import evaluation_repository, trace_repository
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


async def _await_until(predicate, timeout: float = 4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_turn_correlation_bundle(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_persist_enabled=True,
        observability_prompt_capture_mode="always",
        evaluation_enabled=True,
        evaluation_llm_judge_sample_rate=0,
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = []
    async for event in agent_service.stream_chat("s-v78-corr", "default-user", "我把项目上线了", llm=llm):
        events.append(event)
    turn_id = events[-1]["turn_id"]
    request_id = events[-1]["request_id"]

    assert await _await_until(
        lambda: evaluation_repository.get_by_subject("turn", turn_id) is not None
    )
    report = evaluation_repository.get_by_subject("turn", turn_id)
    assert report.meta.request_id == request_id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/debug/turns/{turn_id}/correlation")
        assert resp.status_code == 200
        body = resp.json()
        assert body["turn_id"] == turn_id
        assert body["request_id"] == request_id
        assert body["trace"] is not None
        assert {"llm", "state_update"} <= {s["name"] for s in body["trace"]["steps"]}
        assert body["evaluation"]["meta"]["request_id"] == request_id
        assert any(p["call_site"] == "answer" for p in body["prompts"])
        assert any(c["call_site"] == "answer" for c in body["llm_calls"])
        assert any(d["kind"] == "turn_intention" for d in body["decisions"])

        missing = await client.get("/api/v1/debug/turns/no-such-turn/correlation")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_chat_response_carries_request_id_header(
    db_session_factory, fake_llm, llm_override, override_settings
):
    override_settings(observability_persist_enabled=True)
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    llm_override(llm)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST", "/api/v1/chat/message", json={"content": "在吗"}
        ) as resp:
            assert resp.status_code == 200
            header_request_id = resp.headers.get("x-request-id")
            assert header_request_id is not None and len(header_request_id) == 32
            body = await resp.aread()
        import json

        final_line = [line for line in body.decode().splitlines() if line.strip()][-1]
        assert json.loads(final_line)["done"] is True
        assert await _await_until(
            lambda: trace_repository.get_by_trace_id(header_request_id) is not None
        )
