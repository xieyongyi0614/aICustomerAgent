"""V7.8 指标聚合（metrics.md §2/§3）：纯计算，输入为仓储查询结果，输出 MetricReport。"""

from app.models.observability import (
    BusinessMetrics,
    IssueCount,
    LlmCallSiteStats,
    LlmMetrics,
    PipelineMetrics,
    ProactiveBusinessStats,
    QualityMetrics,
    StepLatencyStats,
    TraceKind,
)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(ratio * (len(ordered) - 1))))
    return float(ordered[index])


def build_pipeline_metrics(traces) -> PipelineMetrics:
    step_latencies: dict[str, list[float]] = {}
    for trace in traces:
        for step in trace.steps:
            step_latencies.setdefault(step.name, []).append(step.duration_ms)
    steps = {
        name: StepLatencyStats(
            count=len(values),
            p50_ms=round(percentile(values, 0.5), 2),
            p95_ms=round(percentile(values, 0.95), 2),
        )
        for name, values in sorted(step_latencies.items())
    }
    turn_traces = [trace for trace in traces if trace.kind is TraceKind.TURN]
    e2e = [trace.duration_ms for trace in turn_traces]
    return PipelineMetrics(
        turn_count=len(turn_traces),
        e2e_p50_ms=round(percentile(e2e, 0.5), 2),
        e2e_p95_ms=round(percentile(e2e, 0.95), 2),
        steps=steps,
    )


def summarize_llm_records(records, window_hours: float) -> LlmMetrics:
    by_site: dict[str, list] = {}
    for record in records:
        by_site.setdefault(record.call_site.value, []).append(record)

    sites: dict[str, LlmCallSiteStats] = {}
    total_calls = total_errors = 0
    total_in = total_out = 0
    total_cost = 0.0
    has_tokens = has_cost = False
    for site_value, site_records in by_site.items():
        latencies = [record.latency_ms for record in site_records]
        site_in = sum(record.input_tokens or 0 for record in site_records)
        site_out = sum(record.output_tokens or 0 for record in site_records)
        site_errors = sum(1 for record in site_records if record.status == "error")
        site_cost = sum(record.cost_estimate or 0.0 for record in site_records)
        sites[site_value] = LlmCallSiteStats(
            calls=len(site_records),
            errors=site_errors,
            latency_p50_ms=round(percentile(latencies, 0.5), 2),
            latency_p95_ms=round(percentile(latencies, 0.95), 2),
            input_tokens=site_in,
            output_tokens=site_out,
            cost_estimate=round(site_cost, 6),
        )
        total_calls += len(site_records)
        total_errors += site_errors
        total_in += site_in
        total_out += site_out
        total_cost += site_cost
        if any(record.input_tokens is not None for record in site_records):
            has_tokens = True
        if any(record.cost_estimate is not None for record in site_records):
            has_cost = True
    return LlmMetrics(
        calls=total_calls,
        errors=total_errors,
        error_rate=round(total_errors / total_calls, 4) if total_calls else 0.0,
        input_tokens=total_in if has_tokens else 0,
        output_tokens=total_out if has_tokens else 0,
        cost_estimate=round(total_cost, 6) if has_cost else 0.0,
        by_call_site=sites,
    )


def build_quality_metrics(reports) -> QualityMetrics:
    verdict_distribution: dict[str, int] = {}
    dimension_scores: dict[str, list[float]] = {}
    issue_counts: dict[str, int] = {}
    for report in reports:
        verdict_distribution[report.verdict] = verdict_distribution.get(report.verdict, 0) + 1
        for dimension, score in report.scores.items():
            key = dimension.value if hasattr(dimension, "value") else str(dimension)
            dimension_scores.setdefault(key, []).append(score.score)
        for issue in report.issues:
            code = issue.code.value if hasattr(issue.code, "value") else str(issue.code)
            issue_counts[code] = issue_counts.get(code, 0) + 1
    issue_top = [
        IssueCount(code=code, count=count)
        for code, count in sorted(issue_counts.items(), key=lambda item: -item[1])[:10]
    ]
    return QualityMetrics(
        reports=len(reports),
        verdict_distribution=verdict_distribution,
        dimension_mean={
            key: round(sum(values) / len(values), 4)
            for key, values in dimension_scores.items()
        },
        issue_top=issue_top,
    )


def build_proactive_stats(actions) -> ProactiveBusinessStats:
    delivered = sum(1 for action in actions if action.status in ("delivered", "acked"))
    acked = sum(1 for action in actions if action.status == "acked")
    failed = sum(1 for action in actions if action.status in ("failed", "expired"))
    ack_rate = None
    if delivered > 0:
        ack_rate = round(acked / delivered, 4)
    return ProactiveBusinessStats(delivered=delivered, acked=acked, failed=failed, ack_rate=ack_rate)


def build_business_metrics(traces, message_pairs, proactive_actions) -> BusinessMetrics:
    conversation_ids = {conv_id for conv_id, _ in message_pairs}
    turn_traces = [trace for trace in traces if trace.kind is TraceKind.TURN]
    success_rate = None
    if turn_traces:
        completed = sum(1 for trace in turn_traces if trace.status != "error")
        success_rate = round(completed / len(turn_traces), 4)
    return BusinessMetrics(
        conversation_count=len(conversation_ids),
        message_count=len(message_pairs),
        avg_messages_per_conversation=(
            round(len(message_pairs) / len(conversation_ids), 2) if conversation_ids else 0.0
        ),
        response_success_rate=success_rate,
        proactive=build_proactive_stats(proactive_actions),
    )


def build_metric_report(
    window_hours: float,
    traces,
    llm_records,
    reports,
    message_pairs,
    proactive_actions,
):
    from app.models.observability import MetricReport

    return MetricReport(
        window_hours=window_hours,
        pipeline=build_pipeline_metrics(traces),
        llm=summarize_llm_records(llm_records, window_hours),
        quality=build_quality_metrics(reports),
        business=build_business_metrics(traces, message_pairs, proactive_actions),
    )
