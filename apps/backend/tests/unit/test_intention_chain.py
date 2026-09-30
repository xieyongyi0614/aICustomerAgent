from datetime import datetime

from app.chains import intention_chain
from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.goal import GoalRecord
from app.models.memory import UserMemory
from app.models.relationship import RelationshipState
from app.services.goal.service import SelectedGoal

NOW = datetime(2026, 8, 29, 12, 0, 0)


def _state() -> ConversationState:
    memory = UserMemory(
        id="m1",
        user_id="u1",
        character_id="asuna",
        type="user_fact",
        content="用户最近在加班赶项目",
        importance=0.7,
        confidence=0.8,
        source="user_stated",
        created_at=NOW,
        updated_at=NOW,
    )
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="我今天好累")],
        summary=None,
        memories=[memory],
        current_input="我今天好累",
        character_state=CharacterState(mood="worried", intensity=0.5),
        relationship_state=RelationshipState(tension=0.2),
    )


def _selected() -> SelectedGoal:
    goal = GoalRecord(
        id="g-1",
        user_id="u1",
        type="user_care",
        description="陪伴用户放松",
        priority=5,
        horizon="current",
        source="policy",
        created_turn=1,
        expires_at_turn=21,
        created_at=NOW,
        updated_at=NOW,
    )
    return SelectedGoal(goal=goal, reason="用户表达疲惫，user_care 目标提升")


def test_decide_returns_llm_candidate(fake_llm):
    llm = fake_llm(
        structured_responses={
            "IntentionDecision": {
                "intention": "comfort_user",
                "confidence": 0.8,
                "reason": "用户表达疲惫，当前目标为陪伴放松，故选择安抚",
            }
        }
    )
    decision = intention_chain.decide("我今天好累", _state(), _selected(), llm=llm)
    import asyncio

    decision = asyncio.run(decision)
    assert decision is not None
    assert decision.intention == "comfort_user"
    assert decision.confidence == 0.8


def test_decide_prompt_carries_goal_state_and_message(fake_llm):
    llm = fake_llm(
        structured_responses={
            "IntentionDecision": {"intention": "comfort_user", "confidence": 0.5}
        }
    )
    import asyncio

    asyncio.run(intention_chain.decide("我今天好累", _state(), _selected(), llm=llm))
    rendered = str(llm.seen_messages)
    assert "陪伴用户放松" in rendered
    assert "用户表达疲惫" in rendered
    assert "用户最近在加班赶项目" in rendered
    assert "我今天好累" in rendered
    assert "comfort_user" in rendered


def test_decide_without_goal_renders_placeholder(fake_llm):
    llm = fake_llm(
        structured_responses={
            "IntentionDecision": {"intention": "continue_topic", "confidence": 0.5}
        }
    )
    import asyncio

    asyncio.run(intention_chain.decide("在吗", _state(), None, llm=llm))
    rendered = str(llm.seen_messages)
    assert "暂无明确目标" in rendered


def test_decide_missing_schema_returns_none(fake_llm):
    llm = fake_llm()
    import asyncio

    decision = asyncio.run(intention_chain.decide("在吗", _state(), None, llm=llm))
    assert decision is None


def test_decide_chain_error_propagates(fake_llm):
    class Boom(Exception):
        pass

    llm = fake_llm(raise_exc=Boom())
    import asyncio

    try:
        asyncio.run(intention_chain.decide("在吗", _state(), None, llm=llm))
        raised = False
    except Boom:
        raised = True
    assert raised
