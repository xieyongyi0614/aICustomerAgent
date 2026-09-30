"""tests/v7.8 Trace Test（testing.md §2）：完整链路 request → trace → 持久化。"""

import asyncio
import time

import pytest

from app.application import observability
from app.core.db import RuntimeTraceRow
from app.models.observability import TraceKind
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


async def _run_turn(llm, content="我今天把项目上线了", session_suffix=""):
    events = []
    async for event in agent_service.stream_chat(
        f"s-v78-trace{session_suffix}", "default-user", content, llm=llm
    ):
        events.append(event)
    return events


async def _await_until(predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


def _all_traces():
    with trace_repository.SessionLocal() as session:
        rows = session.query(RuntimeTraceRow).all()
        return [trace_repository._to_model(row) for row in rows]


@pytest.mark.asyncio
async def test_turn_trace_persisted_with_full_steps(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm)
    assert events[-1]["kind"] == "done"
    turn_id = events[-1]["turn_id"]

    assert await _await_until(lambda: trace_repository.get_by_turn(turn_id) is not None)
    record = trace_repository.get_by_turn(turn_id)
    assert record.kind is TraceKind.TURN
    assert record.status in ("complete", "degraded")
    assert record.turn_id == turn_id
    assert record.user_id == "default-user"
    assert record.conversation_id == events[-1]["session_id"]
    names = {step.name for step in record.steps}
    assert {
        "context_builder",
        "role_router",
        "turn_analyzer",
        "memory_retrieval",
        "prompt_builder",
        "llm",
        "state_update",
        "memory_extractor",
    } <= names
    llm_step = next(step for step in record.steps if step.name == "llm")
    assert llm_step.status == "ok"
    assert llm_step.first_token_ms is not None


@pytest.mark.asyncio
async def test_turn_trace_backfills_emotion_event(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, session_suffix="-events")
    turn_id = events[-1]["turn_id"]
    assert await _await_until(lambda: trace_repository.get_by_turn(turn_id) is not None)
    record = trace_repository.get_by_turn(turn_id)
    assert any(event.kind == "emotion_change" for event in record.events), record.events


@pytest.mark.asyncio
async def test_trace_sample_rate_zero_skips_persist(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_persist_enabled=True,
        observability_trace_sample_rate=0,
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, session_suffix="-sampled-off")
    turn_id = events[-1]["turn_id"]
    await asyncio.sleep(0.3)
    assert trace_repository.get_by_turn(turn_id) is None


@pytest.mark.asyncio
async def test_error_turn_always_persisted_despite_zero_sampling(
    db_session_factory, fake_llm, override_settings
):
    override_settings(
        observability_persist_enabled=True,
        observability_trace_sample_rate=0,
    )
    llm = fake_llm(raise_exc=RuntimeError("boom"), structured_responses=_structured())
    with pytest.raises(RuntimeError):
        await _run_turn(llm, session_suffix="-error")
    assert await _await_until(lambda: any(r.status == "error" for r in _all_traces()))
    rows = [record for record in _all_traces() if record.status == "error"]
    assert rows, "error 运行必须落库"
    record = rows[-1]
    assert record.status == "error"
    assert any(step.name == "llm" and step.status == "error" for step in record.steps)


@pytest.mark.asyncio
async def test_persist_disabled_keeps_v75_behavior(db_session_factory, fake_llm):
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, session_suffix="-off")
    turn_id = events[-1]["turn_id"]
    await asyncio.sleep(0.3)
    assert trace_repository.get_by_turn(turn_id) is None
    assert observability.background_tasks == set()
