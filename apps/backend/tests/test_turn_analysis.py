from app.chains.turn_analysis_chain import analyze
from app.models.conversation import ChatMessage, ConversationState


def _state(messages=None):
    return ConversationState(
        session_id="session-1",
        user_id="user-1",
        messages=messages
        or [
            ChatMessage(role="human", content="我在赶项目"),
            ChatMessage(role="ai", content="别太拼了"),
        ],
        summary=None,
        memories=[],
        current_input="我今天压力很大",
    )


async def test_analyze_returns_structured_analysis(fake_llm):
    llm = fake_llm(
        structured_responses={
            "TurnAnalysis": {
                "user_emotion": {"emotion": "sad", "event": "setback"},
                "behavior": {"behavior": "comfort", "reason": "用户需要情绪支持"},
            }
        }
    )
    result = await analyze("我今天压力很大", _state(), llm=llm)
    assert result.user_emotion.emotion == "sad"
    assert result.user_emotion.event == "setback"
    assert result.behavior.behavior == "comfort"

    rendered = str(llm.seen_messages)
    assert "我今天压力很大" in rendered
    assert "心情：calm" in rendered
    assert "friend" in rendered
    assert "我在赶项目" in rendered


async def test_analyze_propagates_errors(fake_llm):
    llm = fake_llm(raise_exc=RuntimeError("boom"))
    try:
        await analyze("在吗", _state(), llm=llm)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
