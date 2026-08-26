import asyncio
import time

import pytest

from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    memory_repository,
    relationship_repository,
    summary_repository,
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


def _structured(turn_event, turn_behavior="normal_reply", emotion="neutral", memory=None):
    memory_decision = {
        "should_save": False,
        "memory": None,
        "memory_type": "preference",
        "importance": 0.0,
    }
    if memory:
        memory_decision = {
            "should_save": True,
            "memory": memory,
            "memory_type": "preference",
            "importance": 0.8,
        }
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
        "MemoryDecision": memory_decision,
    }


async def _turn(session_id, content, llm):
    chunks = []
    async for event in agent_service.stream_chat(session_id, USER, content, llm=llm):
        if event.get("kind") == "token":
            chunks.append(event["text"])
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


async def test_state_persistence_failure_does_not_break_summary_and_memory(
    db_session_factory, fake_llm, monkeypatch, override_settings
):
    override_settings(summary_threshold=1)

    def raise_failure(user_id, state):
        raise RuntimeError("state db down")

    monkeypatch.setattr(character_state_repository, "upsert_state", raise_failure)

    llm = fake_llm(
        response=["好耶"],
        structured_responses=_structured("daily", memory="用户喜欢寿司"),
    )
    reply = await _turn("s-be7-4", "我喜欢寿司", llm)
    assert reply == "好耶"

    assert await _wait_background(
        lambda: summary_repository.get_summary("s-be7-4") is not None
    )
    assert summary_repository.get_summary("s-be7-4").summary == "好耶"
    assert await _wait_background(
        lambda: any(
            m.memory == "用户喜欢寿司"
            for m in memory_repository.list_by_user(USER)
        )
    )
    assert character_state_repository.get_state(USER).updated_at is None
    assert len(emotion_history_repository.list_recent(USER, limit=5)) == 0
