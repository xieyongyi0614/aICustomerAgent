"""V7.5 EvaluationEngine（architecture.md §2 / evaluation-model.md §2）。

两阶段：规则阶段（纯函数，post_process 第 7 步锁内）→ judge 阶段（采样命中时
派发锁外后台任务，min 合并 + verdict + 落库）。评估失败只降级，绝不冒泡。
"""

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime

from app.chains import evaluation_judge_chain
from app.core.settings import get_settings
from app.models.evaluation import (
    DimensionScore,
    EvaluationDimension,
    EvaluationMeta,
    EvaluationReport,
    EvaluationSubjectKind,
    Issue,
    IssueCode,
    IssueSeverity,
    build_issue,
    clamp_score,
    compute_verdict,
    overall_score_from,
)
from app.repositories import evaluation_repository
from app.services import evaluation_rules
from app.services.evaluation_context import (
    EvaluationContext,
    build_digest,
    collect_proactive_context,
    collect_turn_context,
)

logger = logging.getLogger(__name__)


def should_sample(request_id: str, settings) -> bool:
    if not settings.evaluation_llm_judge_enabled:
        return False
    rate = settings.evaluation_llm_judge_sample_rate
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.sha256(request_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


def _judge_issues(judgement) -> list[Issue]:
    issues: list[Issue] = []
    for code in judgement.codes:
        issue = build_issue(
            IssueCode(code.value),
            evidence_quote=judgement.evidence_quote,
            source="llm",
        )
        if not judgement.evidence_quote:
            issue = issue.model_copy(update={"severity": IssueSeverity.INFO})
        issues.append(issue)
    return issues


def _merge_issues(rule_issues: list[Issue], judge_result) -> list[Issue]:
    issues = list(rule_issues)
    if judge_result is None:
        return issues
    memory_judgement = getattr(judge_result, "memory", None)
    if memory_judgement is not None:
        confirmed = any(
            code.value == IssueCode.MEMORY_FABRICATION.value
            for code in memory_judgement.codes
        )
        issues = [
            issue
            for issue in issues
            if not (
                issue.code == IssueCode.MEMORY_FABRICATION_CANDIDATE and confirmed
            )
        ]
    emotion_judgement = getattr(judge_result, "emotion", None)
    if emotion_judgement is not None:
        issues = [
            issue
            for issue in issues
            if issue.code != IssueCode.EMOTION_TEXT_STATE_CONFLICT
        ]
    for judgement in (
        getattr(judge_result, "persona", None),
        emotion_judgement,
        getattr(judge_result, "memory", None),
    ):
        if judgement is not None:
            issues.extend(_judge_issues(judgement))
    return issues


def _merge_scores(
    rule_scores: dict[EvaluationDimension, float],
    judge_result,
) -> dict[EvaluationDimension, DimensionScore]:
    scores = evaluation_rules.to_dimension_scores(rule_scores)
    judgements = []
    if judge_result is not None:
        judgements = [
            (EvaluationDimension.AUTONOMY, getattr(judge_result, "autonomy", None)),
            (EvaluationDimension.PERSONA, getattr(judge_result, "persona", None)),
            (EvaluationDimension.EMOTION, getattr(judge_result, "emotion", None)),
            (EvaluationDimension.MEMORY, getattr(judge_result, "memory", None)),
        ]
    for dimension, judgement in judgements:
        if judgement is None:
            continue
        judge_score = clamp_score(judgement.score)
        existing = scores.get(dimension)
        merged = judge_score
        rule_score = None
        if existing is not None:
            merged = min(existing.score, judge_score)
            rule_score = existing.rule_score
        scores[dimension] = DimensionScore(
            dimension=dimension,
            score=merged,
            rule_score=rule_score,
            judge_score=judge_score,
            issue_codes=[],
        )
    return scores


def finalize_report(
    subject: EvaluationSubjectKind,
    context: EvaluationContext,
    rule_issues: list[Issue],
    rule_scores: dict[EvaluationDimension, float],
    judge_result=None,
    model_name: str | None = None,
    judge_sampled: bool = False,
    duration_ms: float = 0.0,
) -> EvaluationReport:
    settings = get_settings()
    scores = _merge_scores(rule_scores, judge_result)
    issues = _merge_issues(rule_issues, judge_result)
    weights = settings.evaluation_overall_weights(subject.value)
    overall = overall_score_from(scores, weights) if subject != EvaluationSubjectKind.OFFLINE_BATCH else None
    report = EvaluationReport(
        id=uuid.uuid4().hex,
        subject=subject,
        subject_id=context.subject_id,
        session_id=context.session_id,
        user_id=context.user_id,
        character_id=context.character_id,
        scores=scores,
        overall_score=overall,
        verdict=compute_verdict(
            issues, overall, settings.evaluation_fail_score, settings.evaluation_warn_score
        ),
        issues=issues,
        context_digest=build_digest(context),
        meta=EvaluationMeta(
            model_name=model_name,
            judge_used=judge_result is not None,
            judge_sampled=judge_sampled,
            context_fidelity="live" if context.fidelity == "live" else "reconstructed",
            rule_codes_fired=[issue.code for issue in rule_issues],
            duration_ms=round(duration_ms, 2),
            request_id=context.request_id or None,
        ),
        created_at=datetime.now(),
    )
    return report


def run_turn_evaluation(ctx) -> None:
    """post_process 第 7 步（锁内）：收集 + 规则；judge 采样命中时派发锁外任务。"""
    settings = get_settings()
    if not settings.evaluation_enabled:
        _record(ctx, 0.0, "skipped")
        return
    started = time.perf_counter()
    try:
        context = collect_turn_context(ctx)
        rule_issues = evaluation_rules.run_rules(context)
        eligible = evaluation_rules.eligible_dimensions("turn")
        rule_scores = evaluation_rules.compute_rule_scores(rule_issues, eligible, settings)
        sampled = should_sample(context.request_id, settings)
        duration_ms = (time.perf_counter() - started) * 1000
        if sampled:
            _record(ctx, duration_ms, "ok", judge="dispatched")
            _dispatch_judge_task(ctx, context, rule_issues, rule_scores, duration_ms)
        else:
            report = finalize_report(
                EvaluationSubjectKind.TURN,
                context,
                rule_issues,
                rule_scores,
                judge_result=None,
                model_name=getattr(ctx.trace, "model_name", None),
                judge_sampled=False,
                duration_ms=duration_ms,
            )
            evaluation_repository.save(report)
            _record(ctx, duration_ms, "ok", judge="skipped", verdict=report.verdict)
    except Exception:
        logger.exception("评估流程失败，本轮不出报告")
        _record(ctx, 0.0, "error", error="evaluation failed")


def _dispatch_judge_task(
    ctx,
    context: EvaluationContext,
    rule_issues: list[Issue],
    rule_scores: dict,
    rules_duration_ms: float,
) -> None:
    from app.application import observability

    def _spawn_judge():
        return _judge_and_finalize(
            ctx, context, rule_issues, rule_scores, rules_duration_ms
        )

    if observability.spawn_background(_spawn_judge()):
        return
    asyncio.run(_spawn_judge())


async def _judge_and_finalize(
    ctx,
    context: EvaluationContext,
    rule_issues: list[Issue],
    rule_scores: dict,
    rules_duration_ms: float,
) -> None:
    started = time.perf_counter()
    try:
        judge_result = await evaluation_judge_chain.judge_turn(
            build_digest(context), character_id=context.character_id, llm=ctx.llm, trace=ctx.trace
        )
        report = finalize_report(
            EvaluationSubjectKind.TURN,
            context,
            rule_issues,
            rule_scores,
            judge_result=judge_result,
            model_name=getattr(ctx.trace, "model_name", None),
            judge_sampled=True,
            duration_ms=rules_duration_ms + (time.perf_counter() - started) * 1000,
        )
        evaluation_repository.save(report)
        if judge_result is None and ctx.trace is not None:
            ctx.trace.mark_status("evaluation", "degraded")
    except Exception:
        logger.exception("judge 阶段失败，降级处理")
        if ctx.trace is not None:
            ctx.trace.mark_status("evaluation", "degraded")


def _record(ctx, duration_ms: float, status: str, **extra) -> None:
    if ctx.trace is not None:
        ctx.trace.record("evaluation", duration_ms, status, **extra)


def schedule_proactive_evaluation(action, llm=None) -> None:
    """executor delivered 后 fire-and-forget（autonomy-evaluation.md §1，写锁外）。"""
    settings = get_settings()
    if not settings.evaluation_enabled or not settings.evaluation_autonomy_enabled:
        return
    from app.application import observability

    if not observability.spawn_background(_evaluate_proactive(action, llm)):
        asyncio.run(_evaluate_proactive(action, llm))


async def _evaluate_proactive(action, llm=None) -> None:
    try:
        context = collect_proactive_context(action)
        if context is None:
            return
        settings = get_settings()
        rule_issues = evaluation_rules.run_rules(context)
        eligible = evaluation_rules.eligible_dimensions("proactive_action")
        rule_scores = evaluation_rules.compute_rule_scores(
            rule_issues, eligible, settings
        )
        sampled = should_sample(context.request_id, settings)
        judge_result = None
        if sampled:
            judge_result = await evaluation_judge_chain.judge_proactive(
                build_digest(context),
                character_id=context.character_id,
                llm=llm,
            )
        report = finalize_report(
            EvaluationSubjectKind.PROACTIVE_ACTION,
            context,
            rule_issues,
            rule_scores,
            judge_result=judge_result,
            judge_sampled=sampled,
        )
        evaluation_repository.save(report)
    except Exception:
        logger.exception("主动行为评估失败，仅记录不冒泡")
