"""V7.8 Prompt 快照集成：快照与实际发送消息逐字节一致、模式与采样矩阵。"""

import asyncio
import time

import pytest

from app.repositories import prompt_snapshot_repository
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
async def test_snapshot_matches_sent_messages(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_persist_enabled=True,
        observability_prompt_capture_mode="always",
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v78-prompt")
    turn_id = events[-1]["turn_id"]
    request_id = events[-1]["request_id"]

    assert await _await_until(
        lambda: prompt_snapshot_repository.get_by_turn(turn_id) != []
    )
    snapshots = prompt_snapshot_repository.get_by_turn(turn_id)
    answer = next(s for s in snapshots if s.call_site.value == "answer")
    assert answer.request_id == request_id
    assert answer.section_budget is not None
    assert answer.section_budget["user_message"] == len("我今天把项目上线了")
    assert answer.section_budget["total"] <= answer.section_budget["budget"]

    answer_seen = [
        messages
        for messages in llm.seen_messages
        if messages and getattr(messages[0], "content", "") == answer.messages[0]["content"]
    ]
    assert answer_seen, "快照必须与 FakeLLM 实际收到的消息一致"
    seen = answer_seen[0]
    assert len(seen) == len(answer.messages)
    for message, payload in zip(seen, answer.messages):
        assert str(message.content) == payload["content"]
        assert payload["role"] in ("system", "human", "ai")


@pytest.mark.asyncio
async def test_capture_mode_disabled_records_nothing(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_persist_enabled=True,
        observability_prompt_capture_mode="disabled",
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v78-prompt-off")
    turn_id = events[-1]["turn_id"]
    await asyncio.sleep(0.3)
    assert prompt_snapshot_repository.get_by_turn(turn_id) == []


@pytest.mark.asyncio
async def test_sample_rate_zero_records_nothing(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_persist_enabled=True,
        observability_prompt_capture_mode="sampled",
        observability_prompt_sample_rate=0,
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v78-prompt-s0")
    turn_id = events[-1]["turn_id"]
    await asyncio.sleep(0.3)
    assert prompt_snapshot_repository.get_by_turn(turn_id) == []
