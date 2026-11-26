from datetime import datetime

from app.core import timeutil
from app.core import ids
from app.core.db import EmotionHistoryRow, SessionLocal
from app.models.emotion import EmotionHistoryEntry


def _to_entry(row: EmotionHistoryRow) -> EmotionHistoryEntry:
    return EmotionHistoryEntry(
        id=row.id,
        user_id=row.user_id,
        session_id=row.session_id,
        user_emotion=row.user_emotion,
        event=row.event,
        behavior=row.behavior,
        mood_before=row.mood_before,
        mood_after=row.mood_after,
        energy_after=row.energy_after,
        stage_after=row.stage_after,
        created_at=row.created_at,
    )


def append(
    user_id: str,
    session_id: str,
    user_emotion: str,
    event: str,
    behavior: str,
    mood_before: str,
    mood_after: str,
    energy_after: float,
    stage_after: str,
) -> None:
    now = timeutil.now()
    with SessionLocal() as session:
        session.add(
            EmotionHistoryRow(
                id=ids.new_id(),
                user_id=user_id,
                session_id=session_id,
                user_emotion=user_emotion,
                event=event,
                behavior=behavior,
                mood_before=mood_before,
                mood_after=mood_after,
                energy_after=energy_after,
                stage_after=stage_after,
                created_at=now,
            )
        )
        session.commit()


def list_recent(user_id: str, limit: int = 20) -> list[EmotionHistoryEntry]:
    with SessionLocal() as session:
        rows = (
            session.query(EmotionHistoryRow)
            .filter(EmotionHistoryRow.user_id == user_id)
            .order_by(
                EmotionHistoryRow.created_at.desc(), EmotionHistoryRow.id.desc()
            )
            .limit(limit)
            .all()
        )
        return [_to_entry(row) for row in rows]
