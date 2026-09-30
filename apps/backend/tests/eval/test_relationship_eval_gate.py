"""E-REL Gate：REL-004 关系域离线评估（场景集全规则 0 LLM）。

v2_relationship_evolved_enabled 开关已随 vXX_ 体系删除，开闸行为转常开：
（narrative job → 里程碑账本行 → REL-001 转写 → 投影/模式/规则审计），
报告归档 tests/eval/reports/rel-{date}.json；flag_off 影子样本走 collect 空路。
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.core.settings import get_settings
from app.services.relationship import evaluation

pytestmark = pytest.mark.xdist_group("relationship")

REPORT_DIR = Path(__file__).parent / "reports"


@pytest.fixture
def rel_eval_flags(monkeypatch):
    """v2 开关已删除，开闸行为转常开；保留空夹具以兼容既有调用点。"""
    yield


def test_relationship_eval_gate(db_session_factory, rel_eval_flags):
    now = datetime(2026, 9, 6, 12, 0, 0)
    results = evaluation.run_scenarios(db_session_factory, now=now)
    assert all("scenario_id" in result for result in results)
    report = evaluation.compute_metrics(results)
    assert report["gate_passed"] is True, report["failed_scenarios"]
    for metric_id in ("E-REL-01", "E-REL-02", "E-REL-04"):
        assert report["metrics"][metric_id]["pass"] is True, metric_id

    REPORT_DIR.mkdir(exist_ok=True)
    report_path = REPORT_DIR / f"rel-{datetime.now():%Y%m%d}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    assert report_path.exists()


def test_build_db_report_flag_on(db_session_factory, rel_eval_flags):
    report = evaluation.build_db_report()
    assert report["milestones_total"] >= 0
    assert "provenance_rate" in report


def test_collect_narrative_slice_flag_off(db_session_factory):
    assert evaluation.collect_narrative_slice("u-rel-eval-off") is None
