"""场景化评估套件 runner（testing.md §3~§4）：逐场景跑引擎，断言 issue 集合与 verdict。"""

import pytest

from tests.evaluation.conftest import load_scenarios, run_scenario

SCENARIOS = load_scenarios()

DIMENSIONS = {scenario["dimension"] for scenario in SCENARIOS}


def test_scenario_suite_covers_five_dimensions():
    assert DIMENSIONS == {"persona", "emotion", "memory", "behavior", "autonomy"}
    assert len(SCENARIOS) >= 10


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
def test_scenario(scenario):
    report = run_scenario(scenario)

    actual_codes = sorted(issue.code.value if hasattr(issue.code, "value") else str(issue.code) for issue in report.issues)
    expected_codes = sorted(scenario["expect_issues"])
    assert actual_codes == expected_codes, (
        f"场景 {scenario['name']} issue 集合不符：actual={actual_codes} "
        f"expected={expected_codes} digest_scores="
        f"{ {d.value: s.score for d, s in report.scores.items()} }"
    )
    assert report.verdict == scenario["expect_verdict"], (
        f"场景 {scenario['name']} verdict 不符：actual={report.verdict} "
        f"expected={scenario['expect_verdict']}"
    )
