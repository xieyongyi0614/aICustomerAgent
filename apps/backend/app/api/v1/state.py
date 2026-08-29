from fastapi import APIRouter, Query

from app.api.v1.schemas import (
    BehaviorBudgetOut,
    CharacterStateOut,
    EmotionHistoryItem,
    LastBehaviorOut,
    ModeMetaOut,
    RelationshipEventItem,
    RelationshipStateOut,
    StateSnapshotOut,
)
from app.core.settings import get_settings
from app.services import history_service, state_service, trace_collector

state_router = APIRouter()


def _latest_mode() -> str | None:
    conversation = history_service.find_latest_conversation(get_settings().default_user)
    return getattr(conversation, "mode", None)


def _last_behavior_out() -> LastBehaviorOut | None:
    session = trace_collector.get_trace_collector().latest()
    meta = session.behavior_meta if session is not None else None
    if not meta:
        return None
    budget = meta.get("budget") or {}
    mode_meta = session.mode_meta if session is not None else None
    return LastBehaviorOut(
        strategy=meta.get("strategy", "natural_continuation"),
        base_strategy=meta.get("base_strategy", meta.get("strategy", "natural_continuation")),
        budget=BehaviorBudgetOut(
            max_action_desc=budget.get("max_action_desc", 1),
            allow_action_desc=budget.get("allow_action_desc", True),
            physical_contact=budget.get("physical_contact", "none"),
            emotion_expression=budget.get("emotion_expression", "natural"),
        ),
        degraded=bool(meta.get("degraded", False)),
        mode=(
            ModeMetaOut(
                confirmed=mode_meta.get("confirmed", "default"),
                effective=mode_meta.get("effective", "default"),
                switched=bool(mode_meta.get("switched", False)),
            )
            if mode_meta
            else None
        ),
    )


@state_router.get("/state", response_model=StateSnapshotOut)
def get_state_snapshot(
    user_id: str = Query(default=get_settings().default_user),
    limit: int | None = Query(default=None, ge=1, le=100),
):
    settings = get_settings()
    history_limit = limit if limit is not None else settings.state_history_limit
    snapshot = state_service.load_snapshot(user_id, history_limit)
    character_state = snapshot.character_state
    relationship_state = snapshot.relationship_state
    return StateSnapshotOut(
        character_state=CharacterStateOut(
            mood=character_state.mood,
            energy=character_state.energy,
            current_topic=character_state.current_topic,
            inner_state=character_state.inner_state,
            updated_at=character_state.updated_at,
            intensity=character_state.intensity,
            cause=character_state.cause,
            last_event_at=character_state.last_event_at,
        ),
        relationship_state=RelationshipStateOut(
            intimacy=relationship_state.intimacy,
            trust=relationship_state.trust,
            familiarity=relationship_state.familiarity,
            tension=relationship_state.tension,
            stage=relationship_state.stage,
            updated_at=relationship_state.updated_at,
        ),
        emotion_history=[
            EmotionHistoryItem(
                user_emotion=item.user_emotion,
                event=item.event,
                behavior=item.behavior,
                mood_before=item.mood_before,
                mood_after=item.mood_after,
                energy_after=item.energy_after,
                stage_after=item.stage_after,
                created_at=item.created_at,
            )
            for item in snapshot.emotion_history
        ],
        relationship_events=[
            RelationshipEventItem(
                type=event.type,
                magnitude=event.magnitude,
                impact_intimacy=event.impact.intimacy,
                impact_trust=event.impact.trust,
                impact_familiarity=event.impact.familiarity,
                impact_tension=event.impact.tension,
                confidence=event.confidence,
                source=event.source,
                cause=event.cause,
                created_at=event.created_at,
            )
            for event in snapshot.relationship_events
        ],
        mode=_latest_mode(),
        last_behavior=_last_behavior_out(),
    )
