import pytest

from app.core.settings import get_settings
from app.models.evaluation import (
    DimensionScore,
    EvaluationDimension,
    Issue,
    IssueCode,
)
from app.services import evaluation_rules
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import (
    RULES,
    compute_rule_scores,
    eligible_dimensions,
    penalty_for,
    rule_active,
    run_rules,
    to_dimension_scores,
)


class DummyRule(evaluation_rules.EvaluationRule):
    def __init__(self, code, dimension, issue=None, exc=None, subjects=("turn",)):
        self.code = code
        self.dimension = dimension
        self.subjects = subjects
        self._issue = issue
        self._exc = exc

    def evaluate(self, ctx):
        if self._exc is not None:
            raise self._exc
        return self._issue


def make_ctx(subject: str = "turn") -> EvaluationContext:
    return EvaluationContext(
        subject=subject, subject_id="1", session_id="c", user_id="u"
    )


@pytest.fixture(autouse=True)
def restore_rules():
    saved = list(RULES)
    yield
    RULES[:] = saved


def test_run_rules_filters_by_subject():
    proactive_only = DummyRule(
        IssueCode.AUTONOMY_TIMING_VIOLATION,
        EvaluationDimension.AUTONOMY,
        issue=None,
        subjects=("proactive_action",),
    )
    RULES[:] = [proactive_only]
    assert run_rules(make_ctx("turn")) == []
    assert rule_active(proactive_only, make_ctx("proactive_action"), get_settings())


def test_run_rules_isolates_rule_exceptions():
    broken = DummyRule(
        IssueCode.PERSONA_OOC,
        EvaluationDimension.PERSONA,
        exc=RuntimeError("boom"),
    )
    healthy = DummyRule(
        IssueCode.BEHAVIOR_BUDGET_EXCEEDED,
        EvaluationDimension.BEHAVIOR,
        issue=Issue(
            code=IssueCode.BEHAVIOR_BUDGET_EXCEEDED,
            severity="warning",
            dimension=EvaluationDimension.BEHAVIOR,
        ),
    )
    RULES[:] = [broken, healthy]
    issues = run_rules(make_ctx())
    assert [issue.code for issue in issues] == ["behavior_budget_exceeded"]


def test_run_rules_honors_dimension_toggle(monkeypatch):
    monkeypatch.setenv("EVALUATION_BEHAVIOR_ENABLED", "false")
    get_settings.cache_clear()
    try:
        rule = DummyRule(
            IssueCode.BEHAVIOR_BUDGET_EXCEEDED,
            EvaluationDimension.BEHAVIOR,
            issue=Issue(
                code=IssueCode.BEHAVIOR_BUDGET_EXCEEDED,
                severity="warning",
                dimension=EvaluationDimension.BEHAVIOR,
            ),
        )
        RULES[:] = [rule]
        assert run_rules(make_ctx()) == []
        assert eligible_dimensions("turn", get_settings()) == []
    finally:
        get_settings.cache_clear()


def test_run_rules_honors_development_dimension_toggle(monkeypatch):
    monkeypatch.setenv("EVALUATION_DEVELOPMENT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert get_settings().evaluation_development_enabled is False
        rule = DummyRule(
            IssueCode.DEVELOPMENT_CHANGE_UNATTRIBUTED,
            EvaluationDimension.DEVELOPMENT,
            issue=Issue(
                code=IssueCode.DEVELOPMENT_CHANGE_UNATTRIBUTED,
                severity="critical",
                dimension=EvaluationDimension.DEVELOPMENT,
            ),
        )
        RULES[:] = [rule]
        assert run_rules(make_ctx()) == []
        assert eligible_dimensions("turn", get_settings()) == []
    finally:
        get_settings.cache_clear()


def test_compute_rule_scores_penalty_and_absence():
    settings = get_settings()
    eligible = [
        EvaluationDimension.PERSONA,
        EvaluationDimension.BEHAVIOR,
    ]
    issues = [
        Issue(
            code=IssueCode.PERSONA_ABUSIVE_LANGUAGE,
            severity="critical",
            dimension=EvaluationDimension.PERSONA,
        ),
        Issue(
            code=IssueCode.PERSONA_OOC,
            severity="warning",
            dimension=EvaluationDimension.PERSONA,
        ),
    ]
    scores = compute_rule_scores(issues, eligible, settings)
    assert scores[EvaluationDimension.PERSONA] == pytest.approx(
        1.0 - settings.evaluation_penalty_critical - settings.evaluation_penalty_warning
    )
    assert scores[EvaluationDimension.BEHAVIOR] == pytest.approx(1.0)


def test_compute_rule_scores_clamps_at_zero():
    settings = get_settings()
    issues = [
        Issue(
            code=IssueCode.BEHAVIOR_BUDGET_EXCEEDED,
            severity="warning",
            dimension=EvaluationDimension.BEHAVIOR,
        )
    ] * 6
    scores = compute_rule_scores(issues, [EvaluationDimension.BEHAVIOR], settings)
    assert scores[EvaluationDimension.BEHAVIOR] == 0.0


def test_penalty_for_all_severities():
    settings = get_settings()
    assert penalty_for("critical", settings) == settings.evaluation_penalty_critical
    assert penalty_for("warning", settings) == settings.evaluation_penalty_warning
    assert penalty_for("info", settings) == settings.evaluation_penalty_info


def test_to_dimension_scores():
    scores = to_dimension_scores({EvaluationDimension.PERSONA: 0.9})
    assert isinstance(scores[EvaluationDimension.PERSONA], DimensionScore)
    assert scores[EvaluationDimension.PERSONA].rule_score == pytest.approx(0.9)


def test_empty_registry_leaves_dimensions_absent():
    RULES[:] = []
    assert run_rules(make_ctx()) == []
    assert eligible_dimensions("turn") == []
