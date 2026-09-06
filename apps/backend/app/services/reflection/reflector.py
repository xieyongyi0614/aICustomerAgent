"""反思执行器（REF-004 / Reflector）。

消费 queued 反思任务：重聚合证据组 → LLM 结构化推理（main 档，≤1 次成功调用，
解析失败重试 1 次）→ confidence 代码校准（LLM 自报值仅 trace 对照）→ 三闸复检
（引用完整性/形态合规/置信门槛）→ 单事务写 insights + evidence_links +
reflection_runs 并 supersede 同主题旧 active Insight。核心裁决：LLM 只产候选，
代码决定终值；被篡改证据（组外/伪造引用）必须拒绝。对 memories 零写入。
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta

from app.chains.structured import build_structured_chain
from app.core.db import EvidenceLinkRow, InsightRow, ReflectionRunRow, SessionLocal
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError, get_settings
from app.models.reflection import ReflectionProposal
from app.prompts.reflection import build_evidence_block, build_reflection_messages
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import lifecycle as reflection_lifecycle
from app.services.reflection.lifecycle import (
    EVENT_SUPERSEDE,
    STATUS_ACTIVE,
    transition,
)

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_run"

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_DONE = "done"
RUN_FAILED = "failed"

OUTCOME_INSIGHTS = "insights_created"
OUTCOME_EVIDENCE_GONE = "evidence_gone"
OUTCOME_REJECTED = "rejected"
OUTCOME_ALREADY_CREATED = "already_created"

_LLM_RETRY_ATTEMPTS = 2
_LLM_RETRY_BACKOFF_SECONDS = 0.5
_EVIDENCE_LABEL_RE = re.compile(r"^E(\d+)$", re.IGNORECASE)
_CONFIDENCE_CEILING = 0.95

_REVIEW_NO_EVIDENCE = "no_evidence"
_REVIEW_OUT_OF_SCOPE = "evidence_out_of_scope"
_REVIEW_BELOW_MIN = "evidence_below_min"
_REVIEW_EMPTY_STATEMENT = "empty_statement"
_REVIEW_STATEMENT_TOO_LONG = "statement_too_long"
_REVIEW_MISSING_COUNTER = "missing_counter_evidence"
_REVIEW_BELOW_CONFIDENCE = "below_min_confidence"


def register_executor() -> None:
    """reflection_run 任务执行 handler 注册（main lifespan Flag ON 时调用）。"""
    from app.services.memory2 import job_worker as memory2_job_worker

    memory2_job_worker.register_job_type("reflection_run", run_queued_reflections)


def run_queued_reflections(now: datetime | None = None, trace=None) -> int:
    """调度循环入口：回收超时 running → 逐条认领 queued → 执行；Flag OFF 直接返回 0。"""
    now = now or datetime.now()
    if not get_settings().v2_reflection_enabled:
        return 0
    _recover_timed_out_runs(now)
    executed = 0
    for run_id in _list_queued_run_ids():
        if not _claim_run(run_id, now):
            continue
        try:
            execute_run(run_id, trace=trace)
            executed += 1
        except Exception as exc:
            logger.exception("反思执行异常，run 标记失败：%s", run_id)
            _mark_failed(run_id, f"executor_error:{exc.__class__.__name__}", now)
            executed += 1
    return executed


def execute_run(run_id: str, trace=None) -> str:
    """单 run 执行：证据重聚合 → LLM → 校准/复检 → 单事务落库；返回终态。"""
    started = time.perf_counter()
    now = datetime.now()
    run = _get_run(run_id)
    if run is None:
        return "gone"
    if _run_already_produced(run_id):
        _finish_run(run_id, RUN_DONE, OUTCOME_ALREADY_CREATED, [], llm_used=False, now=now)
        _trace(trace, started, run_id=run_id, decision="done", outcome=OUTCOME_ALREADY_CREATED)
        return RUN_DONE

    settings = get_settings()
    windows = reflection_evidence.aggregate_evidence_windows(
        run.user_id, run.character_id, now=now
    )
    passing = [window for window in windows if window.passes_gate]
    if not passing:
        _finish_run(
            run_id,
            RUN_DONE,
            OUTCOME_EVIDENCE_GONE,
            [],
            llm_used=False,
            now=now,
            evidence_summary={"passing": 0, "window_count": len(windows)},
        )
        _trace(trace, started, run_id=run_id, decision="done", outcome=OUTCOME_EVIDENCE_GONE)
        return OUTCOME_EVIDENCE_GONE

    window = passing[0]
    evidence_block, provided = build_evidence_block(
        window,
        settings.v2_reflection_evidence_max_members,
        settings.v2_reflection_evidence_content_chars,
    )
    try:
        proposal = _ask_llm_with_retry(window)
    except Exception as exc:
        logger.warning("反思 LLM 调用失败：%s - %s", run_id, exc.__class__.__name__)
        _mark_failed(run_id, "llm_failed", now, llm_used=True)
        _trace(trace, started, run_id=run_id, decision="failed", reason="llm_failed")
        return RUN_FAILED

    accepted, rejected = _calibrate_and_review(proposal, window, provided, settings)
    if not accepted:
        _finish_run(
            run_id,
            RUN_DONE,
            OUTCOME_REJECTED,
            [],
            llm_used=True,
            now=now,
            evidence_summary=_summary(window, [], rejected),
        )
        _trace(
            trace,
            started,
            run_id=run_id,
            decision="done",
            outcome=OUTCOME_REJECTED,
            rejected=rejected,
        )
        return OUTCOME_REJECTED

    insight_ids = _persist(run, accepted, provided, now)
    _finish_run(
        run_id,
        RUN_DONE,
        OUTCOME_INSIGHTS,
        insight_ids,
        llm_used=True,
        now=now,
        evidence_summary=_summary(window, accepted, rejected),
    )
    _trace(
        trace,
        started,
        run_id=run_id,
        decision="done",
        outcome=OUTCOME_INSIGHTS,
        insight_ids=insight_ids,
        calibration=[
            {"statement": draft.statement[:40], "final_confidence": final}
            for draft, _resolved, final in accepted
        ],
        rejected=rejected,
    )
    return RUN_DONE


def calibrate_confidence(
    coherence: float, distinct_source_refs: int, sources: list[str], settings=None
) -> float:
    """confidence 终值 = clamp(coherence × count_factor, 0, 0.95)；含 ai_inferred 成员封顶。"""
    settings = settings or get_settings()
    factor = _count_factor(
        distinct_source_refs, settings.v2_reflection_confidence_count_curve_json
    )
    final = coherence * factor
    final = max(0.0, min(_CONFIDENCE_CEILING, final))
    if "ai_inferred" in sources:
        final = min(final, settings.v2_reflection_ai_inferred_cap)
    return round(final, 4)


def _count_factor(count: int, curve_json: str) -> float:
    curve = json.loads(curve_json)
    keys = sorted(int(key) for key in curve)
    if not keys:
        return 1.0
    applicable = [key for key in keys if key <= count]
    chosen = applicable[-1] if applicable else keys[0]
    return float(curve[str(chosen)])


def _calibrate_and_review(proposal, window, provided, settings) -> tuple[list, list[dict]]:
    """逐 draft：evidence_ids 映射 → confidence 校准 → 三闸复检。返回 (通过, 拒绝)。"""
    min_confidence = settings.v2_reflection_min_confidence
    accepted: list = []
    rejected: list[dict] = []
    for draft in proposal.insights:
        resolved, invalid = _resolve_evidence_ids(draft.evidence_ids, provided)
        final = calibrate_confidence(
            window.stats.coherence,
            window.stats.distinct_source_refs,
            [member.source for member in provided],
            settings,
        )
        reasons = _review_draft(draft, resolved, invalid, final, settings)
        if reasons:
            rejected.append({"statement": draft.statement[:60], "reasons": reasons})
            continue
        accepted.append((draft, resolved, final))
    accepted.sort(key=lambda item: item[2], reverse=True)
    return accepted, rejected


def _resolve_evidence_ids(raw_ids: list[str], provided) -> tuple[list[str], list[str]]:
    """E编号 → provided 成员；直接给 id 须在本次提供集合内；组外/伪造一律 invalid。"""
    resolved: list[str] = []
    invalid: list[str] = []
    for raw in raw_ids or []:
        label = str(raw).strip()
        match = _EVIDENCE_LABEL_RE.match(label)
        if match is not None:
            index = int(match.group(1)) - 1
            if 0 <= index < len(provided):
                resolved.append(provided[index].memory_id)
            else:
                invalid.append(label)
            continue
        if any(member.memory_id == label for member in provided):
            resolved.append(label)
        else:
            invalid.append(label)
    return resolved, invalid


def _review_draft(
    draft, resolved: list[str], invalid: list[str], final: float, settings
) -> list[str]:
    reasons: list[str] = []
    if not draft.evidence_ids:
        reasons.append(_REVIEW_NO_EVIDENCE)
    if invalid:
        reasons.append(_REVIEW_OUT_OF_SCOPE)
    if len(set(resolved)) < settings.v2_reflection_min_evidence:
        reasons.append(_REVIEW_BELOW_MIN)
    statement = (draft.statement or "").strip()
    if not statement:
        reasons.append(_REVIEW_EMPTY_STATEMENT)
    elif len(statement) > settings.v2_reflection_statement_max_chars:
        reasons.append(_REVIEW_STATEMENT_TOO_LONG)
    if not (draft.counter_evidence or "").strip():
        reasons.append(_REVIEW_MISSING_COUNTER)
    if final < settings.v2_reflection_min_confidence:
        reasons.append(_REVIEW_BELOW_CONFIDENCE)
    return reasons


def _persist(run, accepted: list, provided, now: datetime) -> list[str]:
    """单事务：INSERT insights + evidence_links + supersede 同主题旧 active + run→done。"""
    settings = get_settings()
    top = accepted[: settings.v2_reflection_max_insights_per_run]
    insight_ids = [f"ins:{uuid.uuid4().hex}" for _ in top]
    weights = {member.memory_id: member.weight for member in provided}
    superseded: list[dict] = []
    with SessionLocal() as session:
        run_row = session.get(ReflectionRunRow, run.id)
        if run_row is None or run_row.status != RUN_RUNNING:
            raise RuntimeError(
                f"run 不可写: {run.id} status={run_row.status if run_row else None}"
            )
        for (draft, resolved_ids, final), insight_id in zip(top, insight_ids):
            session.add(
                InsightRow(
                    id=insight_id,
                    user_id=run.user_id,
                    character_id=run.character_id,
                    statement=draft.statement.strip(),
                    type=draft.type,
                    confidence=final,
                    scope=draft.scope,
                    status=STATUS_ACTIVE,
                    run_id=run.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            for memory_id in dict.fromkeys(resolved_ids):
                session.add(
                    EvidenceLinkRow(
                        id=f"evl:{uuid.uuid4().hex}",
                        insight_id=insight_id,
                        memory_id=memory_id,
                        weight=weights.get(memory_id, 0.0),
                        created_at=now,
                    )
                )
            superseded.extend(
                _supersede_conflicts(session, run, draft, insight_id, insight_ids, now)
            )
        run_row.status = RUN_DONE
        run_row.outcome = OUTCOME_INSIGHTS
        run_row.insight_ids = insight_ids
        run_row.updated_at = now
        session.commit()
    if superseded:
        reflection_lifecycle.notify_invalidation_listeners(run.user_id, superseded)
    return insight_ids


def _supersede_conflicts(
    session, run, draft, insight_id: str, own_ids: list[str], now: datetime
) -> list[dict]:
    """替代半边：同 scope+type 且相似度达阈值的旧 active Insight → superseded（同事务）。"""
    actives = (
        session.query(InsightRow)
        .filter(
            InsightRow.user_id == run.user_id,
            InsightRow.status == STATUS_ACTIVE,
            InsightRow.scope == draft.scope,
            InsightRow.type == draft.type,
        )
        .all()
    )
    candidates = [
        reflection_lifecycle._to_insight(row)
        for row in actives
        if row.id not in own_ids
    ]
    matched_ids = set(
        reflection_lifecycle.find_superseded_insights(
            draft.statement, draft.scope, draft.type, candidates
        )
    )
    changed: list[dict] = []
    for row in actives:
        if row.id not in matched_ids:
            continue
        row.status = transition(row.status, EVENT_SUPERSEDE)
        row.superseded_by = insight_id
        row.updated_at = now
        changed.append(
            {"insight_id": row.id, "status": "superseded", "superseded_by": insight_id}
        )
    return changed


def _ask_llm_with_retry(window) -> ReflectionProposal:
    llm = _resolve_llm(get_settings())
    chain = build_structured_chain(build_reflection_messages(window), ReflectionProposal, llm)
    last_exc: Exception | None = None
    for attempt in range(_LLM_RETRY_ATTEMPTS):
        if attempt:
            time.sleep(_LLM_RETRY_BACKOFF_SECONDS)
        try:
            result = chain.invoke({})
            if isinstance(result, ReflectionProposal):
                return result
            return ReflectionProposal.model_validate(result)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "反思 LLM 调用失败（第 %d 次）：%s", attempt + 1, exc.__class__.__name__
            )
    assert last_exc is not None
    raise last_exc


def _resolve_llm(settings):
    profile = settings.v2_reflection_llm_profile or None
    try:
        return get_llm(profile)
    except SettingsError:
        return get_llm(None)


def _list_queued_run_ids() -> list[str]:
    with SessionLocal() as session:
        rows = (
            session.query(ReflectionRunRow.id)
            .filter(ReflectionRunRow.status == RUN_QUEUED)
            .order_by(ReflectionRunRow.created_at.asc())
            .all()
        )
        return [row[0] for row in rows]


def _claim_run(run_id: str, now: datetime) -> bool:
    with SessionLocal() as session:
        updated = (
            session.query(ReflectionRunRow)
            .filter(ReflectionRunRow.id == run_id, ReflectionRunRow.status == RUN_QUEUED)
            .update({"status": RUN_RUNNING, "updated_at": now})
        )
        session.commit()
        return updated == 1


def _recover_timed_out_runs(now: datetime) -> int:
    threshold = now - timedelta(minutes=get_settings().v2_reflection_run_timeout_minutes)
    with SessionLocal() as session:
        updated = (
            session.query(ReflectionRunRow)
            .filter(
                ReflectionRunRow.status == RUN_RUNNING,
                ReflectionRunRow.updated_at < threshold,
            )
            .update({"status": RUN_QUEUED, "updated_at": now})
        )
        session.commit()
        return updated


def _run_already_produced(run_id: str) -> bool:
    with SessionLocal() as session:
        return (
            session.query(InsightRow.id).filter(InsightRow.run_id == run_id).first()
            is not None
        )


def _get_run(run_id: str):
    with SessionLocal() as session:
        row = session.get(ReflectionRunRow, run_id)
        if row is not None:
            session.expunge(row)
        return row


def _finish_run(
    run_id: str,
    status: str,
    outcome: str,
    insight_ids: list[str],
    *,
    llm_used: bool,
    now: datetime,
    evidence_summary: dict | None = None,
) -> None:
    with SessionLocal() as session:
        row = session.get(ReflectionRunRow, run_id)
        if row is None:
            return
        row.status = status
        row.outcome = outcome
        row.llm_used = llm_used
        row.insight_ids = insight_ids
        if evidence_summary is not None:
            row.evidence_summary = evidence_summary
        row.updated_at = now
        session.commit()


def _mark_failed(run_id: str, error: str, now: datetime, llm_used: bool = False) -> None:
    with SessionLocal() as session:
        row = session.get(ReflectionRunRow, run_id)
        if row is None:
            return
        row.status = RUN_FAILED
        row.error = error
        row.outcome = RUN_FAILED
        row.llm_used = llm_used
        row.updated_at = now
        session.commit()


def _summary(window, accepted, rejected) -> dict:
    return {
        "topic": window.topic_digest[:40],
        "member_count": window.stats.member_count,
        "distinct_source_refs": window.stats.distinct_source_refs,
        "coherence": window.stats.coherence,
        "accepted": [
            {
                "statement": draft.statement[:80],
                "type": draft.type,
                "scope": draft.scope,
                "confidence": final,
                "self_confidence": draft.self_confidence,
                "evidence": resolved,
            }
            for draft, resolved, final in accepted
        ],
        "rejected": rejected,
    }


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)
