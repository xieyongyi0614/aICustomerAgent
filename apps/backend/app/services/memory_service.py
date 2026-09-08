import asyncio
import logging
import time
from datetime import datetime

from app.chains.extractor_chain import extract_candidates
from app.core.logutils import content_preview
from app.core.settings import get_settings
from app.models.memory import MemoryCandidate, UserMemory
from app.repositories import memory_repository as repo
from app.services.memory_conflict import (
    ACTION_DISCARD_PAIR,
    ACTION_INVALIDATE,
    ACTION_NOOP,
    ACTION_SAVE,
    ACTION_SUPERSEDE,
    ACTION_UPDATE,
    resolve_batch,
)
from app.services.memory_policy import apply_policy
from app.application.worker_loop import run_worker_loop
from app.services import trigger_evaluator

logger = logging.getLogger(__name__)

TYPE_AFFINITY_KEYWORDS = {
    "user_preference": ("喜欢", "讨厌", "偏好", "爱", "不爱", "不喜欢", "讨厌"),
    "user_fact": ("在哪", "工作", "住", "养", "做什么", "是谁"),
    "important_event": ("面试", "经历", "发生过", "事件", "考试"),
    "relationship_event": ("我们", "一起", "送过", "看过", "去过"),
}


def _tokenize(text: str) -> set[str]:
    return set(ch for ch in text if ch.strip())


def _trace_step(trace, name: str, started: float, error: str | None = None) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    if error is not None:
        trace.record(name, duration, "error", error=error)
    else:
        trace.record(name, duration)


async def extract_and_save(
    user_id: str,
    user_input: str,
    ai_reply: str,
    llm=None,
    trace=None,
    recent_context: str = "",
    character_id: str = "asuna",
) -> None:
    started = time.perf_counter()
    try:
        extraction = await extract_candidates(
            user_input, ai_reply, recent_context=recent_context, llm=llm
        )
    except Exception as exc:
        logger.exception("记忆提取失败，丢弃本轮，不重试")
        _trace_step(trace, "memory_extract", started, error=exc.__class__.__name__)
        return
    _trace_step(trace, "memory_extract", started)
    candidates = extraction.candidates
    if not candidates:
        return

    try:
        active = repo.list_active(user_id, character_id, limit=200)
    except Exception:
        logger.exception("记忆读取失败，冲突比对降级为空")
        active = []
    started_policy = time.perf_counter()
    try:
        report = apply_policy(candidates, [m.content for m in active])
    except Exception as exc:
        logger.exception("记忆策略执行失败，丢弃本轮候选")
        _trace_step(trace, "memory_policy", started_policy, error=exc.__class__.__name__)
        return
    _trace_step(trace, "memory_policy", started_policy)

    for item in report.privacy_items:
        await _execute_forget(user_id, character_id, item, trace)
    saved = report.saved
    if not saved:
        return

    started_conflict = time.perf_counter()
    try:
        outcomes = resolve_batch(saved, active)
    except Exception as exc:
        logger.exception("记忆冲突处理失败，本轮候选丢弃")
        _trace_step(trace, "memory_conflict", started_conflict, error=exc.__class__.__name__)
        return
    _trace_step(trace, "memory_conflict", started_conflict)
    for outcome in outcomes:
        await _execute_outcome(user_id, character_id, outcome)
    _register_followups(user_id, saved)


def _register_followups(user_id: str, saved) -> None:
    """V7-010：带时间语义的事件记忆 → scheduled_followup 登记（内存，丢失可接受）。"""
    from datetime import datetime, timedelta


    now = datetime.now()
    for memory in saved:
        keyword = trigger_evaluator.find_followup_event(memory.content or "")
        if keyword is None:
            continue
        due = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        try:
            trigger_evaluator.register_followup(
                user_id, due, f"{keyword}近况跟进"
            )
            logger.info("scheduled_followup 登记：%s due=%s", keyword, due)
        except Exception:
            logger.exception("followup 登记失败，跳过")


FORGET_MAX_ATTEMPTS = 2


async def _execute_forget(
    user_id: str, character_id: str, item: MemoryCandidate, trace=None
) -> None:
    for attempt in range(1, FORGET_MAX_ATTEMPTS + 1):
        try:
            active = repo.list_active(user_id, character_id, limit=200)
            target = (item.content or "").strip()
            matched = [
                memory
                for memory in active
                if target
                and (
                    target == memory.content.strip()
                    or target in memory.content
                    or memory.content in target
                )
            ]
            if not matched:
                logger.warning(
                    "forget 未匹配到任何记忆，不猜测删除：预览=%s",
                    content_preview(item.content),
                )
                if trace is not None:
                    trace.record(
                        "memory_privacy", 0.0, "miss", error="forget target not found"
                    )
                return
            for memory in matched:
                repo.forget_memory(memory.id)
            if trace is not None:
                trace.record("memory_privacy", 0.0)
            return
        except Exception as exc:
            logger.exception("forget 执行失败（第 %d 次）", attempt)
            if attempt == FORGET_MAX_ATTEMPTS:
                if trace is not None:
                    trace.record(
                        "memory_privacy",
                        0.0,
                        "error",
                        error=exc.__class__.__name__,
                    )
                logger.error(
                    "用户遗忘指令执行失败已重试仍失败，需人工关注：预览=%s",
                    content_preview(item.content),
                )


async def _execute_outcome(
    user_id: str, character_id: str, outcome
) -> None:
    candidate = outcome.candidate
    try:
        if outcome.action == ACTION_SAVE:
            repo.create_memory(
                user_id,
                character_id,
                candidate.content,
                candidate.type,
                candidate.importance,
                confidence=candidate.confidence,
                source=candidate.source,
            )
        elif outcome.action == ACTION_UPDATE:
            repo.update_memory_content(
                outcome.target_id, candidate.content, candidate.importance
            )
        elif outcome.action == ACTION_SUPERSEDE:
            repo.create_memory_and_supersede(
                user_id,
                character_id,
                candidate.content,
                candidate.type,
                candidate.importance,
                confidence=candidate.confidence,
                source=candidate.source,
                superseded_id=outcome.target_id,
            )
        elif outcome.action == ACTION_INVALIDATE:
            repo.invalidate_memory(outcome.target_id)
        elif outcome.action == ACTION_DISCARD_PAIR:
            logger.warning(
                "同轮候选矛盾成对丢弃：预览=%s", content_preview(candidate.content)
            )
        elif outcome.action == ACTION_NOOP:
            logger.info("候选无可执行动作：预览=%s", content_preview(candidate.content))
    except Exception:
        logger.exception("记忆写入失败，单条候选丢弃，不影响其他候选")


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


def _recency(memory: UserMemory, now: datetime) -> float:
    settings = get_settings()
    reference = memory.last_accessed_at or memory.created_at
    reference = reference.replace(tzinfo=None) if reference.tzinfo else reference
    days = max((now - reference).total_seconds() / 86400, 0)
    return 0.5 ** (days / settings.memory_recency_half_life_days)


def _score_memory(
    memory: UserMemory, user_input: str, query_types: set[str], now: datetime
) -> float:
    settings = get_settings()
    affinity = (
        0.5
        if not query_types
        else (1.0 if memory.type in query_types else 0.0)
    )
    return (
        settings.memory_weight_lexical * _lexical_overlap(user_input, memory.content)
        + settings.memory_weight_importance * memory.importance
        + settings.memory_weight_recency * _recency(memory, now)
        + settings.memory_weight_type_affinity * affinity
    )


def _is_expired(memory: UserMemory, now: datetime) -> bool:
    return memory.expires_at is not None and memory.expires_at < now


def retrieve(
    user_id: str,
    user_input: str,
    character_id: str = "asuna",
    top_k: int | None = None,
) -> list[UserMemory]:
    settings = get_settings()
    limit = top_k or settings.memory_top_k
    now = datetime.now()
    try:
        candidates = repo.list_active(
            user_id, character_id, limit=settings.memory_candidate_pool_limit
        )
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


def _is_duplicate_content(content: str, seen: list[str]) -> bool:
    normalized = content.strip()
    return any(
        normalized == existing or normalized in existing or existing in normalized
        for existing in seen
    )


def reclaim_expired_memories(now: datetime | None = None) -> int:
    now = now or datetime.now()
    try:
        expired = repo.list_expired_active(
            now, limit=get_settings().memory_reclaim_batch_limit
        )
    except (ValueError, OSError, RuntimeError):
        logger.exception("过期记忆读取失败，本轮回收跳过")
        return 0
    for memory in expired:
        try:
            repo.invalidate_memory(memory.id)
        except (ValueError, OSError, RuntimeError):
            logger.exception("过期记忆失效失败：%s", memory.id)
    if expired:
        logger.info("过期记忆回收：%d 条", len(expired))
    return len(expired)


async def run_memory_reclaim_loop(interval_seconds: int | None = None) -> None:
    interval = (
        interval_seconds
        if interval_seconds is not None
        else get_settings().memory_reclaim_interval_seconds
    )
    await run_worker_loop(
        "memory reclaim loop", reclaim_expired_memories, interval, offload=True
    )


def select_for_context(
    memories: list[UserMemory],
    max_count: int | None = None,
    max_chars: int | None = None,
) -> list[UserMemory]:
    settings = get_settings()
    if max_chars is None:
        max_chars = settings.memory_context_char_budget
    limit = max_count or settings.memory_top_k
    selected: list[UserMemory] = []
    seen_contents: list[str] = []
    total_chars = 0
    for memory in memories:
        if len(selected) >= limit:
            break
        content = memory.content
        if not content or _is_duplicate_content(content, seen_contents):
            continue
        if total_chars + len(content) > max_chars:
            continue
        selected.append(memory)
        seen_contents.append(content)
        total_chars += len(content)
    return selected
