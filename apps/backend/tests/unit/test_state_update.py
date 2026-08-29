from app.chains.state_update_chain import update
from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis, UserEmotion
from app.models.behavior import BehaviorDecision


def _state():
    return ConversationState(
        session_id="session-1",
        user_id="user-1",
        messages=[],
        summary=None,
        memories=[],
        current_input="我今天压力很大",
        character_state=CharacterState(
            mood="calm",
            energy=0.8,
            current_topic="用户的 AI Agent 项目",
            inner_state="平静",
        ),
    )


def _analysis():
    return TurnAnalysis(
        user_emotion=UserEmotion(emotion="sad", event="setback"),
        behavior=BehaviorDecision(behavior="comfort", reason="用户需要情绪支持"),
    )


async def test_update_returns_decision_and_renders_context(fake_llm):
    llm = fake_llm(
        structured_responses={
            "StateUpdateDecision": {
                "mood": "worried",
                "mood_reason": "用户受挫，替他担心",
                "inner_state": "担心用户过度疲劳",
                "current_topic": "用户的 AI Agent 项目",
            }
        }
    )
    decision = await update(
        _state(), _analysis(), "我今天压力很大", "辛苦了，抱抱", llm=llm
    )
    assert decision.mood == "worried"
    assert decision.inner_state == "担心用户过度疲劳"

    rendered = str(llm.seen_messages)
    assert "心情：calm" in rendered
    assert "用户的 AI Agent 项目" in rendered
    assert "sad" in rendered
    assert "setback" in rendered
    assert "comfort" in rendered
    assert "我今天压力很大" in rendered
    assert "辛苦了，抱抱" in rendered


async def test_update_returns_none_on_failure(fake_llm):
    llm = fake_llm(raise_exc=RuntimeError("boom"))
    decision = await update(
        _state(), _analysis(), "我今天压力很大", "辛苦了", llm=llm
    )
    assert decision is None
