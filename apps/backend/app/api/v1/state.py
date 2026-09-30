from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.v1.auth import require_user
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
from app.services.conversation import history as history_service
from app.services.conversation import state as state_service
from app.services.observability import collector as trace_collector

state_router = APIRouter()


def _latest_mode(user_id: str) -> str | None:
    conversation = history_service.find_latest_conversation(user_id)
    return getattr(conversation, "mode", None)


def _last_behavior_out(user_id: str) -> LastBehaviorOut | None:
    session = trace_collector.get_trace_collector().latest_for_user(user_id)
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
    user_id: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
    caller: str = Depends(require_user),
):
    user_id = user_id or caller
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
        mode=_latest_mode(user_id),
        last_behavior=_last_behavior_out(user_id),
    )


class ModeSetRequest(BaseModel):
    mode: str
    user_id: str | None = None


@state_router.post("/state/mode")
def set_mode(body: ModeSetRequest, caller: str = Depends(require_user)):
    if body.mode not in {"professional", "default", "immersive"}:
        raise HTTPException(status_code=422, detail="invalid mode")
    user_id = body.user_id or caller
    session_id = history_service.find_latest_conversation(user_id)
    session_id = getattr(session_id, "id", None)
    if session_id is None:
        # 无会话时仅回传期望模式，待首轮对话落库
        return {"ok": True, "mode": body.mode, "session_id": None}
    from app.services.conversation import service as conversation_service

    conversation_service.set_preferred_mode(user_id, body.mode)
    return {"ok": True, "mode": body.mode, "session_id": session_id}
