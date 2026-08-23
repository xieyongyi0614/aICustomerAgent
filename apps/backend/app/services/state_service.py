from datetime import datetime

from app.models.character_state import CharacterState
from app.models.relationship import RelationshipState
from app.repositories import character_state_repository, relationship_repository
from app.services import state_engine


def load_states(user_id: str) -> tuple[CharacterState, RelationshipState]:
    character = character_state_repository.get_state(user_id)
    relationship = relationship_repository.get_relationship(user_id)
    recovered = state_engine.apply_idle_recovery(character, datetime.now())
    return recovered, relationship
