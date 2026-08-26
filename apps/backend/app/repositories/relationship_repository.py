from datetime import datetime

from app.core.db import RelationshipStateRow, SessionLocal
from app.models.relationship import RelationshipState


def _to_relationship(row: RelationshipStateRow) -> RelationshipState:
    return RelationshipState(
        intimacy=row.intimacy,
        trust=row.trust,
        familiarity=row.familiarity,
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
        row.stage = relationship.stage
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_relationship(row)
