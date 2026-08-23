import asyncio
import time

import pytest

from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    relationship_repository,
)
from app.services import agent_service

USER = "default-user"


async def _wait_background(predicate):
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


def _structured(turn_event, turn_behavior="normal_reply", emotion="neutral"):
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": emotion, "event": turn_event},
            "behavior": {"behavior": turn_behavior, "reason": "测试"},
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "用户带来好消息",
            "inner_state": "开心",
            "current_topic": "用户的成就",
        },
        "MemoryDecision": {
            "should_save": False,
            "memory": None,
            "memory_type": "preference",
            "importance": 0.0,
        },
    }


async def _turn(session_id, content, llm):
    chunks = []
    async for token in agent_service.stream_chat(session_id, USER, content, llm=llm):
        chunks.append(token)
    return "".join(chunks)


async def test_turn_updates_state_relationship_and_history(
    db_session_factory, fake_llm
):
    llm = fake_llm(
        response=["好耶"],
        structured_responses=_structured("achievement", "celebrate", emotion="happy"),
    )
    reply = await _turn("s-be7-1", "我今天终于把项目上线了", llm)
    assert reply == "好耶"

    assert await _wait_background(
        lambda: character_state_repository.get_state(USER).updated_at is not None
    )
    state = character_state_repository.get_state(USER)
    assert state.mood == "happy"
    assert state.energy == pytest.approx(0.9 - 0.05 + 0.10)
    assert state.inner_state == "开心"

    relationship = relationship_repository.get_relationship(USER)
    assert relationship.intimacy == pytest.approx(0.3 + 0.04 + 0.02)
    assert relationship.familiarity == pytest.approx(0.3 + 0.02)
    assert relationship.stage == "friend"

    history = emotion_history_repository.list_recent(USER, limit=5)
    assert len(history) == 1
    assert history[0].event == "achievement"
    assert history[0].behavior == "celebrate"
    assert history[0].mood_before == "calm"
    assert history[0].mood_after == "happy"
    assert history[0].stage_after == "friend"


async def test_state_update_chain_failure_falls_back_to_code_rules(
    db_session_factory, fake_llm
):
    llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured("daily"),
        structured_errors={"StateUpdateDecision": RuntimeError("update boom")},
    )
    reply = await _turn("s-be7-2", "随便聊聊", llm)
    assert reply == "嗯"

    assert await _wait_background(
        lambda: character_state_repository.get_state(USER).updated_at is not None
    )
    state = character_state_repository.get_state(USER)
    assert state.mood == "calm"
    assert state.energy == pytest.approx(0.85)
    assert state.inner_state == "平静，期待和用户聊天"

    relationship = relationship_repository.get_relationship(USER)
    assert relationship.familiarity == pytest.approx(0.31)

    history = emotion_history_repository.list_recent(USER, limit=5)
    assert len(history) == 1
    assert history[0].mood_before == history[0].mood_after == "calm"


async def test_two_turns_decay_energy_accumulatively(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured("daily"),
    )
    await _turn("s-be7-3", "第一轮", llm)
    assert await _wait_background(
        lambda: character_state_repository.get_state(USER).energy == pytest.approx(0.85)
    )
    await _turn("s-be7-3", "第二轮", llm)
    assert await _wait_background(
        lambda: character_state_repository.get_state(USER).energy == pytest.approx(0.80)
    )
    history = emotion_history_repository.list_recent(USER, limit=5)
    assert len(history) == 2
