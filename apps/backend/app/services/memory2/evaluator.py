"""Memory 2.0 候选评估器（MEM-003）。

pending 候选三段判定：规则分 ≥ high 转正、< low 拒绝、灰区由 lite LLM 兜底一次。
转正（memories 插入 + candidates.status=approved）单事务完成；hypothetical 候选
直接拒绝且永不调 LLM；显式 remember 候选直通转正（salience=1.0，0 次 LLM）。
LLM 兜底率护栏：滑动窗口仅统计成功兜底（True）与护栏让位（False），超 cap 的
灰区候选留 pending 不调 LLM；LLM 调用失败不占窗口，由候选级失败计数承接，连续
失败达上限转 rejected(reason=llm_failed)。
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from app.chains.structured import build_structured_chain
from app.core.db import Memory, MemoryCandidateRow, SessionLocal
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError, get_settings
from app.models.memory2 import EvaluationVerdict
from app.prompts.memory2_evaluator import build_memory_evaluation_messages
from app.services.memory2 import embeddings as memory_embeddings
from app.services.memory2 import lifecycle as memory_lifecycle
from app.services.memory2 import types as memory2_types
from app.services.memory_conflict import _lcs_length, same_topic
from app.services.memory_service import TYPE_AFFINITY_KEYWORDS

logger = logging.getLogger(__name__)

SOURCE_EXPLICIT_REMEMBER = "explicit_remember"
VISIBILITY_PRIVATE = "private"
VISIBILITY_HYPOTHETICAL = "hypothetical"

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISION_DEFER = "defer"

SOURCE_WEIGHTS = {"user_stated": 1.0, "user_derived": 0.7, "ai_inferred": 0.4}
UNKNOWN_SOURCE_WEIGHT = 0.4

VALID_MEMORY_SOURCES = ("user_stated", "user_derived", "ai_inferred")
_MEMORY_SOURCE_OVERRIDES = {"explicit_remember": "user_stated"}

_LLM_LITE_PROFILE_ID = "lite"
_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_BACKOFF_SECONDS = 0.5
_LLM_MAX_FAILURES = 5
_FALLBACK_RATE_WINDOW = 50
_RELATED_MEMORY_LIMIT = 5

_DEFAULT_PROMOTION_SALIENCE = 0.6
_DEFAULT_PROMOTION_CONFIDENCE = 0.6
_AI_INFERRED_CONFIDENCE_CAP = 0.4
_DEFAULT_DIM_SALIENCE = 0.5

_fallback_window: deque[bool] = deque(maxlen=_FALLBACK_RATE_WINDOW)
_llm_failure_counts: dict[str, int] = {}


class CandidateNotPendingError(Exception):
    def __init__(self, candidate_id: str):
        super().__init__(f"候选已离开 pending 状态: {candidate_id}")
        self.candidate_id = candidate_id


@dataclass
class Decision:
    action: str
    reason: str
    score: float
    llm_used: bool = False
    memory_id: str | None = None
    components: dict = field(default_factory=dict)


def _resolve_llm():
    try:
        return get_llm(_LLM_LITE_PROFILE_ID)
    except SettingsError:
        return get_llm(None)


async def _ask_llm(
    content: str, proposed_type: str, related_contents: list[str], llm=None
) -> EvaluationVerdict:
    model = llm if llm is not None else _resolve_llm()
    chain = build_structured_chain(
        build_memory_evaluation_messages(content, proposed_type, related_contents),
        EvaluationVerdict,
        model,
    )
    return await chain.ainvoke({})


async def _ask_llm_with_retry(
    content: str, proposed_type: str, related_contents: list[str], llm=None
) -> EvaluationVerdict:
    last_exc: Exception | None = None
    for attempt in range(_LLM_RETRY_ATTEMPTS):
        if attempt:
            await asyncio.sleep(_LLM_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        try:
            return await _ask_llm(content, proposed_type, related_contents, llm)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "记忆评估 LLM 调用失败（第 %d 次）：%s", attempt + 1, exc.__class__.__name__
            )
    assert last_exc is not None
    raise last_exc


def _fallback_budget_available() -> bool:
    if not _fallback_window:
        return True
    rate = sum(_fallback_window) / len(_fallback_window)
    return rate <= get_settings().v2_memory_llm_fallback_rate_cap


def _record_llm_failure(candidate_id: str) -> int:
    _llm_failure_counts[candidate_id] = _llm_failure_counts.get(candidate_id, 0) + 1
    return _llm_failure_counts[candidate_id]


def _similarity(left: str, right: str) -> float:
    longer = max(len(left), len(right))
    if longer == 0:
        return 0.0
    return _lcs_length(left, right) / longer


def _novelty(content: str, active_contents: list[str]) -> float:
    if not active_contents:
        return 1.0
    max_similarity = max(_similarity(content, existing) for existing in active_contents)
    return 1.0 - max_similarity


def _type_affinity(content: str, proposed_type: str) -> float:
    hit_types = {
        memory_type
        for memory_type, keywords in TYPE_AFFINITY_KEYWORDS.items()
        if any(keyword in content for keyword in keywords)
    }
    if not hit_types:
        return 0.5
    return 1.0 if proposed_type in hit_types else 0.0


def _score_components(
    candidate: MemoryCandidateRow, content: str, active_contents: list[str]
) -> dict[str, float]:
    settings = get_settings()
    salience = candidate.salience if candidate.salience is not None else _DEFAULT_DIM_SALIENCE
    return {
        "source": settings.v2_memory_eval_weight_source
        * SOURCE_WEIGHTS.get(candidate.source, UNKNOWN_SOURCE_WEIGHT),
        "novelty": settings.v2_memory_eval_weight_novelty
        * _novelty(content, active_contents),
        "affinity": settings.v2_memory_eval_weight_affinity
        * _type_affinity(content, candidate.proposed_type),
        "salience": settings.v2_memory_eval_weight_salience * salience,
    }


def _is_exact_duplicate(content: str, active_contents: list[str]) -> bool:
    return any(content == existing.strip() for existing in active_contents)


def _related_contents(content: str, active_contents: list[str]) -> list[str]:
    related = [existing for existing in active_contents if same_topic(content, existing)]
    return related[:_RELATED_MEMORY_LIMIT]


def _final_type(proposed_type: str | None, llm_suggestion: str | None) -> str:
    """type 终值由代码映射决定：建议类型仅作参考，统一归一化为 v2 规范 7 类。"""
    normalized = memory2_types.normalize_type(proposed_type)
    if normalized is not None:
        return normalized
    normalized = memory2_types.normalize_type(llm_suggestion)
    if normalized is not None:
        return normalized
    return memory2_types.DEFAULT_MEMORY_TYPE


def _memory_source_of(candidate_source: str | None) -> str:
    if candidate_source in _MEMORY_SOURCE_OVERRIDES:
        return _MEMORY_SOURCE_OVERRIDES[candidate_source]
    if candidate_source in VALID_MEMORY_SOURCES:
        return candidate_source
    return "user_derived"


def _importance_of(row: MemoryCandidateRow) -> float:
    source_ref = row.source_ref or {}
    value = source_ref.get("importance")
    if isinstance(value, (int, float)):
        return min(max(float(value), 0.0), 1.0)
    if row.salience is not None:
        return min(max(row.salience, 0.0), 1.0)
    return _DEFAULT_PROMOTION_SALIENCE


def _confidence_of(row: MemoryCandidateRow) -> float:
    source_ref = row.source_ref or {}
    value = source_ref.get("confidence")
    base = (
        min(max(float(value), 0.0), 1.0)
        if isinstance(value, (int, float))
        else _DEFAULT_PROMOTION_CONFIDENCE
    )
    if row.source == "ai_inferred":
        return min(base, _AI_INFERRED_CONFIDENCE_CAP)
    return base


def _promotion_salience(row: MemoryCandidateRow) -> float:
    if row.salience is not None:
        return row.salience
    return _DEFAULT_PROMOTION_SALIENCE


def _promote(
    candidate: MemoryCandidateRow, *, final_type: str, salience: float, reason: str
) -> str:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(MemoryCandidateRow, candidate.id)
        if row is None or row.status != "pending":
            raise CandidateNotPendingError(candidate.id)
        memory_id = str(uuid.uuid4())
        session.add(
            Memory(
                id=memory_id,
                user_id=row.user_id,
                character_id=row.character_id or "*",
                content=row.content,
                type=final_type,
                importance=_importance_of(row),
                confidence=_confidence_of(row),
                source=_memory_source_of(row.source),
                status="active",
                salience=salience,
                last_reinforced_at=now,
                source_ref=row.source_ref,
                visibility=row.visibility or VISIBILITY_PRIVATE,
                created_at=now,
                updated_at=now,
            )
        )
        row.status = "approved"
        row.reason = reason
        session.commit()
        return memory_id


def _enqueue_embedding(memory_id: str, candidate: MemoryCandidateRow) -> None:
    if not get_settings().v2_memory_vector_enabled:
        return
    try:
        memory_embeddings.enqueue(memory_id, candidate.content or "")
    except Exception:
        logger.exception("embedding 入队失败，留待 NULL 补扫：%s", memory_id)


def _after_promotion(
    memory_id: str, candidate: MemoryCandidateRow, trace=None
) -> None:
    source_ref = candidate.source_ref or {}
    try:
        memory_lifecycle.on_promoted(
            memory_id, relation=source_ref.get("relation"), trace=trace
        )
    except Exception:
        logger.exception("转正冲突检测失败，留待补扫：%s", memory_id)
    _enqueue_embedding(memory_id, candidate)


def _promote_or_defer(
    candidate: MemoryCandidateRow,
    *,
    final_type: str,
    salience: float,
    reason: str,
    score: float,
    components: dict | None = None,
    llm_used: bool = False,
    trace=None,
) -> Decision:
    try:
        memory_id = _promote(
            candidate, final_type=final_type, salience=salience, reason=reason
        )
    except CandidateNotPendingError:
        return Decision(
            DECISION_DEFER,
            "not_pending",
            score,
            llm_used=llm_used,
            components=components or {},
        )
    _after_promotion(memory_id, candidate, trace=trace)
    return Decision(
        DECISION_APPROVE,
        reason,
        score,
        llm_used=llm_used,
        memory_id=memory_id,
        components=components or {},
    )


def _mark_rejected(candidate_id: str, reason: str) -> None:
    with SessionLocal() as session:
        row = session.get(MemoryCandidateRow, candidate_id)
        if row is not None and row.status == "pending":
            row.status = "rejected"
            row.reason = reason
            session.commit()


async def _decide_gray_zone(
    candidate: MemoryCandidateRow,
    content: str,
    active_contents: list[str],
    score: float,
    components: dict,
    llm=None,
    trace=None,
) -> Decision:
    if not _fallback_budget_available():
        _fallback_window.append(False)
        return Decision(
            DECISION_DEFER, "llm_fallback_rate_cap", score, components=components
        )
    related = _related_contents(content, active_contents)
    try:
        verdict = await _ask_llm_with_retry(
            content, candidate.proposed_type, related, llm
        )
    except Exception:
        failures = _record_llm_failure(candidate.id)
        if failures >= _LLM_MAX_FAILURES:
            _llm_failure_counts.pop(candidate.id, None)
            _mark_rejected(candidate.id, "llm_failed")
            return Decision(
                DECISION_REJECT, "llm_failed", score, llm_used=True, components=components
            )
        return Decision(
            DECISION_DEFER, "llm_unavailable", score, llm_used=True, components=components
        )
    _fallback_window.append(True)
    _llm_failure_counts.pop(candidate.id, None)
    reason = f"llm:{verdict.reason}" if verdict.reason else "llm"
    if verdict.approve:
        return _promote_or_defer(
            candidate,
            final_type=_final_type(candidate.proposed_type, verdict.type),
            salience=_promotion_salience(candidate),
            reason=reason,
            score=score,
            components=components,
            llm_used=True,
            trace=trace,
        )
    _mark_rejected(candidate.id, reason)
    return Decision(
        DECISION_REJECT, reason, score, llm_used=True, components=components
    )


async def _decide(
    candidate: MemoryCandidateRow, active_contents: list[str], llm=None, trace=None
) -> Decision:
    if candidate.status != "pending":
        return Decision(DECISION_DEFER, "not_pending", 0.0)
    content = (candidate.content or "").strip()
    if not content:
        _mark_rejected(candidate.id, "empty_content")
        return Decision(DECISION_REJECT, "empty_content", 0.0)
    if candidate.visibility == VISIBILITY_HYPOTHETICAL:
        _mark_rejected(candidate.id, "hypothetical")
        return Decision(DECISION_REJECT, "hypothetical", 0.0)
    if candidate.source == SOURCE_EXPLICIT_REMEMBER:
        return _promote_or_defer(
            candidate,
            final_type=_final_type(candidate.proposed_type, None),
            salience=1.0,
            reason="explicit_remember",
            score=1.0,
            trace=trace,
        )
    if _is_exact_duplicate(content, active_contents):
        _mark_rejected(candidate.id, "duplicate_exact")
        return Decision(DECISION_REJECT, "duplicate_exact", 0.0)
    components = _score_components(candidate, content, active_contents)
    score = sum(components.values())
    settings = get_settings()
    if score >= settings.v2_memory_eval_threshold_high:
        return _promote_or_defer(
            candidate,
            final_type=_final_type(candidate.proposed_type, None),
            salience=_promotion_salience(candidate),
            reason=f"rule_score:{score:.2f}",
            score=score,
            components=components,
        )
    if score < settings.v2_memory_eval_threshold_low:
        _mark_rejected(candidate.id, f"low_score:{score:.2f}")
        return Decision(
            DECISION_REJECT, f"low_score:{score:.2f}", score, components=components
        )
    return await _decide_gray_zone(
        candidate, content, active_contents, score, components, llm, trace
    )


def _trace_decision(
    trace, started: float, decision: Decision, candidate: MemoryCandidateRow
) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(
        "memory_evaluate",
        duration,
        "ok",
        candidate_id=candidate.id,
        decision=decision.action,
        reason=decision.reason,
        score=round(decision.score, 4),
        llm_used=decision.llm_used,
        components={k: round(v, 4) for k, v in decision.components.items()},
    )


async def evaluate_candidate(
    candidate: MemoryCandidateRow,
    active_contents: list[str],
    trace=None,
    llm=None,
) -> Decision:
    started = time.perf_counter()
    decision = await _decide(candidate, active_contents, llm, trace)
    _trace_decision(trace, started, decision, candidate)
    return decision


def _list_pending(user_id: str) -> list[MemoryCandidateRow]:
    with SessionLocal() as session:
        rows = (
            session.query(MemoryCandidateRow)
            .filter(
                MemoryCandidateRow.user_id == user_id,
                MemoryCandidateRow.status == "pending",
            )
            .order_by(MemoryCandidateRow.created_at.asc(), MemoryCandidateRow.id.asc())
            .all()
        )
        return list(rows)


def _list_active_contents(user_id: str) -> list[str]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory.content)
            .filter(Memory.user_id == user_id, Memory.status == "active")
            .all()
        )
        return [row[0] for row in rows]


async def evaluate_pending(user_id: str, trace=None, llm=None) -> list[Decision]:
    """评估该用户全部 pending 候选；Flag OFF 时不执行任何动作。"""
    if not get_settings().v2_memory_enabled:
        return []
    candidates = _list_pending(user_id)
    if not candidates:
        return []
    active_contents = _list_active_contents(user_id)
    known_contents = list(active_contents)
    decisions: list[Decision] = []
    for row in candidates:
        try:
            decision = await evaluate_candidate(
                row, known_contents, trace=trace, llm=llm
            )
        except Exception:
            logger.exception("候选评估异常，留待下一轮：%s", row.id)
            if trace is not None:
                trace.record(
                    "memory_evaluate",
                    0.0,
                    "error",
                    error="evaluate failed",
                    candidate_id=row.id,
                )
            continue
        if decision.action == DECISION_APPROVE and row.content:
            known_contents.append(row.content)
        decisions.append(decision)
    return decisions


def reset_evaluator_state() -> None:
    """清空进程内护栏状态（兜底率窗口 / LLM 失败计数），仅供测试与运维复位。"""
    _fallback_window.clear()
    _llm_failure_counts.clear()
