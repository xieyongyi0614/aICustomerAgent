from datetime import datetime

from app.chains import state_update_chain
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipState
from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    relationship_repository,
)
from app.services import state_engine


def load_states(user_id: str) -> tuple[CharacterState, RelationshipState]:
    character = character_state_repository.get_state(user_id)
    relationship = relationship_repository.get_relationship(user_id)
    recovered = state_engine.apply_idle_recovery(character, datetime.now())
    return recovered, relationship


async def apply_and_save(
    user_id: str,
    session_id: str,
    state: ConversationState,
    analysis: TurnAnalysis,
    user_input: str,
    ai_reply: str,
    llm=None,
) -> None:
    now = datetime.now()
    decision = await state_update_chain.update(
        state, analysis, user_input, ai_reply, llm=llm
    )
    recovered = state_engine.apply_idle_recovery(state.character_state, now)
    new_character = state_engine.apply_character(recovered, decision, analysis, now)
    new_relationship = state_engine.apply_relationship(
        state.relationship_state,
        analysis.user_emotion.event,
        analysis.behavior.behavior,
    )
    character_state_repository.upsert_state(user_id, new_character)
    relationship_repository.upsert_relationship(user_id, new_relationship)
    emotion_history_repository.append(
        user_id=user_id,
        session_id=session_id,
        user_emotion=analysis.user_emotion.emotion,
        event=analysis.user_emotion.event,
        behavior=analysis.behavior.behavior,
        mood_before=state.character_state.mood,
        mood_after=new_character.mood,
        energy_after=new_character.energy,
        stage_after=new_relationship.stage,
    )
