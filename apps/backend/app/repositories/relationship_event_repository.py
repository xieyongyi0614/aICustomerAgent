from app.core.db import RelationshipEventRow, SessionLocal
from app.models.relationship import RelationshipDelta, RelationshipEvent


def _to_event(row: RelationshipEventRow) -> RelationshipEvent:
    return RelationshipEvent(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        session_id=row.session_id,
        type=row.type,
        magnitude=row.magnitude,
        impact=RelationshipDelta(
            intimacy=row.impact_intimacy,
            trust=row.impact_trust,
            familiarity=row.impact_familiarity,
            respect=row.impact_respect,
            comfort=row.impact_comfort,
            tension=row.impact_tension,
        ),
        confidence=row.confidence,
        source=row.source,
        cause=row.cause,
        created_at=row.created_at,
    )


def create_event(event: RelationshipEvent) -> RelationshipEvent:
    with SessionLocal() as session:
        row = RelationshipEventRow(
            id=event.id,
            user_id=event.user_id,
            character_id=event.character_id,
            session_id=event.session_id,
            type=event.type,
            magnitude=event.magnitude,
            impact_intimacy=event.impact.intimacy,
            impact_trust=event.impact.trust,
            impact_familiarity=event.impact.familiarity,
            impact_respect=event.impact.respect,
            impact_comfort=event.impact.comfort,
            impact_tension=event.impact.tension,
            confidence=event.confidence,
            source=event.source,
            cause=event.cause,
            created_at=event.created_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_event(row)


def list_events(
    user_id: str,
    limit: int = 50,
    *,
    session_id: str | None = None,
    since=None,
    until=None,
) -> list[RelationshipEvent]:
    with SessionLocal() as session:
        query = session.query(RelationshipEventRow).filter(
            RelationshipEventRow.user_id == user_id
        )
        if session_id is not None:
            query = query.filter(RelationshipEventRow.session_id == session_id)
        if since is not None:
            query = query.filter(RelationshipEventRow.created_at >= since)
        if until is not None:
            query = query.filter(RelationshipEventRow.created_at <= until)
        rows = (
            query.order_by(RelationshipEventRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_event(row) for row in rows]


def count_events(user_id: str) -> int:
    with SessionLocal() as session:
        return session.query(RelationshipEventRow).filter(
            RelationshipEventRow.user_id == user_id
        ).count()
