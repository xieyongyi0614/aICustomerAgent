"""MEV-004 离线门槛扩展测试：E-MEM-07 / E-MEM-08 的阈值、映射与判定参与。

契约：`app/services/memory/offline_metrics.py`（§MEV-004 §4.1.3）。
既有 E-MEM-01~06 的阈值与 kind 映射必须**逐项不变**。
"""

from __future__ import annotations

import pytest

from app.services.memory import offline_metrics
from app.services.memory.offline_metrics import GATE_THRESHOLDS, KIND_TO_METRIC, build_report

pytestmark = pytest.mark.unit

BASELINE_THRESHOLDS = {
    "E-MEM-01": 0.9,
    "E-MEM-02": 1.0,
    "E-MEM-03": 1.0,
    "E-MEM-04": 0.8,
    "E-MEM-05": 1.0,
    "E-MEM-06": 1.0,
}

BASELINE_KIND_TO_METRIC = {
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
}

KIND_BY_METRIC = {
    "E-MEM-01": "short_dialog",
    "E-MEM-02": "user_correction",
    "E-MEM-03": "explicit_remember",
    "E-MEM-04": "paraphrase_recall",
    "E-MEM-05": "roleplay",
    "E-MEM-06": "roleplay",
    "E-MEM-07": "rerank_gain",
    "E-MEM-08": "rewrite_gain",
}


def _result(kind: str, *, passed: bool = True, scenario_id: str = "s") -> dict:
    return {
        "scenario_id": scenario_id,
        "kind": kind,
        "passed": passed,
        "failures": [] if passed else ["probe 未命中"],
        "probe_count": 1,
    }


def _all_passing(exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    return [
        _result(kind, scenario_id=f"{metric_id}-ok")
        for metric_id, kind in KIND_BY_METRIC.items()
        if metric_id not in exclude
    ]


class TestThresholdsAndMapping:
    def test_thresholds_include_seven_and_eight(self):
        assert {"E-MEM-07", "E-MEM-08"} <= set(GATE_THRESHOLDS)

    def test_previous_thresholds_unchanged(self):
        for metric_id, threshold in BASELINE_THRESHOLDS.items():
            assert GATE_THRESHOLDS[metric_id]["threshold"] == threshold
            assert GATE_THRESHOLDS[metric_id]["metric"]

    def test_new_thresholds_are_bounded(self):
        for metric_id in ("E-MEM-07", "E-MEM-08"):
            threshold = GATE_THRESHOLDS[metric_id]["threshold"]
            assert 0.0 < threshold <= 1.0

    def test_kind_to_metric_keeps_previous_mappings(self):
        for kind, metric_id in BASELINE_KIND_TO_METRIC.items():
            assert KIND_TO_METRIC[kind] == metric_id

    def test_new_kinds_map_to_new_metrics(self):
        assert KIND_TO_METRIC["rerank_gain"] == "E-MEM-07"
        assert KIND_TO_METRIC["rewrite_gain"] == "E-MEM-08"


class TestReport:
    def test_report_emits_eight_metrics(self):
        report = build_report(_all_passing(), [])
        assert set(report["metrics"]) == set(GATE_THRESHOLDS)
        assert len(report["metrics"]) == 8

    def test_gate_passes_when_all_metrics_pass(self):
        report = build_report(_all_passing(), [])
        assert report["gate_passed"] is True

    def test_gate_fails_when_rerank_metric_below_threshold(self):
        results = _all_passing(exclude={"E-MEM-07"})
        results.append(_result("rerank_gain", passed=False, scenario_id="rg-bad"))
        report = build_report(results, [])
        assert report["metrics"]["E-MEM-07"]["score"] == 0.0
        assert report["metrics"]["E-MEM-07"]["pass"] is False
        assert report["gate_passed"] is False

    def test_gate_fails_when_rewrite_metric_below_threshold(self):
        results = _all_passing(exclude={"E-MEM-08"})
        results.append(_result("rewrite_gain", passed=False, scenario_id="rw-bad"))
        report = build_report(results, [])
        assert report["metrics"]["E-MEM-08"]["pass"] is False
        assert report["gate_passed"] is False

    def test_missing_scenarios_for_new_metrics_fail_the_gate(self):
        """无场景的指标不得「静默通过」（与既有 n=0 语义一致）。"""
        report = build_report(_all_passing(exclude={"E-MEM-07", "E-MEM-08"}), [])
        assert report["metrics"]["E-MEM-07"]["n"] == 0
        assert report["metrics"]["E-MEM-07"]["pass"] is False
        assert report["gate_passed"] is False

    def test_coverage_counts_new_kinds(self):
        report = build_report(_all_passing(), [])
        assert report["coverage"]["kind_counts"]["rerank_gain"] == 1
        assert report["coverage"]["kind_counts"]["rewrite_gain"] == 1
        assert report["coverage"]["scenario_count"] == len(KIND_BY_METRIC)

    def test_failed_scenarios_are_reported(self):
        results = _all_passing()
        results.append(_result("rerank_gain", passed=False, scenario_id="rg-bad"))
        report = build_report(results, [])
        assert any(item["scenario_id"] == "rg-bad" for item in report["failed_scenarios"])

    def test_module_exposes_no_settings_dependency(self):
        """门槛是模块常量（不随运行期设置变化）。"""
        assert isinstance(offline_metrics.GATE_THRESHOLDS, dict)
        assert all(
            isinstance(spec["threshold"], float) for spec in offline_metrics.GATE_THRESHOLDS.values()
        )
