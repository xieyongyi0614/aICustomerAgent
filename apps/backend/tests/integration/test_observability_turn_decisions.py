"""V7.8 Turn 级决策记录：goal/intention/behavior 三类 kind 与 request_id 关联。"""

import asyncio
import time

import pytest

from app.models.observability import DecisionKind
from app.repositories import decision_repository
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


async def _await_until(predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_turn_level_decisions_recorded(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = []
    async for event in agent_service.stream_chat("s-v78-turndec", "default-user", "我把项目上线了", llm=llm):
        events.append(event)
    request_id = events[-1]["request_id"]

    assert await _await_until(
        lambda: {
            record.kind
            for record in decision_repository.search(request_id=request_id)
        }
        >= {DecisionKind.TURN_GOAL, DecisionKind.TURN_INTENTION, DecisionKind.TURN_BEHAVIOR}
    )
    rows = {record.kind: record for record in decision_repository.search(request_id=request_id)}
    assert rows[DecisionKind.TURN_GOAL].decision in ("none", "user_care", "relationship", "conversation", "scene")
    assert rows[DecisionKind.TURN_INTENTION].decision == "celebrate_with_user"
    assert rows[DecisionKind.TURN_BEHAVIOR].decision != "none"
    assert all(row.conversation_id == "s-v78-turndec" for row in rows.values())


@pytest.mark.asyncio
async def test_turn_decisions_skipped_when_persist_disabled(db_session_factory, fake_llm):
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = []
    async for event in agent_service.stream_chat("s-v78-turndec-off", "default-user", "在吗", llm=llm):
        events.append(event)
    await asyncio.sleep(0.3)
    assert decision_repository.search(limit=200) == []
