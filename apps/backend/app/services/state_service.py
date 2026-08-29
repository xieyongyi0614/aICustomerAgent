import logging
import time
from dataclasses import dataclass
from datetime import datetime

from app.chains import state_update_chain, turn_analysis_chain
from app.core.settings import get_settings
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipDelta, RelationshipEvent, RelationshipState
from app.models.emotion import EmotionHistoryEntry
from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    relationship_event_repository,
    relationship_repository,
)
from app.services import state_engine

logger = logging.getLogger(__name__)

RELATIONSHIP_DIMENSIONS = ("intimacy", "trust", "familiarity", "tension")

REPLAY_TYPE_KEYWORDS = (
    (("安慰", "关心", "陪", "照顾"), "user_care"),
    (("帮", "帮忙", "支持"), "user_help"),
    (("送", "礼物", "夸", "称赞"), "praise"),
    (("吵", "冲突", "生气", "冷战"), "conflict"),
)


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


@dataclass
class StateSnapshotData:
    character_state: CharacterState
    relationship_state: RelationshipState
    emotion_history: list[EmotionHistoryEntry]
    relationship_events: list


def load_snapshot(user_id: str, limit: int) -> StateSnapshotData:
    character = character_state_repository.get_state(user_id)
    relationship = relationship_repository.get_relationship(user_id)
    history = emotion_history_repository.list_recent(user_id, limit)
    events = relationship_event_repository.list_events(user_id, limit)
    return StateSnapshotData(
        character_state=character,
        relationship_state=relationship,
        emotion_history=history,
        relationship_events=events,
    )


def load_states(user_id: str) -> tuple[CharacterState, RelationshipState]:
    character = character_state_repository.get_state(user_id)
    relationship = relationship_repository.get_relationship(user_id)
    now = datetime.now()
    recovered = state_engine.apply_idle_recovery(character, now)
    decayed = state_engine.apply_emotion_decay(recovered, now)
    if decayed != recovered:
        character_state_repository.upsert_state(user_id, decayed)
    return decayed, relationship


def load_last_user_emotion(user_id: str) -> str:
    try:
        entries = emotion_history_repository.list_recent(user_id, 1)
        return entries[0].user_emotion if entries else "neutral"
    except Exception:
        logger.exception("最近用户情绪读取失败，按 neutral 处理")
        return "neutral"


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
    pending_events: list[RelationshipEvent] = []
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
            pending_events.append(
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

    try:
        replay_state, replay_events = _replay_relationship_memories(
            user_id, session_id, state, new_relationship, now
        )
        if replay_events:
            pending_events.extend(replay_events)
            new_relationship = replay_state
    except Exception:
        logger.exception("记忆回放补记失败，跳过，不影响主流程")

    character_state_repository.upsert_state(user_id, character)
    try:
        relationship_repository.commit_relationship_update(
            user_id, new_relationship, pending_events
        )
    except Exception:
        logger.exception("关系状态与事件账本落库失败，保持上一轮")
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
    try:
        replayed = _replay_relationship_memories(
            user_id, session_id, state, new_relationship, now
        )
        if replayed is not None:
            relationship_repository.upsert_relationship(user_id, replayed)
    except Exception:
        logger.exception("记忆回放补记失败，跳过，不影响主流程")


def _replay_type_for(content: str) -> str:
    for keywords, event_type in REPLAY_TYPE_KEYWORDS:
        if any(keyword in content for keyword in keywords):
            return event_type
    return "user_care"


def _replay_exists(user_id: str, cause: str) -> bool:
    events = relationship_event_repository.list_events(user_id, limit=200)
    return any(
        event.source == "memory_replay" and event.cause == cause for event in events
    )


def _replay_is_idle(user_id: str, now: datetime) -> bool:
    settings = get_settings()
    events = relationship_event_repository.list_events(user_id, limit=1)
    if not events:
        return True
    idle_hours = (now - events[0].created_at).total_seconds() / 3600
    return idle_hours >= settings.rel_replay_min_idle_hours


def _replay_relationship_memories(
    user_id: str,
    session_id: str,
    state: ConversationState,
    relationship: RelationshipState,
    now: datetime,
) -> tuple[RelationshipState, list[RelationshipEvent]]:
    settings = get_settings()
    updated = relationship
    replay_events: list[RelationshipEvent] = []
    for memory in state.memories:
        if memory.type != "relationship_event":
            continue
        try:
            cause = memory.content[:50]
            if _replay_exists(user_id, cause):
                continue
            if not _replay_is_idle(user_id, now):
                continue
            event_type = _replay_type_for(memory.content)
            base = state_engine.build_relationship_impact(event_type, "weak")
            discount = settings.rel_replay_discount
            new_values = {}
            applied = {}
            for dim in RELATIONSHIP_DIMENSIONS:
                delta = getattr(base, dim) * discount
                current = getattr(updated, dim)
                new_value = state_engine.clamp(current + delta, 0.0, 1.0)
                new_values[dim] = new_value
                applied[dim] = round(new_value - current, 6)
            stage = state_engine.next_stage(
                new_values["intimacy"],
                new_values["trust"],
                new_values["familiarity"],
                updated.stage,
                tension=new_values["tension"],
            )
            replay_events.append(
                RelationshipEvent(
                    user_id=user_id,
                    session_id=session_id,
                    type=event_type,
                    magnitude="weak",
                    impact=RelationshipDelta(**applied),
                    confidence=0.5,
                    source="memory_replay",
                    cause=cause,
                    created_at=now,
                )
            )
            updated = updated.model_copy(update={**new_values, "stage": stage})
        except Exception:
            logger.exception("单条记忆回放补记失败，跳过该条")
    return updated, replay_events
