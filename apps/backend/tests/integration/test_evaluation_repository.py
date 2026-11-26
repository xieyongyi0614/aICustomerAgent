from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.models.evaluation import (
    DimensionScore,
    EvaluationDimension,
    EvaluationMeta,
    EvaluationReport,
    EvaluationSubjectKind,
    IssueCode,
    build_issue,
)
from app.repositories import evaluation_repository


def make_report(
    subject_id: str = "t1",
    subject: EvaluationSubjectKind = EvaluationSubjectKind.TURN,
    created_at: datetime | None = None,
    with_issue: bool = False,
) -> EvaluationReport:
    issues = [build_issue(IssueCode.PERSONA_ABUSIVE_LANGUAGE)] if with_issue else []
    return EvaluationReport(
        id=evaluation_repository.new_report_id(),
        subject=subject,
        subject_id=subject_id,
        session_id="conv-1",
        user_id="default-user",
        scores={
            EvaluationDimension.PERSONA: DimensionScore(
                dimension=EvaluationDimension.PERSONA, score=0.8
            )
        },
        overall_score=0.8 if subject != EvaluationSubjectKind.OFFLINE_BATCH else None,
        verdict="pass",
        issues=issues,
        context_digest={"reply": "你好"},
        meta=EvaluationMeta(judge_used=True, model_name="fake"),
        created_at=created_at or timeutil.now(),
    )


def test_save_and_get_roundtrip(db_session_factory):
    report = make_report(with_issue=True)
    evaluation_repository.save(report)

    loaded = evaluation_repository.get_by_subject("turn", "t1")
    assert loaded is not None
    assert loaded.id == report.id
    assert loaded.subject == EvaluationSubjectKind.TURN
    assert loaded.scores[EvaluationDimension.PERSONA].score == pytest.approx(0.8)
    assert loaded.issues[0].code == "persona_abusive_language"
    assert loaded.issues[0].severity == "critical"
    assert loaded.meta.judge_used is True
    assert loaded.context_digest["reply"] == "你好"


def test_same_subject_keeps_latest(db_session_factory):
    old = make_report(created_at=timeutil.now() - timedelta(hours=1))
    new = make_report(created_at=timeutil.now())
    evaluation_repository.save(old)
    evaluation_repository.save(new)

    loaded = evaluation_repository.get_by_subject("turn", "t1")
    assert loaded is not None
    assert loaded.id == new.id


def test_list_by_user_ordering(db_session_factory):
    for index in range(3):
        evaluation_repository.save(
            make_report(
                subject_id=f"t{index}",
                created_at=timeutil.now() - timedelta(minutes=10 - index),
            )
        )
    reports = evaluation_repository.list_by_user("default-user")
    assert [report.subject_id for report in reports] == ["t2", "t1", "t0"]


def test_retention_lazy_prune_on_save(db_session_factory):
    evaluation_repository.save(make_report(created_at=timeutil.now() - timedelta(days=60)))
    assert evaluation_repository.get_by_subject("turn", "t1") is None

    evaluation_repository.save(make_report(subject_id="t2"))
    assert evaluation_repository.get_by_subject("turn", "t2") is not None

    deleted = evaluation_repository.prune_before(timeutil.now() + timedelta(days=1))
    assert deleted == 1
    assert evaluation_repository.get_by_subject("turn", "t2") is None


def test_offline_batch_subject_roundtrip(db_session_factory):
    report = make_report(
        subject=EvaluationSubjectKind.OFFLINE_BATCH,
        subject_id="run-1",
    )
    evaluation_repository.save(report)
    loaded = evaluation_repository.get_by_subject("offline_batch", "run-1")
    assert loaded is not None
    assert loaded.overall_score is None
