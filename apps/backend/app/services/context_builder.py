import logging
import time

from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.relationship import RelationshipState
from app.services import conversation_service
from app.services import memory_service
from app.services import state_service
from app.services import summary_service

logger = logging.getLogger(__name__)


def _load_states_with_fallback(user_id: str) -> tuple[CharacterState, RelationshipState]:
    try:
        return state_service.load_states(user_id)
    except Exception:
        logger.exception("状态读取失败，降级为默认状态")
        return CharacterState(), RelationshipState()


async def build(
    session_id: str,
    user_id: str,
    current_input: str,
    trace=None,
) -> ConversationState:
    if not current_input:
        raise ValueError("current_input 必填")
    conversation_service.ensure_conversation(session_id, user_id)
    messages = conversation_service.load_window(session_id)
    current = summary_service.get_summary(session_id)
    summary = current.summary if current else None
    started = time.perf_counter()
    memories = memory_service.retrieve(user_id, current_input)
    if trace is not None:
        trace.record("memory_retrieval", (time.perf_counter() - started) * 1000)
    character_state, relationship_state = _load_states_with_fallback(user_id)
    return ConversationState(
        session_id=session_id,
        user_id=user_id,
        messages=messages,
        summary=summary,
        memories=memories,
        current_input=current_input,
        character_state=character_state,
        relationship_state=relationship_state,
    )
