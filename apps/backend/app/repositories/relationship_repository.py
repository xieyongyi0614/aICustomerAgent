from datetime import datetime

from app.core.db import RelationshipEventRow, RelationshipStateRow, SessionLocal
from app.models.relationship import RelationshipEvent, RelationshipState


def _to_relationship(row: RelationshipStateRow) -> RelationshipState:
    return RelationshipState(
        intimacy=row.intimacy,
        trust=row.trust,
        familiarity=row.familiarity,
        tension=row.tension,
        stage=row.stage,
        updated_at=row.updated_at,
    )


def get_relationship(user_id: str) -> RelationshipState:
    with SessionLocal() as session:
        row = session.get(RelationshipStateRow, user_id)
        if row is None:
            return RelationshipState()
        return _to_relationship(row)


def upsert_relationship(
    user_id: str, relationship: RelationshipState
) -> RelationshipState:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(RelationshipStateRow, user_id)
        if row is None:
            row = RelationshipStateRow(user_id=user_id, created_at=now, updated_at=now)
            session.add(row)
        row.intimacy = relationship.intimacy
        row.trust = relationship.trust
        row.familiarity = relationship.familiarity
        row.tension = relationship.tension
        row.stage = relationship.stage
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_relationship(row)


def commit_relationship_update(
    user_id: str, relationship: RelationshipState, events: list[RelationshipEvent]
) -> RelationshipState:
    """状态与事件账本同事务落库，避免部分成功导致的对账漂移。"""
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(RelationshipStateRow, user_id)
        if row is None:
            row = RelationshipStateRow(user_id=user_id, created_at=now, updated_at=now)
            session.add(row)
        row.intimacy = relationship.intimacy
        row.trust = relationship.trust
        row.familiarity = relationship.familiarity
        row.tension = relationship.tension
        row.stage = relationship.stage
        row.updated_at = now
        for event in events:
            session.add(
                RelationshipEventRow(
                    id=event.id,
                    user_id=event.user_id,
                    character_id=event.character_id,
                    session_id=event.session_id,
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
            )
        session.commit()
        session.refresh(row)
        return _to_relationship(row)
