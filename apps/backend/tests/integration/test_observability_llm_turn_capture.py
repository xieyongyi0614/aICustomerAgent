"""V7.8 LLM 调用捕获集成：全链 turn 覆盖各 call_site，错误行落库。"""

import asyncio
import time

import pytest

from app.application import observability
from app.models.observability import CallSite
from app.repositories import llm_call_repository
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


async def _run_turn(llm, session_id, content="我今天把项目上线了"):
    events = []
    async for event in agent_service.stream_chat(session_id, "default-user", content, llm=llm):
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
async def test_full_turn_records_all_call_sites(db_session_factory, fake_llm, override_settings):
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v78-llm")
    turn_id = events[-1]["turn_id"]
    request_id = events[-1]["request_id"]

    assert await _await_until(
        lambda: llm_call_repository.get_by_request(request_id) != []
    )
    records = llm_call_repository.get_by_request(request_id)
    sites = {record.call_site for record in records}
    assert {
        CallSite.ANSWER,
        CallSite.ROUTER,
        CallSite.TURN_ANALYSIS,
        CallSite.SCENE_INTENT,
        CallSite.INTENTION,
    } <= sites
    for record in records:
        assert record.status == "ok"
        assert record.request_id == request_id
        assert record.latency_ms >= 0
    answer = next(record for record in records if record.call_site is CallSite.ANSWER)
    assert answer.ttft_ms is not None
    assert answer.turn_id == turn_id


@pytest.mark.asyncio
async def test_error_call_recorded(db_session_factory, fake_llm, override_settings):
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v78-llm-ok")
    request_id = events[-1]["request_id"]
    assert await _await_until(
        lambda: llm_call_repository.get_by_request(request_id) != []
    )
    ok_rows = llm_call_repository.get_by_request(request_id)
    assert ok_rows

    llm = fake_llm(raise_exc=RuntimeError("boom"), structured_responses=_structured())
    with pytest.raises(RuntimeError):
        await _run_turn(llm, "s-v78-llm-err")
    assert await _await_until(
        lambda: any(
            record.status == "error"
            for record in llm_call_repository.search(limit=500)
        )
    )
    error_rows = [record for record in llm_call_repository.search(limit=500) if record.status == "error"]
    assert all(record.error_kind == "RuntimeError" for record in error_rows)


@pytest.mark.asyncio
async def test_llm_call_recorded_unconditionally(db_session_factory, fake_llm):
    """批次 2 固化后 LLM 调用采集无总闸（`observability_persist_enabled` 已删）。"""
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v78-llm-off")
    request_id = events[-1]["request_id"]
    assert await _await_until(
        lambda: llm_call_repository.get_by_request(request_id) != []
    )
