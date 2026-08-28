import json
from datetime import datetime

from app.core.db import SceneStateRow, SessionLocal
from app.models.scene import PendingAction, SceneState


def _parse_pending_action(raw: str | None) -> PendingAction | None:
    if raw is None:
        return None
    return PendingAction.model_validate(json.loads(raw))


def _to_state(row: SceneStateRow) -> SceneState:
    return SceneState(
        session_id=row.session_id,
        turn_id=row.turn_id,
        location=row.location,
        current_activity=row.current_activity,
        current_action=row.current_action,
        pending_action=_parse_pending_action(row.pending_action),
    )


def get_scene_state(session_id: str) -> SceneState:
    with SessionLocal() as session:
        row = session.get(SceneStateRow, session_id)
        if row is None:
            return SceneState(session_id=session_id)
        return _to_state(row)


def upsert_scene_state(session_id: str, state: SceneState) -> SceneState:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(SceneStateRow, session_id)
        if row is None:
            row = SceneStateRow(session_id=session_id, created_at=now, updated_at=now)
            session.add(row)
        row.turn_id = state.turn_id
        row.location = state.location
        row.current_activity = state.current_activity
        row.current_action = state.current_action
        row.pending_action = (
            json.dumps(state.pending_action.model_dump())
            if state.pending_action is not None
            else None
        )
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_state(row)
