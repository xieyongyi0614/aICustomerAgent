"""Memory 2.0 混合检索与排序（MEM-006）。

语义（cosine）+ 结构化（recency/importance/salience）+ 类型亲和混合打分；
向量路 ANN top-N ∪ 结构路 list_active 池合并去重后统一打分。query 或行向量
缺席自动降级纯结构化；被拒/被纠正冷却期（24h）条目硬过滤并记 trace 原因。
reinforce 命中只投 MEM-005 缓冲，读路径零直写。Flag OFF 时本模块不被调用。
"""

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.chains import memory_query_rewrite_chain as memory_query_rewrite
from app.chains import memory_rerank_chain as memory_rerank
from app.core import timeutil
from app.core.db import Memory, MemoryCandidateRow, MemoryLinkRow, SessionLocal
from app.core.settings import get_settings
from app.models.memory import UserMemory
from app.repositories import memory_repository
from app.services.memory import embeddings as memory_embeddings
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import types as memory_types
from app.engines.memory_conflict import same_topic

logger = logging.getLogger(__name__)

STEP_NAME = "memory_retrieve_v2"

MODE_HYBRID = "hybrid"
MODE_STRUCTURED = "structured"
MODE_DEGRADED = "degraded"

RERANK_MODE_OFF = "off"
RERANK_MODE_LITE = "lite"

REWRITE_MODE_OFF = "off"
REWRITE_MODE_LITE = "lite"

VISIBILITY_HYPOTHETICAL = "hypothetical"
STATUS_ACTIVE = "active"
STATUS_CANDIDATE_REJECTED = "rejected"
RELATION_CONTRADICTS = "contradicts"

TEMPORAL_QUERY_KEYWORDS = (
    "什么时候",
    "多久",
    "上次",
    "最近",
    "昨天",
    "前天",
    "上周",
    "之前",
    "哪天",
    "几号",
)

_DEFAULT_SALIENCE = 0.5


@dataclass
class RankedMemory:
    memory: UserMemory
    semantic: float = 0.0
    structured: float = 0.0
    affinity: float = 0.0
    penalty: float = 0.0
    score: float = 0.0
    reason: str = ""
    rerank_score: float | None = None
    matched_queries: str = ""


@dataclass
class RankedMemories:
    items: list[RankedMemory] = field(default_factory=list)
    mode: str = MODE_STRUCTURED
    rerank_mode: str = RERANK_MODE_OFF
    rewrite_mode: str = REWRITE_MODE_OFF

    def memories(self) -> list[UserMemory]:
        return [item.memory for item in self.items]


def _detect_query_types(query: str) -> set[str]:
    return {
        memory_type
        for memory_type, keywords in memory_types.TYPE_AFFINITY_KEYWORDS.items()
        if any(keyword in query for keyword in keywords)
    }


def _is_temporal_query(query: str) -> bool:
    return any(keyword in query for keyword in TEMPORAL_QUERY_KEYWORDS)


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_left * norm_right)))


def _recency(memory: UserMemory, now: datetime) -> float:
    settings = get_settings()
    reference = timeutil.ensure_aware(memory.last_accessed_at or memory.created_at)
    now = timeutil.ensure_aware(now)
    days = max((now - reference).total_seconds() / 86400, 0.0)
    return 0.5 ** (days / settings.memory_recency_half_life_days)


def _structured_score(memory: UserMemory, salience: float | None, now: datetime) -> float:
    recency = _recency(memory, now)
    importance = memory.importance if memory.importance is not None else 0.5
    salience_value = salience if salience is not None else _DEFAULT_SALIENCE
    return (recency + importance + salience_value) / 3.0


def _affinity_score(memory: UserMemory, query_types: set[str]) -> float:
    if not query_types:
        return 0.5
    memory_type = memory_types.normalize_type(memory.type)
    return 1.0 if memory_type is not None and memory_type in query_types else 0.0


def _recently_rejected_contents(user_id: str, now: datetime) -> list[str]:
    cutoff = now - timedelta(hours=get_settings().memory_rejected_cooldown_hours)
    with SessionLocal() as session:
        rows = (
            session.query(MemoryCandidateRow.content)
            .filter(
                MemoryCandidateRow.user_id == user_id,
                MemoryCandidateRow.status == STATUS_CANDIDATE_REJECTED,
                MemoryCandidateRow.created_at >= cutoff,
            )
            .all()
        )
        return [row[0] for row in rows if row[0]]


def _contradicts_cooldown_ids(user_id: str, now: datetime) -> set[str]:
    """被纠正未满冷却期的 contradicts 对侧：对侧行已离开 active 且 24h 内被处置。"""
    cutoff = now - timedelta(hours=get_settings().memory_rejected_cooldown_hours)
    with SessionLocal() as session:
        actives = (
            session.query(Memory)
            .filter(Memory.user_id == user_id, Memory.status == STATUS_ACTIVE)
            .all()
        )
        active_ids = {row.id for row in actives}
        if not active_ids:
            return set()
        rows = (
            session.query(MemoryLinkRow)
            .filter(MemoryLinkRow.relation == RELATION_CONTRADICTS)
            .all()
        )
        cooled: set[str] = set()
        for link in rows:
            counterpart_id = None
            if link.memory_id in active_ids:
                counterpart_id = link.related_memory_id
            elif link.related_memory_id in active_ids:
                counterpart_id = link.memory_id
            if counterpart_id is None:
                continue
            counterpart = session.get(Memory, counterpart_id)
            if counterpart is None or counterpart.status == STATUS_ACTIVE:
                continue
            resolved_at = timeutil.ensure_aware(
                counterpart.updated_at or counterpart.created_at
            )
            if resolved_at >= cutoff:
                survivor = (
                    link.memory_id
                    if link.memory_id in active_ids
                    else link.related_memory_id
                )
                cooled.add(survivor)
        return cooled


def _filter_reasons(
    memory: UserMemory,
    rejected_contents: list[str],
    cooldown_ids: set[str],
) -> str | None:
    if memory.id in cooldown_ids:
        return "contradicts_cooldown"
    for rejected in rejected_contents:
        if _same_topic(memory.content or "", rejected):
            return "recently_rejected"
    return None


def _same_topic(left: str, right: str) -> bool:
    return same_topic(left, right)


def _row_facts(memory_ids: list[str]) -> dict[str, dict]:
    """批量读取 salience / embedding / visibility（DB 为 SoT，向量列可 NULL）。"""
    if not memory_ids:
        return {}
    facts: dict[str, dict] = {}
    with SessionLocal() as session:
        rows = (
            session.query(Memory.id, Memory.salience, Memory.embedding, Memory.visibility)
            .filter(Memory.id.in_(memory_ids))
            .all()
        )
        for memory_id, salience, embedding, visibility in rows:
            facts[memory_id] = {
                "salience": salience,
                "embedding": _parse_vector(embedding),
                "visibility": visibility,
            }
    return facts


def _parse_vector(value) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, list) else None
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _weighted_score(
    semantic: float,
    structured: float,
    affinity: float,
    memory: UserMemory,
    now: datetime,
    temporal: bool,
) -> float:
    settings = get_settings()
    score = (
        settings.memory_weight_semantic * semantic
        + settings.memory_weight_structured * structured
        + settings.memory_weight_affinity * affinity
    )
    if temporal:
        score += settings.memory_temporal_recency_boost * _recency(memory, now)
    return score


def _score_all(
    memories: list[UserMemory],
    facts: dict[str, dict],
    query_embedding: list[float] | None,
    query_types: set[str],
    now: datetime,
    temporal: bool = False,
) -> list[RankedMemory]:
    ranked = []
    for memory in memories:
        fact = facts.get(memory.id, {})
        embedding = fact.get("embedding")
        semantic = 0.0
        if query_embedding is not None and embedding is not None:
            semantic = _cosine(query_embedding, embedding)
        structured = _structured_score(memory, fact.get("salience"), now)
        affinity = _affinity_score(memory, query_types)
        score = _weighted_score(semantic, structured, affinity, memory, now, temporal)
        ranked.append(
            RankedMemory(
                memory=memory,
                semantic=semantic,
                structured=structured,
                affinity=affinity,
                score=score,
            )
        )
    return ranked


def _rerank_sort_key(item: RankedMemory):
    has_rerank = item.rerank_score is not None
    return (
        0 if has_rerank else 1,
        -(item.rerank_score or 0.0),
        -item.score,
        -item.memory.importance,
        item.memory.id,
    )


def _maybe_rerank(
    query: str, ranked: list[RankedMemory], settings
) -> tuple[list[RankedMemory], str]:
    if settings.memory_rerank_mode != RERANK_MODE_LITE:
        return ranked, RERANK_MODE_OFF
    if len(ranked) < settings.memory_rerank_min_candidates:
        return ranked, RERANK_MODE_OFF
    pool = ranked[: settings.memory_rerank_top_k]
    candidates = [(item.memory.id, item.memory.content or "") for item in pool]
    try:
        scored = memory_rerank.rerank_memories_sync(query, candidates)
    except Exception as exc:
        logger.warning("记忆重排失败，降级既有排序：%s", exc.__class__.__name__)
        return ranked, RERANK_MODE_OFF
    by_id = {item.memory.id: item for item in ranked}
    applied = 0
    for entry in scored:
        target = by_id.get(entry.id)
        if target is None:
            continue
        target.rerank_score = float(entry.score)
        applied += 1
    if not applied:
        return ranked, RERANK_MODE_OFF
    return sorted(ranked, key=_rerank_sort_key), RERANK_MODE_LITE


def _recall(
    user_id: str, character_id: str, query_text: str, now: datetime
) -> tuple[list[RankedMemory], str, int]:
    """单 query 召回（结构路 ∪ 向量路）+ 逐候选分量；返回 (ranked, mode, pool_size)。"""
    pool = _candidate_pool(user_id, character_id)
    facts = _row_facts([memory.id for memory in pool])
    pool = [m for m in pool if facts.get(m.id, {}).get("visibility") != VISIBILITY_HYPOTHETICAL]
    query_embedding = None
    mode = MODE_STRUCTURED
    if query_text:
        query_embedding = memory_embeddings.embed_query(query_text)
        if query_embedding is not None:
            mode = MODE_HYBRID
            vector_hits = _vector_recall(user_id, character_id, query_embedding)
            known = {memory.id for memory in pool}
            extra = [m for m in vector_hits if m.id not in known]
            pool = pool + extra
            facts.update(_row_facts([m.id for m in extra]))
            pool = [m for m in pool if facts.get(m.id, {}).get("visibility") != VISIBILITY_HYPOTHETICAL]
        elif pool:
            mode = MODE_DEGRADED

    query_types = _detect_query_types(query_text)
    ranked = _score_all(
        pool, facts, query_embedding, query_types, now, temporal=_is_temporal_query(query_text)
    )
    return ranked, mode, len(pool)


def _merge_ranked(
    ranked_lists: list[list[RankedMemory]], now: datetime, temporal: bool
) -> list[RankedMemory]:
    """多路归并：按 memory.id 去重，分量与惩罚取最大，score 用同一公式与权重重算。

    `matched_queries` 记录命中该记忆的 query 序号（`q0` = 原 query），供 MEV-004 归因。
    """
    merged: dict[str, RankedMemory] = {}
    order: list[str] = []
    hits: dict[str, list[str]] = {}
    for index, ranked in enumerate(ranked_lists):
        tag = f"q{index}"
        for item in ranked:
            memory_id = item.memory.id
            target = merged.get(memory_id)
            if target is None:
                target = RankedMemory(memory=item.memory)
                merged[memory_id] = target
                order.append(memory_id)
                hits[memory_id] = []
            target.semantic = max(target.semantic, item.semantic)
            target.structured = max(target.structured, item.structured)
            target.affinity = max(target.affinity, item.affinity)
            target.penalty = max(target.penalty, item.penalty)
            if tag not in hits[memory_id]:
                hits[memory_id].append(tag)

    merged_items: list[RankedMemory] = []
    for memory_id in order:
        item = merged[memory_id]
        item.score = _weighted_score(
            item.semantic, item.structured, item.affinity, item.memory, now, temporal
        )
        item.matched_queries = ",".join(hits[memory_id])
        merged_items.append(item)
    return merged_items


def _merge_mode(modes: list[str]) -> str:
    if MODE_HYBRID in modes:
        return MODE_HYBRID
    if MODE_DEGRADED in modes:
        return MODE_DEGRADED
    return MODE_STRUCTURED


def _resolve_queries(query_text: str, settings) -> tuple[list[str], str]:
    """解析本次检索的 query 集合：`lite` 且改写返回非空才扩多路，否则单路 + `off`。"""
    if settings.memory_query_rewrite_mode != REWRITE_MODE_LITE or not query_text:
        return [query_text], REWRITE_MODE_OFF
    try:
        rewritten = memory_query_rewrite.rewrite_queries_sync(query_text)
    except Exception as exc:
        logger.warning("记忆查询改写失败，回落单 query：%s", exc.__class__.__name__)
        return [query_text], REWRITE_MODE_OFF
    if not rewritten:
        return [query_text], REWRITE_MODE_OFF
    return [query_text, *rewritten], REWRITE_MODE_LITE


def retrieve(
    user_id: str,
    query: str,
    character_id: str = "asuna",
    top_k: int | None = None,
    trace=None,
) -> RankedMemories:
    started = time.perf_counter()
    settings = get_settings()
    limit = top_k or settings.memory_top_k
    now = timeutil.now()
    query_text = (query or "").strip()

    queries, rewrite_mode = _resolve_queries(query_text, settings)
    if len(queries) > 1:
        recalls = [_recall(user_id, character_id, text, now) for text in queries]
        ranked = _merge_ranked(
            [items for items, _, _ in recalls],
            now,
            temporal=any(_is_temporal_query(text) for text in queries),
        )
        mode = _merge_mode([recall_mode for _, recall_mode, _ in recalls])
        pool_size = len(ranked)
    else:
        ranked, mode, pool_size = _recall(user_id, character_id, query_text, now)

    rejected_contents = _recently_rejected_contents(user_id, now) if pool_size else []
    cooldown_ids = _contradicts_cooldown_ids(user_id, now) if pool_size else set()

    kept: list[RankedMemory] = []
    filtered: list[RankedMemory] = []
    for item in ranked:
        reason = _filter_reasons(item.memory, rejected_contents, cooldown_ids)
        if reason is not None:
            item.penalty = (
                settings.memory_penalty_rejected
                if reason == "recently_rejected"
                else settings.memory_penalty_contradicts
            )
            item.reason = reason
            filtered.append(item)
            continue
        kept.append(item)
    kept.sort(key=lambda item: (-item.score, -item.memory.importance))
    kept, rerank_mode = _maybe_rerank(query_text, kept, settings)
    kept = kept[:limit]
    result = RankedMemories(
        items=kept, mode=mode, rerank_mode=rerank_mode, rewrite_mode=rewrite_mode
    )

    for item in kept:
        memory_lifecycle.record_reinforce(item.memory.id)
    _trace(
        trace,
        started,
        mode=mode,
        rerank_mode=rerank_mode,
        rewrite_mode=rewrite_mode,
        queries_count=len(queries),
        matched_queries=[
            {"id": item.memory.id, "queries": item.matched_queries}
            for item in kept
            if item.matched_queries
        ],
        pool_size=pool_size,
        returned=[_item_digest(item) for item in kept],
        filtered=[_item_digest(item) for item in filtered],
    )
    return result


def _vector_recall(
    user_id: str, character_id: str, query_embedding: list[float]
) -> list[UserMemory]:
    try:
        return memory_repository.search_by_vector(
            user_id,
            character_id,
            query_embedding,
            limit=get_settings().memory_vector_recall_k,
        )
    except Exception as exc:
        logger.warning("向量召回失败，降级结构化：%s", exc.__class__.__name__)
        return []


def _candidate_pool(user_id: str, character_id: str) -> list[UserMemory]:
    settings = get_settings()
    try:
        pool = memory_repository.list_active(
            user_id, character_id, limit=settings.memory_candidate_pool_limit
        )
    except Exception:
        logger.exception("记忆候选池读取失败，本轮检索降级为空")
        return []
    return [
        memory
        for memory in pool
        if memory.status == STATUS_ACTIVE and memory.content and memory.superseded_by is None
    ]


def _item_digest(item: RankedMemory) -> dict:
    return {
        "id": item.memory.id,
        "semantic": round(item.semantic, 4),
        "structured": round(item.structured, 4),
        "affinity": round(item.affinity, 4),
        "score": round(item.score, 4),
        **({"rerank_score": round(item.rerank_score, 4)} if item.rerank_score is not None else {}),
        **({"matched_queries": item.matched_queries} if item.matched_queries else {}),
        **({"penalty_reason": item.reason} if item.reason else {}),
    }


def _trace(trace, started: float, **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, "ok", **extra)
