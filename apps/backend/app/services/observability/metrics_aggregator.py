"""V7.8 指标聚合（metrics.md §2/§3）：纯计算，输入为仓储查询结果，输出 MetricReport。"""


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(ratio * (len(ordered) - 1))))
    return float(ordered[index])


def summarize_llm_records(records, window_hours: float):
    from app.models.observability import LlmCallSiteStats, LlmMetrics

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
