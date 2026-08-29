import logging
from datetime import datetime

from app.chains.extractor_chain import extract
from app.core.settings import get_settings
from app.models.memory import UserMemory, UserMemoryV4
from app.repositories import memory_repository as repo

logger = logging.getLogger(__name__)

WEIGHT_LEXICAL = 0.45
WEIGHT_IMPORTANCE = 0.25
WEIGHT_RECENCY = 0.20
WEIGHT_TYPE_AFFINITY = 0.10
RECENCY_HALF_LIFE_DAYS = 30.0

TYPE_AFFINITY_KEYWORDS = {
    "user_preference": ("喜欢", "讨厌", "偏好", "爱", "不爱", "不喜欢", "讨厌"),
    "user_fact": ("在哪", "工作", "住", "养", "做什么", "是谁"),
    "important_event": ("面试", "经历", "发生过", "事件", "考试"),
    "relationship_event": ("我们", "一起", "送过", "看过", "去过"),
}


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


def _detect_query_types(user_input: str) -> set[str]:
    return {
        memory_type
        for memory_type, keywords in TYPE_AFFINITY_KEYWORDS.items()
        if any(keyword in user_input for keyword in keywords)
    }


def _lexical_overlap(user_input: str, content: str) -> float:
    input_tokens = _tokenize(user_input)
    content_tokens = _tokenize(content)
    if not content_tokens:
        return 0.0
    return len(input_tokens & content_tokens) / len(content_tokens)


def _recency(memory: UserMemoryV4, now: datetime) -> float:
    reference = memory.last_accessed_at or memory.created_at
    reference = reference.replace(tzinfo=None) if reference.tzinfo else reference
    days = max((now - reference).total_seconds() / 86400, 0)
    return 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)


def _score_memory(
    memory: UserMemoryV4, user_input: str, query_types: set[str], now: datetime
) -> float:
    affinity = (
        0.5
        if not query_types
        else (1.0 if memory.type in query_types else 0.0)
    )
    return (
        WEIGHT_LEXICAL * _lexical_overlap(user_input, memory.content)
        + WEIGHT_IMPORTANCE * memory.importance
        + WEIGHT_RECENCY * _recency(memory, now)
        + WEIGHT_TYPE_AFFINITY * affinity
    )


def _is_expired(memory: UserMemoryV4, now: datetime) -> bool:
    return memory.expires_at is not None and memory.expires_at < now


def retrieve_v4(
    user_id: str,
    user_input: str,
    character_id: str = "asuna",
    top_k: int | None = None,
) -> list[UserMemoryV4]:
    settings = get_settings()
    limit = top_k or settings.memory_top_k
    now = datetime.now()
    try:
        candidates = repo.list_active_v4(user_id, character_id, limit=200)
    except (ValueError, OSError, RuntimeError):
        logger.exception("记忆检索失败，降级为空列表")
        return []
    candidates = [m for m in candidates if not _is_expired(m, now)]
    if not candidates:
        return []
    query_types = _detect_query_types(user_input)
    scored = [
        (_score_memory(memory, user_input, query_types, now), memory)
        for memory in candidates
    ]
    passed = [
        (score, memory) for score, memory in scored if score >= settings.memory_min_score
    ]
    passed.sort(key=lambda item: (-item[0], -item[1].importance))
    results = [memory for _, memory in passed[:limit]]
    if not results:
        fallback = max(candidates, key=lambda memory: memory.importance)
        results = [fallback]
    try:
        repo.touch_last_accessed([memory.id for memory in results])
    except (ValueError, OSError, RuntimeError):
        logger.exception("last_accessed_at 回写失败，可容忍")
    return results
