"""Memory 2.0 离线评估指标计算器（MEM-010）。

E-MEM-01~08 的门槛判定与报告聚合（evaluation.md §指标与门槛）。纯函数、只读：
输入逐场景执行结果（由 tests/eval 场景运行器产出），输出 Eval Gate 报告 JSON。
场景标注集规模不足时门槛照常生效，覆盖率在报告中显式标注。

E-MEM-07 / E-MEM-08 为 MEV-004 扩展：把 M1 的重排与改写能力纳入可判定范围。
二者的阈值为**评估模块常量**（非运行期设置，保持与既有 6 项同源）；当前取值按既定
「top-1 一致率 / 相关条目占比」口径在评估集上实测后冻结，重排 / 改写开启的批次若口径变化
须同批复核。
"""

from datetime import datetime

from app.core import timeutil

GATE_THRESHOLDS = {
    "E-MEM-01": {"metric": "Memory Precision", "threshold": 0.9},
    "E-MEM-02": {"metric": "冲突处理正确率", "threshold": 1.0},
    "E-MEM-03": {"metric": "显式命令正确率", "threshold": 1.0},
    "E-MEM-04": {"metric": "语义召回 Recall（改述）", "threshold": 0.8},
    "E-MEM-05": {"metric": "Roleplay/假设拦截率", "threshold": 1.0},
    "E-MEM-06": {"metric": "Context 注入合规", "threshold": 1.0},
    "E-MEM-07": {"metric": "重排增益（top-1 与人工首选一致率）", "threshold": 0.9},
    "E-MEM-08": {"metric": "改写贡献（仅改写 query 命中的相关条目占比）", "threshold": 0.8},
}

KIND_TO_METRIC = {
    "short_dialog": "E-MEM-01",
    "long_dialog": "E-MEM-01",
    "cross_conversation": "E-MEM-01",
    "misinformation": "E-MEM-01",
    "user_correction": "E-MEM-02",
    "conflict_info": "E-MEM-02",
    "explicit_remember": "E-MEM-03",
    "explicit_forget": "E-MEM-03",
    "paraphrase_recall": "E-MEM-04",
    "roleplay": "E-MEM-05",
    "hypothetical": "E-MEM-05",
    "rerank_gain": "E-MEM-07",
    "rewrite_gain": "E-MEM-08",
}


def build_report(scenario_results: list[dict], context_violations: list[str]) -> dict:
    """聚合逐场景结果为 Eval Gate 报告。

    scenario_results: [{scenario_id, kind, passed, failures}]；
    context_violations: E-MEM-06 全局违例（hypothetical 注入 / 检索段超预算）。
    """
    by_metric: dict[str, list[dict]] = {metric_id: [] for metric_id in GATE_THRESHOLDS}
    for result in scenario_results:
        metric_id = KIND_TO_METRIC.get(result["kind"])
        if metric_id is not None:
            by_metric[metric_id].append(result)
        else:
            by_metric.setdefault("unmapped", []).append(result)

    metrics = {}
    for metric_id, spec in GATE_THRESHOLDS.items():
        results = by_metric.get(metric_id, [])
        if metric_id == "E-MEM-06":
            total_probes = sum(r.get("probe_count", 0) for r in scenario_results)
            score = 1.0 if not context_violations else 0.0
            total = total_probes
        else:
            total = len(results)
            score = (
                sum(1 for r in results if r["passed"]) / total if total else 0.0
            )
        metrics[metric_id] = {
            "metric": spec["metric"],
            "score": round(score, 4),
            "threshold": spec["threshold"],
            "n": total,
            "pass": score >= spec["threshold"] and (total > 0 or metric_id != "E-MEM-06"),
        }

    failed_scenarios = [
        {"scenario_id": r["scenario_id"], "kind": r["kind"], "failures": r["failures"]}
        for r in scenario_results
        if not r["passed"]
    ]
    kind_counts: dict[str, int] = {}
    for result in scenario_results:
        kind_counts[result["kind"]] = kind_counts.get(result["kind"], 0) + 1

    return {
        "generated_at": timeutil.now().isoformat(timespec="seconds"),
        "mode": "flag-on-shadow",
        "coverage": {
            "scenario_count": len(scenario_results),
            "kind_counts": kind_counts,
            "llm_stub": "deterministic（场景级拒绝表驱动）",
            "note": "标注集随 Phase 累积（目标每类 ≥10）；门槛已按 evaluation.md 生效",
        },
        "metrics": metrics,
        "gate_passed": all(m["pass"] for m in metrics.values()),
        "context_violations": context_violations,
        "failed_scenarios": failed_scenarios,
    }
