"""V8 Performance Test：世界装配开销预算 + 热路径无解释器写 + facts 降级。"""

import time

import pytest

from app.application import world_engine
from app.repositories import world_repository
from app.services import agent_service


def _structured():
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "achievement"},
            "behavior": {"behavior": "celebrate", "reason": "ok"},
        },
        "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "ok"},
        "IntentionDecision": {"intention": "continue_topic", "confidence": 0.9, "reason": "ok"},
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "ok",
            "inner_state": "平静",
            "current_topic": "日常",
        },
    }


async def _run_turn(llm, session_id, content="今天怎么样"):
    events = []
    async for event in agent_service.stream_chat(session_id, "default-user", content, llm=llm):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_world_assembly_overhead_within_budget(db_session_factory, fake_llm):
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    rounds = 10
    started = time.perf_counter()
    for index in range(rounds):
        await _run_turn(llm, f"s-v8-perf-{index}")
    avg = (time.perf_counter() - started) / rounds
    assert avg < 0.25, avg


@pytest.mark.asyncio
async def test_world_writes_only_in_step_eight(db_session_factory, fake_llm, monkeypatch):
    world_engine.ensure_world("default-user")

    def _explode(*args, **kwargs):
        raise RuntimeError("世界只允许在第 8 步写")

    monkeypatch.setattr(world_engine, "run_turn_update", _explode)
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v8-perf-guard")
    assert events[-1]["kind"] == "done"
    assert world_repository.get_world("default-user") is not None


@pytest.mark.asyncio
async def test_collect_facts_failure_degrades_policy(db_session_factory, monkeypatch):
    world_engine.ensure_world("default-user")

    def _explode(*args, **kwargs):
        raise RuntimeError("facts down")

    monkeypatch.setattr(world_engine, "get_world", _explode)
    assert world_engine.collect_facts("default-user") == {}
