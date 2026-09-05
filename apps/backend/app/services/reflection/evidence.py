"""Evidence Window 聚合（REF-002）。

从 memories（active、非 hypothetical）聚合合格证据组：窗口过滤 → 贪心单遍主题
聚类（语义邻域 ∪ same_topic 关键词路）→ 组统计（数量/跨度/独立来源/印证度/
成员 weight）→ 门槛前置判定。纯规则 0 LLM；单条记忆不成组；同数据同分组幂等。
「独立来源」口径 = ≥v2_reflection_min_evidence 个不同 source_ref.id（不同原始
消息/事件），source 类型分布仅作统计与 REF-004 折算输入。
"""

import json
import logging
import math
import time
from datetime import datetime, timedelta

from app.core.db import Memory, SessionLocal
from app.core.settings import get_settings
from app.models.reflection import EvidenceMember, EvidenceWindow, WindowStats
from app.repositories import memory_repository
from app.services.memory_conflict import _lcs_length, same_topic

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_evidence"

VISIBILITY_HYPOTHETICAL = "hypothetical"

_DEFAULT_SALIENCE = 0.5
_COHERENCE_PAIR_SAMPLE = 20
_TOPIC_DIGEST_CHARS = 40

_GATE_EVIDENCE_COUNT = "evidence_count"
_GATE_SPAN = "span"
_GATE_COHERENCE = "coherence"


def _parse_vector(value) -> list[float] | None:
    """embedding 列可能为 str/list/None（同构复刻 memory2/retriever，不 import 私有函数）。"""
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


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_left * norm_right)))


def _topic_similarity(left: str, right: str) -> float:
    longer = max(len(left), len(right))
    if longer == 0:
        return 0.0
    return _lcs_length(left, right) / longer


def _naive(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _row_facts(memory_ids: list[str]) -> dict[str, dict]:
    """批量补读 UserMemory 未携带的生命周期字段（DB 为 SoT）。"""
    facts: dict[str, dict] = {}
    if not memory_ids:
        return facts
    with SessionLocal() as session:
        rows = (
            session.query(
                Memory.id,
                Memory.salience,
                Memory.embedding,
                Memory.visibility,
                Memory.source,
                Memory.source_ref,
                Memory.last_reinforced_at,
                Memory.created_at,
            )
            .filter(Memory.id.in_(memory_ids))
            .all()
        )
        for (
            memory_id,
            salience,
            embedding,
            visibility,
            source,
            source_ref,
            last_reinforced_at,
            created_at,
        ) in rows:
            facts[memory_id] = {
                "salience": salience,
                "embedding": _parse_vector(embedding),
                "visibility": visibility,
                "source": source,
                "source_ref": source_ref,
                "last_reinforced_at": _naive(last_reinforced_at),
                "created_at": _naive(created_at),
            }
    return facts


def _source_identity(memory_id: str, source_ref) -> str:
    if isinstance(source_ref, dict):
        ref_id = source_ref.get("id")
        if ref_id:
            return str(ref_id)
    return f"memory:{memory_id}"


def _member_weight(salience: float | None, reference: datetime | None, now: datetime) -> float:
    half_life = get_settings().memory_recency_half_life_days
    reference = _naive(reference) or now
    days = max((now - reference).total_seconds() / 86400, 0.0)
    recency = 0.5 ** (days / half_life)
    return round((salience if salience is not None else _DEFAULT_SALIENCE) * recency, 6)


def passes_gate(window: EvidenceWindow, settings=None) -> tuple[bool, list[str]]:
    """三闸前置判定（REF-003 复用）：数量（独立来源）/跨度/印证度。"""
    settings = settings or get_settings()
    stats = window.stats
    reasons: list[str] = []
    if stats.distinct_source_refs < settings.v2_reflection_min_evidence:
        reasons.append(_GATE_EVIDENCE_COUNT)
    if stats.span_hours < settings.v2_reflection_min_span_hours:
        reasons.append(_GATE_SPAN)
    if stats.coherence < settings.v2_reflection_min_coherence:
        reasons.append(_GATE_COHERENCE)
    return not reasons, reasons


class _Cluster:
    def __init__(self, member: EvidenceMember, vector: list[float] | None):
        self.members: list[EvidenceMember] = [member]
        self.member_vectors: list[list[float] | None] = [vector]
        self.rep_content = member.content
        self._vectors = [vector] if vector is not None else []
        self.rep_vector = list(vector) if vector is not None else None

    def add(self, member: EvidenceMember, vector: list[float] | None) -> None:
        self.members.append(member)
        self.member_vectors.append(vector)
        if vector is not None:
            self._vectors.append(vector)
            self.rep_vector = [
                sum(values) / len(self._vectors) for values in zip(*self._vectors)
            ]
        if len(member.content) > len(self.rep_content):
            self.rep_content = member.content


def _coherence(cluster: _Cluster) -> float:
    members = cluster.members
    if len(members) < 2:
        return 1.0
    pairs: list[float] = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if len(pairs) >= _COHERENCE_PAIR_SAMPLE:
                break
            left_vector = cluster.member_vectors[i]
            right_vector = cluster.member_vectors[j]
            if left_vector is not None and right_vector is not None:
                pairs.append(_cosine(left_vector, right_vector))
            else:
                pairs.append(_topic_similarity(members[i].content, members[j].content))
    if not pairs:
        return 1.0
    return sum(pairs) / len(pairs)


def _build_window(cluster: _Cluster, degraded: str | None, settings) -> EvidenceWindow:
    members = cluster.members
    for member, vector in zip(members, cluster.member_vectors):
        member.semantic_sim = round(_cosine(vector, cluster.rep_vector), 4)
        member.topic_sim = round(_topic_similarity(member.content, cluster.rep_content), 4)
    created = [member.created_at for member in members]
    span_hours = (
        (max(created) - min(created)).total_seconds() / 3600.0 if len(created) > 1 else 0.0
    )
    distinct_refs = {member.source_ref for member in members}
    type_mix: dict[str, int] = {}
    for member in members:
        type_mix[member.source] = type_mix.get(member.source, 0) + 1
    stats = WindowStats(
        member_count=len(members),
        span_hours=round(span_hours, 4),
        distinct_source_refs=len(distinct_refs),
        source_type_mix=type_mix,
        coherence=round(_coherence(cluster), 4),
    )
    window = EvidenceWindow(
        topic_digest=cluster.rep_content[:_TOPIC_DIGEST_CHARS],
        members=members,
        stats=stats,
        degraded=degraded,
    )
    _, window.gate_reasons = passes_gate(window, settings)
    return window


def aggregate_evidence_windows(
    user_id: str,
    character_id: str = "asuna",
    now: datetime | None = None,
    trace=None,
) -> list[EvidenceWindow]:
    """主入口：候选池 → 聚类 → 组统计 → 门槛判定；异常/空池返回空列表。"""
    started = time.perf_counter()
    now = now or datetime.now()
    try:
        result = _aggregate(user_id, character_id, now)
    except Exception as exc:
        logger.exception("证据聚合异常，按无证据处理")
        _trace(trace, started, status="error", error=f"{exc.__class__.__name__}: {exc}")
        return []
    _trace(
        trace,
        started,
        status="ok",
        pool_size=result["pool_size"],
        clusters=result["clusters"],
        degraded=result["degraded"],
        windows=[_window_digest(window) for window in result["windows"]],
    )
    return result["windows"]


def _aggregate(user_id: str, character_id: str, now: datetime) -> dict:
    settings = get_settings()
    pool = _pool(user_id, character_id, now)
    vector_count = sum(1 for entry in pool if entry["vector"] is not None)
    degraded = "keyword_only" if pool and vector_count == 0 else None

    clusters: list[_Cluster] = []
    ordered = sorted(
        pool,
        key=lambda entry: (entry["salience"], entry["memory"].created_at),
        reverse=True,
    )
    for entry in ordered:
        memory = entry["memory"]
        vector = entry["vector"]
        member = EvidenceMember(
            memory_id=memory.id,
            content=memory.content.strip(),
            created_at=entry["created_at"],
            source=entry["source"],
            source_ref=entry["source_identity"],
            salience=entry["salience"],
            weight=_member_weight(entry["salience"], entry["reference"], now),
        )
        best: _Cluster | None = None
        best_score = -1.0
        for cluster in clusters:
            semantic = _cosine(vector, cluster.rep_vector)
            topic_sim = _topic_similarity(member.content, cluster.rep_content)
            matched = (
                semantic >= settings.v2_reflection_cluster_cosine
                or same_topic(member.content, cluster.rep_content)
            )
            if not matched:
                continue
            score = max(semantic, topic_sim)
            if score > best_score:
                best, best_score = cluster, score
        if best is None:
            clusters.append(_Cluster(member, vector))
        else:
            best.add(member, vector)

    windows = [_build_window(cluster, degraded, settings) for cluster in clusters]
    windows.sort(key=lambda window: (-window.stats.member_count, -window.stats.coherence))
    return {"pool_size": len(pool), "clusters": len(clusters), "windows": windows, "degraded": degraded}


def _pool(user_id: str, character_id: str, now: datetime) -> list[dict]:
    settings = get_settings()
    memories = memory_repository.list_active(
        user_id, character_id, limit=settings.memory_candidate_pool_limit
    )
    facts = _row_facts([memory.id for memory in memories])
    window_start = now - timedelta(days=settings.v2_reflection_window_days)
    candidates: list[dict] = []
    for memory in memories:
        fact = facts.get(memory.id, {})
        if fact.get("visibility") == VISIBILITY_HYPOTHETICAL:
            continue
        content = (memory.content or "").strip()
        if not content or memory.superseded_by is not None:
            continue
        reference = _naive(fact.get("last_reinforced_at")) or _naive(
            fact.get("created_at")
        ) or _naive(memory.created_at)
        if reference < window_start:
            continue
        candidates.append(
            {
                "memory": memory,
                "vector": fact.get("embedding"),
                "salience": fact.get("salience")
                if fact.get("salience") is not None
                else _DEFAULT_SALIENCE,
                "source": fact.get("source") or memory.source,
                "source_identity": _source_identity(memory.id, fact.get("source_ref")),
                "reference": reference,
                "created_at": _naive(fact.get("created_at")) or memory.created_at,
            }
        )
    return candidates


def _window_digest(window: EvidenceWindow) -> dict:
    return {
        "topic_digest": window.topic_digest,
        "member_count": window.stats.member_count,
        "span_hours": window.stats.span_hours,
        "distinct_source_refs": window.stats.distinct_source_refs,
        "coherence": window.stats.coherence,
        "passes_gate": window.passes_gate,
        "gate_reasons": window.gate_reasons,
        "member_ids": [member.memory_id for member in window.members],
    }


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)
