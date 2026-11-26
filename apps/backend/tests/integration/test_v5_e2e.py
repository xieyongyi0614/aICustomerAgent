from datetime import datetime

import pytest

from app.chains import state_update_chain
from app.models.character_state import CharacterState, StateUpdateDecision
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipDelta, RelationshipState
from app.repositories import (
    character_state_repository,
    relationship_event_repository,
    relationship_repository,
)
from app.services.conversation import state as state_service
from app.services.observability.collector import TurnTraceSession
from tests.conftest import FakeLLM

NOW = datetime(2026, 8, 29, 12, 0, 0)

DECISION = {
    "inner_state": "开心",
    "current_topic": "用户的成就",
}


def make_conversation_state() -> ConversationState:
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="我升职了")],
        summary=None,
        memories=[],
        current_input="我升职了",
        character_state=CharacterState(mood="calm", intensity=0.3),
        relationship_state=RelationshipState(),
    )


def make_analysis(**overrides) -> TurnAnalysis:
    payload = {
        "user_emotion": {"emotion": "happy", "event": "achievement"},
        "behavior": {"behavior": "celebrate", "reason": "用户达成成就"},
        "emotion_event": {
            "type": "praise",
            "magnitude": "normal",
            "confidence": 0.9,
            "cause": "用户达成成就",
        },
        "relationship_event": {
            "type": "user_care",
            "magnitude": "normal",
            "confidence": 0.85,
            "cause": "用户主动关心角色",
        },
    }
    payload.update(overrides)
    return TurnAnalysis(**payload)


async def run_pipeline(analysis, state=None, llm=None, trace=None):
    state = state or make_conversation_state()
    await state_service.apply_and_save(
        "u1", "s1", state, analysis, "我升职了", "恭喜！", llm=llm, trace=trace
    )
    return state


class TestOrchestrationPipeline:
    @pytest.mark.asyncio
    async def test_emotion_and_relationship_applied_and_ledger_written(
        self, db_session_factory
    ):
        llm = FakeLLM(
            structured_responses={"StateUpdateDecision": DECISION},
        )
        original_state = await run_pipeline(make_analysis(), llm=llm)

        character = character_state_repository.get_state("u1")
        assert character.mood == "happy"
        assert character.cause == "用户达成成就"
        assert character.last_event_at is not None

        relationship = relationship_repository.get_relationship("u1")
        events = relationship_event_repository.list_events("u1")
        assert len(events) == 1
        event = events[0]
        assert event.type == "user_care"
        # 批次 2 固化后关系演化恒开（原用例以 setattr 关闭 rel_evolution_enabled 走 V5 平直增量 0.04）；
        # 现走 V8.5 动力学，精确值由 tests/v8.5 单测覆盖。
        assert event.impact.trust == pytest.approx(0.0351, abs=1e-6)
        assert relationship.trust == pytest.approx(
            original_state.relationship_state.trust + event.impact.trust, abs=1e-9
        )

    @pytest.mark.asyncio
    async def test_none_events_decay_only_and_zero_writes(self, db_session_factory):
        analysis = make_analysis(
            emotion_event={"type": "none", "magnitude": "normal", "confidence": 0.9},
            relationship_event={"type": "none", "magnitude": "normal", "confidence": 0.9},
            user_emotion={"emotion": "neutral", "event": "setback"},
            behavior={"behavior": "normal_reply", "reason": "日常"},
        )
        llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
        await run_pipeline(analysis, llm=llm)
        assert relationship_event_repository.count_events("u1") == 0
        character = character_state_repository.get_state("u1")
        assert character.mood == "calm"

    @pytest.mark.asyncio
    async def test_v2_event_fallback_creates_mapped_ledger_row(
        self, db_session_factory
    ):
        analysis = make_analysis(
            emotion_event={"type": "none", "magnitude": "normal", "confidence": 0.9},
            relationship_event={"type": "none", "magnitude": "normal", "confidence": 0.0},
            user_emotion={"emotion": "angry", "event": "conflict"},
            behavior={"behavior": "normal_reply", "reason": "冲突"},
        )
        llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
        await run_pipeline(analysis, llm=llm)
        events = relationship_event_repository.list_events("u1")
        assert len(events) == 1
        assert events[0].type == "conflict"
        assert events[0].impact.tension == pytest.approx(0.15)

    @pytest.mark.asyncio
    async def test_daily_event_creates_weak_long_interaction_row(
        self, db_session_factory
    ):
        analysis = make_analysis(
            emotion_event={"type": "none", "magnitude": "normal", "confidence": 0.9},
            relationship_event={"type": "none", "magnitude": "normal", "confidence": 0.0},
            user_emotion={"emotion": "neutral", "event": "daily"},
            behavior={"behavior": "normal_reply", "reason": "闲聊"},
        )
        llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
        await run_pipeline(analysis, llm=llm)
        events = relationship_event_repository.list_events("u1")
        assert len(events) == 1
        assert events[0].type == "long_interaction"
        assert events[0].magnitude == "weak"

    @pytest.mark.asyncio
    async def test_state_update_chain_failure_degrades_gracefully(
        self, db_session_factory, monkeypatch
    ):
        async def boom(*args, **kwargs):
            return None

        monkeypatch.setattr(state_update_chain, "update", boom)
        llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
        await run_pipeline(make_analysis(), llm=llm)
        character = character_state_repository.get_state("u1")
        assert character.mood == "happy"
        assert character.current_topic == ""

    @pytest.mark.asyncio
    async def test_relationship_update_failure_keeps_previous_state(
        self, db_session_factory, monkeypatch
    ):
        def boom(*args, **kwargs):
            raise RuntimeError("rel down")

        monkeypatch.setattr(
            state_service.relationship_repository,
            "commit_relationship_update",
            boom,
        )
        llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
        original = make_conversation_state()
        await run_pipeline(make_analysis(), state=original, llm=llm)
        relationship = relationship_repository.get_relationship("u1")
        assert relationship.trust == pytest.approx(0.35)
        assert relationship.tension == pytest.approx(0.0)
        assert relationship_event_repository.count_events("u1") == 0

    @pytest.mark.asyncio
    async def test_trace_records_v5_steps(self, db_session_factory):
        llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
        trace = TurnTraceSession()
        await run_pipeline(make_analysis(), llm=llm, trace=trace)
        names = {step.name for step in trace.steps}
        assert {"state_update", "emotion_update", "relationship_event"} <= names
        assert all(step.status == "ok" for step in trace.steps)

    @pytest.mark.asyncio
    async def test_day_cap_limits_same_day_accumulation(self, db_session_factory):
        llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
        analysis = make_analysis()
        for _ in range(10):
            await state_service.apply_and_save(
                "u2", "s2", make_conversation_state(), analysis, "x", "y", llm=llm
            )
        events = relationship_event_repository.list_events("u2", limit=100)
        total_trust = sum(e.impact.trust for e in events if e.type == "user_care")
        assert total_trust <= 0.30 + 1e-6
