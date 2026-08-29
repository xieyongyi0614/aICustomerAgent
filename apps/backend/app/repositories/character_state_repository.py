from datetime import datetime

from app.core.db import CharacterStateRow, SessionLocal
from app.models.character_state import CharacterState


def _to_state(row: CharacterStateRow) -> CharacterState:
    return CharacterState(
        mood=row.mood,
        energy=row.energy,
        current_topic=row.current_topic,
        inner_state=row.inner_state,
        intensity=row.intensity,
        cause=row.cause,
        last_event_at=row.last_event_at,
        updated_at=row.updated_at,
    )


def get_state(user_id: str) -> CharacterState:
    with SessionLocal() as session:
        row = session.get(CharacterStateRow, user_id)
        if row is None:
            return CharacterState()
        return _to_state(row)


def upsert_state(user_id: str, state: CharacterState) -> CharacterState:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(CharacterStateRow, user_id)
        if row is None:
            row = CharacterStateRow(user_id=user_id, created_at=now, updated_at=now)
            session.add(row)
        row.mood = state.mood
        row.energy = state.energy
        row.current_topic = state.current_topic
        row.inner_state = state.inner_state
        row.intensity = state.intensity
        row.cause = state.cause
        row.last_event_at = state.last_event_at
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_state(row)
