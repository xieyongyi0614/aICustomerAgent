import logging
import time
from datetime import datetime

from app.chains import state_update_chain, turn_analysis_chain
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipDelta, RelationshipEvent, RelationshipState
from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    relationship_event_repository,
    relationship_repository,
)
from app.services import state_engine

logger = logging.getLogger(__name__)

RELATIONSHIP_DIMENSIONS = ("intimacy", "trust", "familiarity", "tension")


def _day_impact_totals(
    user_id: str, now: datetime
) -> tuple[RelationshipDelta, RelationshipDelta]:
    positive = RelationshipDelta()
    negative = RelationshipDelta()
    try:
        events = relationship_event_repository.list_events(user_id, limit=500)
    except Exception:
        logger.exception("当日事件账本读取失败，日上限按零已用处理")
        return positive, negative
    for event in events:
        if event.created_at.date() != now.date():
            continue
        for dim in RELATIONSHIP_DIMENSIONS:
            value = getattr(event.impact, dim)
            if value > 0:
                setattr(positive, dim, getattr(positive, dim) + value)
            elif value < 0:
                setattr(negative, dim, getattr(negative, dim) - value)
    return positive, negative


def _resolve_relationship_event(
    analysis: TurnAnalysis,
) -> tuple[str, str, float, str]:
    decision = analysis.relationship_event
    if decision.type != "none":
        return decision.type, decision.magnitude, decision.confidence, decision.cause
    v2_event = analysis.user_emotion.event
    mapped = turn_analysis_chain.map_v2_event_to_relationship(v2_event)
    if mapped != "none":
        return mapped, "normal", 0.5, ""
    if v2_event == "daily":
        return "long_interaction", "weak", 0.3, ""
    return "none", "normal", 0.0, ""


def load_states(user_id: str) -> tuple[CharacterState, RelationshipState]:
    character = character_state_repository.get_state(user_id)
    relationship = relationship_repository.get_relationship(user_id)
    now = datetime.now()
    recovered = state_engine.apply_idle_recovery(character, now)
    decayed = state_engine.apply_emotion_decay(recovered, now)
    if decayed != recovered:
        character_state_repository.upsert_state(user_id, decayed)
    return decayed, relationship


async def apply_and_save(
    user_id: str,
    session_id: str,
    state: ConversationState,
    analysis: TurnAnalysis,
    user_input: str,
    ai_reply: str,
    llm=None,
    trace=None,
) -> None:
    now = datetime.now()
    started = time.perf_counter()
    decision = await state_update_chain.update(
        state, analysis, user_input, ai_reply, llm=llm
    )
    if trace is not None:
        elapsed = (time.perf_counter() - started) * 1000
        trace.record("state_update", elapsed, "degraded" if decision is None else "ok")

    character = state_engine.apply_idle_recovery(state.character_state, now)
    character = state_engine.apply_character(character, decision, analysis, now)

    emotion_started = time.perf_counter()
    try:
        character = state_engine.update_emotion(character, analysis.emotion_event, now)
        if trace is not None:
            trace.record(
                "emotion_update", (time.perf_counter() - emotion_started) * 1000
            )
    except Exception as exc:
        logger.exception("情绪更新失败，保持上一轮情绪")
        if trace is not None:
            trace.record(
                "emotion_update",
                0.0,
                "error",
                error=exc.__class__.__name__,
            )

    relationship_started = time.perf_counter()
    new_relationship = state.relationship_state
    try:
        event_type, magnitude, confidence, cause = _resolve_relationship_event(analysis)
        day_positive, day_negative = _day_impact_totals(user_id, now)
        new_relationship, applied = state_engine.apply_relationship_v5(
            state.relationship_state,
            event_type,
            magnitude,
            analysis.behavior.behavior,
            day_positive,
            day_negative,
        )
        if event_type != "none":
            relationship_event_repository.create_event(
                RelationshipEvent(
                    user_id=user_id,
                    session_id=session_id,
                    type=event_type,
                    magnitude=magnitude,
                    impact=applied,
                    confidence=confidence,
                    cause=cause,
                    created_at=now,
                )
            )
        if trace is not None:
            trace.record(
                "relationship_event",
                (time.perf_counter() - relationship_started) * 1000,
            )
    except Exception as exc:
        logger.exception("关系更新失败，保持上一轮关系")
        new_relationship = state.relationship_state
        if trace is not None:
            trace.record(
                "relationship_event",
                0.0,
                "error",
                error=exc.__class__.__name__,
            )

    character_state_repository.upsert_state(user_id, character)
    relationship_repository.upsert_relationship(user_id, new_relationship)
    emotion_history_repository.append(
        user_id=user_id,
        session_id=session_id,
        user_emotion=analysis.user_emotion.emotion,
        event=analysis.user_emotion.event,
        behavior=analysis.behavior.behavior,
        mood_before=state.character_state.mood,
        mood_after=character.mood,
        energy_after=character.energy,
        stage_after=new_relationship.stage,
    )
