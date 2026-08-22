import logging

from app.chains.extractor_chain import extract
from app.core.settings import get_settings
from app.models.memory import UserMemory
from app.repositories import memory_repository as repo

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> set[str]:
    return set(ch for ch in text if ch.strip())


async def extract_and_save(user_id: str, user_input: str, ai_reply: str, llm=None) -> None:
    settings = get_settings()
    try:
        decision = await extract(user_input, ai_reply, llm=llm)
    except (ValueError, OSError, RuntimeError):
        logger.exception("记忆提取失败，跳过本轮")
        return
    if not decision.should_save or decision.importance < settings.memory_importance_threshold:
        return
    if decision.memory and repo.exists_similar(user_id, decision.memory):
        return
    try:
        repo.create_memory(user_id, decision.memory, decision.memory_type, decision.importance)
    except (ValueError, OSError, RuntimeError):
        logger.exception("记忆落库失败，不影响本轮回答")


def retrieve(user_id: str, user_input: str, top_k: int | None = None) -> list[UserMemory]:
    settings = get_settings()
    limit = top_k or settings.memory_top_k
    candidates = repo.list_by_user(user_id, limit=100)
    input_tokens = _tokenize(user_input)
    scored = []
    for memory in candidates:
        memory_tokens = _tokenize(memory.memory)
        if not memory_tokens:
            continue
        overlap = len(input_tokens & memory_tokens)
        score = overlap / len(memory_tokens)
        if score > 0:
            scored.append((score, memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:limit]]
