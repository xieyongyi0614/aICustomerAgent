"""V7.8 Metrics Test（testing.md §2）：种子数据 → 期望数字精确断言。"""

from datetime import datetime

from app.core import timeutil
from app.models.autonomy import ProactiveAction
from app.models.evaluation import (
    DimensionScore,
    EvaluationDimension,
    EvaluationReport,
    EvaluationSubjectKind,
    build_issue,
    IssueCode,
)
from app.models.observability import (
    CallSite,
    LlmCallRecord,
    RuntimeTrace,
    TraceKind,
    TraceStep,
)
from app.services.observability.metrics_aggregator import (
    build_business_metrics,
    build_metric_report,
    build_pipeline_metrics,
    build_proactive_stats,
    build_quality_metrics,
    percentile,
)


def _trace(trace_id, status="complete", steps=None):
    return RuntimeTrace(
        trace_id=trace_id,
        kind=TraceKind.TURN,
        user_id="u1",
        turn_id=trace_id,
        status=status,
        duration_ms=100.0 if status != "error" else 50.0,
        steps=steps
        or [
            TraceStep(name="llm", duration_ms=10.0),
            TraceStep(name="memory_retrieval", duration_ms=20.0),
        ],
    )


def _llm_record(call_site=CallSite.ANSWER, status="ok", input_tokens=100, output_tokens=10, cost=None):
    return LlmCallRecord(
        request_id="req",
        call_site=call_site,
        model="fake",
        status=status,
        latency_ms=100.0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_estimate=cost,
    )


def _report(verdict="pass", score=0.9, dimension=EvaluationDimension.PERSONA, with_issue=False):
    return EvaluationReport(
        id=f"r-{verdict}-{dimension.value}-{score}-{with_issue}",
        subject=EvaluationSubjectKind.TURN,
        subject_id="t1",
        user_id="u1",
        scores={dimension: DimensionScore(dimension=dimension, score=score)},
        verdict=verdict,
        issues=[build_issue(IssueCode.MEMORY_MISSED)] if with_issue else [],
        created_at=timeutil.now(),
    )


def _action(status):
    return ProactiveAction(
        id=f"a-{status}",
        user_id="u1",
        session_id="s1",
        trigger_type="conversation_inactivity",
        dedupe_key=f"k-{status}",
        intention="check_in",
        reason="r",
        status=status,
        created_at=timeutil.now(),
        updated_at=timeutil.now(),
    )


def test_percentile_simple():
    assert percentile([], 0.5) == 0.0
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([10.0], 0.95) == 10.0


def test_pipeline_metrics_steps_and_e2e():
    traces = [
        _trace("t1", steps=[TraceStep(name="llm", duration_ms=10.0)]),
        _trace("t2", steps=[TraceStep(name="llm", duration_ms=30.0)]),
        _trace("t3", status="error", steps=[TraceStep(name="llm", duration_ms=50.0)]),
    ]
    metrics = build_pipeline_metrics(traces)
    assert metrics.turn_count == 3
    assert metrics.steps["llm"].count == 3
    assert metrics.steps["llm"].p50_ms == 30.0
    assert metrics.steps["llm"].p95_ms == 50.0
    assert metrics.e2e_p50_ms == 100.0


def test_quality_metrics_distribution_means_and_issues():
    reports = [
        _report("pass", score=0.9, dimension=EvaluationDimension.PERSONA),
        _report("fail", score=0.4, dimension=EvaluationDimension.PERSONA),
        _report("warn", score=0.6, dimension=EvaluationDimension.EMOTION, with_issue=True),
    ]
    metrics = build_quality_metrics(reports)
    assert metrics.reports == 3
    assert metrics.verdict_distribution == {"pass": 1, "fail": 1, "warn": 1}
    assert metrics.dimension_mean["persona"] == 0.65
    assert metrics.dimension_mean["emotion"] == 0.6
    assert metrics.issue_top[0].code == "memory_missed"


def test_proactive_stats_ack_rate():
    stats = build_proactive_stats(
        [_action("delivered"), _action("acked"), _action("acked"), _action("failed")]
    )
    assert stats.delivered == 3
    assert stats.acked == 2
    assert stats.failed == 1
    assert stats.ack_rate == round(2 / 3, 4)
    assert build_proactive_stats([]).ack_rate is None


def test_business_metrics_messages_and_success_rate():
    traces = [_trace("t1"), _trace("t2", status="error")]
    metrics = build_business_metrics(
        traces,
        [("c1", "human"), ("c1", "ai"), ("c2", "human")],
        [_action("acked")],
    )
    assert metrics.conversation_count == 2
    assert metrics.message_count == 3
    assert metrics.avg_messages_per_conversation == 1.5
    assert metrics.response_success_rate == 0.5
    assert metrics.proactive.acked == 1


def test_build_metric_report_empty_window_is_zeroed():
    report = build_metric_report(24, [], [], [], [], [])
    assert report.pipeline.turn_count == 0
    assert report.llm.calls == 0
    assert report.quality.reports == 0
    assert report.business.message_count == 0
    assert report.business.proactive.ack_rate is None
    assert report.business.response_success_rate is None
