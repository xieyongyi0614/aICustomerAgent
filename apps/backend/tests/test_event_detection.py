import pytest

from app.chains import turn_analysis_chain
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipEventDecision
from tests.conftest import FakeLLM


def make_state() -> ConversationState:
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="你好")],
        summary=None,
        memories=[],
        current_input="今天辛苦你了",
    )


def _responses(analysis: dict) -> dict:
    return {"TurnAnalysis": analysis}


def _full_analysis() -> dict:
    return {
        "user_emotion": {"emotion": "happy", "event": "achievement"},
        "behavior": {"behavior": "celebrate", "reason": "用户带来好消息"},
        "emotion_event": {
            "type": "praise",
            "magnitude": "strong",
            "confidence": 0.9,
            "cause": "用户夸奖角色",
        },
        "relationship_event": {
            "type": "user_care",
            "magnitude": "normal",
            "confidence": 0.85,
            "cause": "用户主动关心角色",
        },
    }


@pytest.fixture
def state() -> ConversationState:
    return make_state()


class TestEventDetection:
    @pytest.mark.asyncio
    async def test_emotion_event_fields_propagated(self, state):
        llm = FakeLLM(structured_responses=_responses(_full_analysis()))
        analysis = await turn_analysis_chain.analyze("你真厉害", state, llm=llm)
        assert analysis.emotion_event.type == "praise"
        assert analysis.emotion_event.magnitude == "strong"
        assert analysis.emotion_event.confidence == pytest.approx(0.9)
        assert analysis.emotion_event.cause == "用户夸奖角色"

    @pytest.mark.asyncio
    async def test_relationship_event_fields_propagated(self, state):
        llm = FakeLLM(structured_responses=_responses(_full_analysis()))
        analysis = await turn_analysis_chain.analyze("谢谢陪伴", state, llm=llm)
        assert analysis.relationship_event.type == "user_care"
        assert analysis.relationship_event.magnitude == "normal"
        assert analysis.relationship_event.confidence == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_missing_v5_keys_fall_back_to_none(self, state):
        llm = FakeLLM(
            structured_responses=_responses(
                {
                    "user_emotion": {"emotion": "happy", "event": "daily"},
                    "behavior": {"behavior": "normal_reply", "reason": "日常"},
                }
            )
        )
        analysis = await turn_analysis_chain.analyze("哈哈哈", state, llm=llm)
        assert analysis.emotion_event.type == "none"
        assert analysis.relationship_event.type == "none"

    @pytest.mark.asyncio
    async def test_default_turn_analysis_has_none_events(self):
        analysis = TurnAnalysis()
        assert analysis.emotion_event.type == "none"
        assert analysis.relationship_event.type == "none"

    @pytest.mark.asyncio
    async def test_invalid_event_type_rejected(self, state):
        llm = FakeLLM(
            structured_responses=_responses(
                {
                    "user_emotion": {"emotion": "happy", "event": "daily"},
                    "behavior": {"behavior": "normal_reply", "reason": "日常"},
                    "emotion_event": {"type": "betrayal", "magnitude": "normal"},
                }
            )
        )
        with pytest.raises(Exception):
            await turn_analysis_chain.analyze("x", state, llm=llm)

    @pytest.mark.asyncio
    async def test_confidence_out_of_range_rejected(self, state):
        llm = FakeLLM(
            structured_responses=_responses(
                {
                    "user_emotion": {"emotion": "happy", "event": "daily"},
                    "behavior": {"behavior": "normal_reply", "reason": "日常"},
                    "relationship_event": {"type": "user_care", "confidence": 1.5},
                }
            )
        )
        with pytest.raises(Exception):
            await turn_analysis_chain.analyze("x", state, llm=llm)

    @pytest.mark.asyncio
    async def test_detection_failure_raises_for_caller_degradation(self, state):
        llm = FakeLLM(structured_errors={"TurnAnalysis": RuntimeError("llm down")})
        with pytest.raises(RuntimeError):
            await turn_analysis_chain.analyze("x", state, llm=llm)

    @pytest.mark.asyncio
    async def test_prompt_contains_v5_event_sections(self, state):
        llm = FakeLLM(structured_responses=_responses(_full_analysis()))
        await turn_analysis_chain.analyze("x", state, llm=llm)
        prompt_text = str(llm.seen_messages[0])
        assert "emotion_event" in prompt_text
        assert "relationship_event" in prompt_text
        assert "boundary_violation" in prompt_text
        assert "禁止输出任何数值变化量" in prompt_text


class TestV2EventMapping:
    def test_documented_mappings(self):
        assert turn_analysis_chain.map_v2_event_to_relationship("achievement") == "praise"
        assert turn_analysis_chain.map_v2_event_to_relationship("complaint") == "criticized"
        assert turn_analysis_chain.map_v2_event_to_relationship("conflict") == "conflict"
        assert turn_analysis_chain.map_v2_event_to_relationship("share_goal") == "user_help"
        assert turn_analysis_chain.map_v2_event_to_relationship("seek_help") == "user_help"
        assert turn_analysis_chain.map_v2_event_to_relationship("help_given") == "user_care"

    def test_ambiguous_events_map_to_none(self):
        for event in ("daily", "setback", "farewell"):
            assert turn_analysis_chain.map_v2_event_to_relationship(event) == "none"

    def test_unknown_event_defaults_none(self):
        assert turn_analysis_chain.map_v2_event_to_relationship("unknown") == "none"


class TestRelationshipEventDecisionModel:
    def test_defaults(self):
        decision = RelationshipEventDecision()
        assert decision.type == "none"
        assert decision.magnitude == "normal"
        assert decision.confidence == 0.0
        assert decision.cause == ""

    def test_invalid_type_rejected(self):
        with pytest.raises(Exception):
            RelationshipEventDecision(type="betrayal")

    def test_cause_max_length(self):
        with pytest.raises(Exception):
            RelationshipEventDecision(cause="好" * 51)
