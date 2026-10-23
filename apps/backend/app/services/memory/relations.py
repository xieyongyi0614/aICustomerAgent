"""MEV-010 记忆关系抽取：无链接 active 记忆 → lite LLM 判定三义 → 写 `memory_links`。

设计要点（`docs/version/v6.0.0/tasks/MEV-010.md` §4）：

- 只写 `caused_by` / `before` / `related`；既有冲突三义由 `on_promoted` 独占（D1）；
- anchor = 「尚无任何链接」的 active 记忆（出边 / 入边都没有，D3），天然幂等、可续跑；
- 候选优先向量近邻，向量不可用回落 `same_topic` + 同类型近期（D7）；
- 候选外 id / 白名单外关系由链 fail-closed 丢弃（D4）；
- 写入经 `lifecycle.create_relation_link`（白名单 + `_link_exists` 去重）；
- 单条 anchor 失败隔离，整体不抛；`mode=off` 零查库、零 LLM；
- job 幂等键锚定 anchor id（`memory_link:{id}`，D6）。

链接只读面由 `MEV-009` 的 `memory_repository.list_links` 提供，并已双向匹配；
因此反向链接（A→B）以 B 为种子做 1-hop 也能命中 A。
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.chains.memory_link_chain import extract_links_with_stats
from app.core import timeutil
from app.core.db import BackgroundJobRow, Memory, SessionLocal
from app.core.settings import get_settings
from app.engines.memory_conflict import same_topic
from app.repositories import background_job_repository, memory_repository
from app.services.memory import embeddings as memory_embeddings
from app.services.memory import lifecycle as memory_lifecycle

logger = logging.getLogger(__name__)

STEP_NAME = "memory_relation_extract"

JOB_TYPE_MEMORY_LINK_EXTRACT = "memory_link_extract"
MODE_AUTO = "auto"

_STAT_KEYS = (
    "candidates",
    "extracted",
    "wrote",
    "duplicates",
    "ignored_existing_relations",
    "unknown_ids",
    "skipped_no_candidates",
    "failed",
)


def _empty_stats() -> dict:
    stats = {"anchors": 0}
    stats.update({key: 0 for key in _STAT_KEYS})
    return stats


def _linked_neighbor_ids(anchor_id: str) -> set[str]:
    links = memory_repository.list_links([anchor_id])
    return {neighbor for seed, neighbor, _ in links if seed == anchor_id}


def _select_unlinked_anchors(limit: int) -> list:
    """选材：active 且无任何出/入链接、且尚无抽取 job 的记忆（按创建时间升序）。"""
    settings = get_settings()
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.status == "active")
            .order_by(Memory.created_at.asc(), Memory.id.asc())
            .limit(settings.memory_candidate_pool_limit)
            .all()
        )
        existing_keys = {
            key
            for (key,) in session.query(BackgroundJobRow.idempotency_key)
            .filter(BackgroundJobRow.job_type == JOB_TYPE_MEMORY_LINK_EXTRACT)
            .all()
        }
        for row in rows:
            session.expunge(row)
    if not rows:
        return []
    links = memory_repository.list_links([row.id for row in rows])
    linked = {seed for seed, _, _ in links} | {neighbor for _, neighbor, _ in links}
    anchors = []
    for row in rows:
        if row.id in linked:
            continue
        if f"memory_link:{row.id}" in existing_keys:
            continue
        anchors.append(row)
        if len(anchors) >= limit:
            break
    return anchors


def _vector_candidates(anchor, limit: int) -> list:
    embedding = memory_embeddings.embed_query(anchor.content or "")
    if not embedding:
        return []
    try:
        candidates = memory_repository.search_by_vector(
            anchor.user_id,
            anchor.character_id,
            embedding,
            limit=max(limit * 3, limit),
        )
    except Exception as exc:
        logger.warning("关系抽取向量候选失败，回落同题：%s", exc.__class__.__name__)
        return []
    return [
        memory
        for memory in candidates
        if memory.id != anchor.id and memory.status == "active"
    ]


def _fallback_candidates(anchor, limit: int, linked: set[str]) -> list:
    pool = memory_repository.list_active(
        anchor.user_id,
        anchor.character_id,
        limit=get_settings().memory_candidate_pool_limit,
    )
    scored = []
    for memory in pool:
        if memory.id == anchor.id or memory.id in linked:
            continue
        if memory.status != "active":
            continue
        same = same_topic(anchor.content or "", memory.content or "")
        same_type = memory.type == anchor.type
        if not (same or same_type):
            continue
        scored.append(
            (
                0 if same else 1,
                -memory.created_at.timestamp(),
                memory.id,
                memory,
            )
        )
    scored.sort(key=lambda entry: entry[:3])
    return [entry[3] for entry in scored[:limit]]


def _candidate_memories(anchor, limit: int) -> list:
    linked = _linked_neighbor_ids(anchor.id)
    vector_candidates = _vector_candidates(anchor, limit)
    candidates = [memory for memory in vector_candidates if memory.id not in linked]
    if candidates:
        return candidates[:limit]
    return _fallback_candidates(anchor, limit, linked)


def run_extract(anchor_id: str, llm=None, trace=None) -> dict:
    """抽取单条 anchor；门控在入口（off → 零查库、零 LLM）。"""
    started = time.perf_counter()
    stats = _empty_stats()
    settings = get_settings()
    if settings.memory_link_extract_mode != MODE_AUTO:
        return stats

    anchor = memory_repository.get_memory(anchor_id)
    if anchor is None or anchor.status != "active":
        return stats
    stats["anchor_id"] = anchor_id

    candidates = _candidate_memories(anchor, settings.memory_link_candidate_k)
    stats["candidates"] = len(candidates)
    if not candidates:
        stats["skipped_no_candidates"] = 1
        _trace(trace, started, **stats)
        return stats

    try:
        items, chain_stats = asyncio.run(
            extract_links_with_stats(
                anchor.content or "",
                [(memory.id, memory.content or "") for memory in candidates],
                llm,
            )
        )
    except Exception:
        stats["failed"] = 1
        logger.warning("关系抽取失败，跳过：anchor=%s", anchor_id, exc_info=True)
        _trace(trace, started, **stats)
        return stats

    stats["extracted"] = len(items)
    stats["ignored_existing_relations"] = chain_stats.get(
        "ignored_existing_relations", 0
    )
    stats["unknown_ids"] = chain_stats.get("unknown_ids", 0)

    for item in items:
        try:
            created = memory_lifecycle.create_relation_link(
                anchor.id,
                item.related_memory_id,
                item.relation,
                trace=trace,
            )
        except Exception:
            stats["failed"] += 1
            logger.warning(
                "关系写入失败，跳过：anchor=%s related=%s",
                anchor.id,
                item.related_memory_id,
                exc_info=True,
            )
            continue
        if created:
            stats["wrote"] += 1
        else:
            stats["duplicates"] += 1

    _trace(trace, started, **stats)
    return stats


def extract_once(llm=None, trace=None) -> dict:
    """批量抽取一轮（tick / 无 payload 的 job 共用）；单条失败隔离。"""
    stats = _empty_stats()
    settings = get_settings()
    if settings.memory_link_extract_mode != MODE_AUTO:
        return stats
    try:
        anchors = _select_unlinked_anchors(settings.memory_link_max_per_run)
    except Exception:
        logger.exception("关系抽取选材失败，跳过本轮")
        return stats
    stats["anchors"] = len(anchors)
    for anchor in anchors:
        try:
            item_stats = run_extract(anchor.id, llm=llm, trace=trace)
        except Exception:
            stats["failed"] += 1
            logger.warning("关系抽取单条失败，跳过：anchor=%s", anchor.id, exc_info=True)
            continue
        for key in _STAT_KEYS:
            stats[key] += item_stats.get(key, 0)
    return stats


def enqueue_extract(memory_id: str, now=None) -> bool:
    """按 anchor 入队；幂等键锚定记忆 id（同一记忆只抽一次）。"""
    if get_settings().memory_link_extract_mode != MODE_AUTO:
        return False
    return background_job_repository.enqueue_job(
        JOB_TYPE_MEMORY_LINK_EXTRACT,
        {"memory_id": memory_id},
        f"memory_link:{memory_id}",
        run_at=now,
    )


def run_extract_tick(now=None) -> dict:
    """周期 hook：`mode != auto` → 零动作（不查库、不入队）。"""
    if get_settings().memory_link_extract_mode != MODE_AUTO:
        return {"enqueued": 0}
    moment = now or timeutil.now()
    try:
        anchors = _select_unlinked_anchors(
            get_settings().memory_link_max_per_run
        )
    except Exception:
        logger.exception("关系抽取选材失败，跳过本轮")
        return {"enqueued": 0}
    enqueued = 0
    for anchor in anchors:
        try:
            if enqueue_extract(anchor.id, now=moment):
                enqueued += 1
        except Exception:
            logger.warning("关系抽取入队失败：anchor=%s", anchor.id, exc_info=True)
    return {"enqueued": enqueued}


def run_extract_job(memory_id: str | None = None) -> dict:
    """job handler：有 payload 处理单条 anchor；无 payload 走一轮批量。"""
    if get_settings().memory_link_extract_mode != MODE_AUTO:
        return _empty_stats()
    if memory_id:
        return run_extract(memory_id)
    return extract_once()


def _trace(trace, started: float, **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, "ok", **extra)
