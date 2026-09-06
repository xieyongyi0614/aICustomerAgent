import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.core.settings import Settings, SettingsError, get_settings
from app.models.evaluation import (
    DEFAULT_SEVERITY,
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
    dimension_of,
    overall_score_from,
)
from app.models.evaluation import DimensionScore

ISSUE_CODE_COUNT = 46


def make_issue(code: IssueCode, severity: IssueSeverity | None = None) -> Issue:
    base = build_issue(code)
    if severity is not None:
        base = base.model_copy(update={"severity": severity})
    return base


def make_scores(**values: float) -> dict[EvaluationDimension, DimensionScore]:
    return {
        EvaluationDimension(name): DimensionScore(
            dimension=EvaluationDimension(name), score=value
        )
        for name, value in values.items()
    }


def test_issue_code_table_is_complete_and_consistent():
    assert len(IssueCode) == ISSUE_CODE_COUNT
    assert set(DEFAULT_SEVERITY.keys()) == set(IssueCode)
    for code in IssueCode:
        issue = build_issue(code)
        assert issue.dimension == dimension_of(code)
        assert issue.message
        assert issue.source == "rule"


def test_build_issue_truncates_evidence():
    issue = build_issue(IssueCode.PERSONA_ABUSIVE_LANGUAGE, evidence_quote="词" * 120)
    assert len(issue.evidence_quote) == 80


def test_issue_rejects_oversized_evidence():
    with pytest.raises(ValidationError):
        Issue(
            code=IssueCode.PERSONA_ABUSIVE_LANGUAGE,
            severity=IssueSeverity.CRITICAL,
            dimension=EvaluationDimension.PERSONA,
            evidence_quote="词" * 81,
        )


def test_dimension_score_bounds():
    with pytest.raises(ValidationError):
        DimensionScore(dimension=EvaluationDimension.PERSONA, score=1.5)


def test_compute_verdict_thresholds():
    assert compute_verdict([], 0.90, 0.6, 0.85) == "pass"
    assert compute_verdict([], 0.84, 0.6, 0.85) == "warn"
    assert compute_verdict([], 0.59, 0.6, 0.85) == "fail"
    critical = make_issue(IssueCode.PERSONA_ABUSIVE_LANGUAGE)
    assert compute_verdict([critical], 0.95, 0.6, 0.85) == "fail"


def test_compute_verdict_offline_batch_without_overall():
    warning = make_issue(IssueCode.PERSONA_OOC)
    info = make_issue(IssueCode.MEMORY_MISSED)
    assert compute_verdict([], None, 0.6, 0.85) == "pass"
    assert compute_verdict([info], None, 0.6, 0.85) == "pass"
    assert compute_verdict([warning], None, 0.6, 0.85) == "warn"


def test_overall_score_weights_and_normalization():
    weights = {"persona": 0.5, "behavior": 0.5}
    scores = make_scores(persona=0.8, behavior=1.0)
    assert overall_score_from(scores, weights) == pytest.approx(0.9)

    partial = make_scores(persona=0.6)
    assert overall_score_from(partial, weights) == pytest.approx(0.6)

    assert overall_score_from({}, weights) is None
    assert overall_score_from(scores, {}) is None


def test_clamp_score():
    assert clamp_score(1.5) == 1.0
    assert clamp_score(-0.2) == 0.0
    assert clamp_score(0.42) == pytest.approx(0.42)


def test_evaluation_report_construction():
    report = EvaluationReport(
        id="run-1",
        subject=EvaluationSubjectKind.TURN,
        subject_id="123",
        session_id="conv-1",
        user_id="default-user",
        scores=make_scores(persona=0.9),
        overall_score=0.9,
        verdict="pass",
        issues=[],
        meta=EvaluationMeta(judge_used=True, model_name="fake"),
        created_at=datetime.now(),
    )
    assert report.verdict == "pass"
    payload = json.loads(report.model_dump_json())
    assert payload["scores"]["persona"]["score"] == pytest.approx(0.9)
    assert payload["subject"] == "turn"


def test_settings_evaluation_defaults(monkeypatch):
    monkeypatch.delenv("EVALUATION_ENABLED", raising=False)
    monkeypatch.delenv("EVALUATION_LLM_JUDGE_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("EVALUATION_MAX_DIGEST_CHARS", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.evaluation_enabled is True
        assert settings.evaluation_llm_judge_sample_rate == 1.0
        assert settings.evaluation_penalty_critical == 0.4
        assert settings.evaluation_max_digest_chars == 2000
        weights = settings.evaluation_overall_weights("turn")
        assert weights["persona"] == pytest.approx(0.30)
        assert weights["action"] == pytest.approx(0.10)
        assert sum(weights.values()) == pytest.approx(1.0)
        assert settings.evaluation_overall_weights("proactive_action")["autonomy"] == pytest.approx(0.6)
    finally:
        get_settings.cache_clear()


def test_settings_evaluation_overrides(monkeypatch):
    monkeypatch.setenv("EVALUATION_ENABLED", "false")
    monkeypatch.setenv("EVALUATION_FAIL_SCORE", "0.5")
    monkeypatch.setenv("EVALUATION_LLM_JUDGE_SAMPLE_RATE", "0.5")
    settings = Settings()
    assert settings.evaluation_enabled is False
    assert settings.evaluation_fail_score == 0.5
    assert settings.evaluation_llm_judge_sample_rate == 0.5


def test_settings_rejects_bad_sample_rate(monkeypatch):
    monkeypatch.setenv("EVALUATION_LLM_JUDGE_SAMPLE_RATE", "1.5")
    with pytest.raises(SettingsError):
        Settings()


def test_settings_rejects_bad_weights(monkeypatch):
    monkeypatch.setenv("EVALUATION_OVERALL_WEIGHTS_JSON", "{bad json")
    with pytest.raises(SettingsError):
        Settings()

    monkeypatch.setenv(
        "EVALUATION_OVERALL_WEIGHTS_JSON",
        json.dumps({"turn": {"persona": 0.5}, "proactive_action": {"autonomy": 1.0}}),
    )
    with pytest.raises(SettingsError):
        Settings()

    monkeypatch.setenv(
        "EVALUATION_OVERALL_WEIGHTS_JSON",
        json.dumps({"turn": {"persona": 0.6, "behavior": 0.4}, "proactive_action": {"autonomy": 1.0}}),
    )
    assert Settings().evaluation_overall_weights("turn")["behavior"] == pytest.approx(0.4)
