"""V7.8 低质量下钻：评估反向查询 + include=correlation。"""

from datetime import datetime, timedelta

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.models.evaluation import (
    DimensionScore,
    EvaluationDimension,
    EvaluationReport,
    EvaluationSubjectKind,
    build_issue,
    IssueCode,
)
from app.models.observability import RuntimeTrace, TraceKind, TraceStep
from app.repositories import evaluation_repository, trace_repository


def _report(
    report_id,
    subject_id,
    verdict,
    dimension=EvaluationDimension.EMOTION,
    score=0.4,
    with_issue=True,
    created_at=None,
):
    return EvaluationReport(
        id=report_id,
        subject=EvaluationSubjectKind.TURN,
        subject_id=subject_id,
        user_id="default-user",
        scores={dimension: DimensionScore(dimension=dimension, score=score)},
        overall_score=score,
        verdict=verdict,
        issues=[build_issue(IssueCode.EMOTION_OVERSHIFT)] if with_issue else [],
        created_at=created_at or datetime.now(),
    )


def _seed():
    now = datetime.now()
    trace_repository.save(
        RuntimeTrace(
            trace_id="s-req-low",
            kind=TraceKind.TURN,
            user_id="default-user",
            conversation_id="s-search",
            turn_id="7001",
            status="degraded",
            duration_ms=80.0,
            steps=[TraceStep(name="state_update", status="degraded", duration_ms=5.0)],
        )
    )
    evaluation_repository.save(
        _report(
            "low-3", "7003", "fail", dimension=EvaluationDimension.MEMORY,
            with_issue=False, created_at=now - timedelta(seconds=120),
        )
    )
    evaluation_repository.save(
        _report("low-2", "7002", "pass", with_issue=False, created_at=now - timedelta(seconds=60))
    )
    evaluation_repository.save(_report("low-1", "7001", "fail", created_at=now))


@pytest.mark.asyncio
async def test_evaluation_search_filters_and_correlation(db_session_factory):
    _seed()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fails = await client.get("/api/v1/debug/evaluations", params={"verdict": "fail"})
        assert fails.status_code == 200
        rows = fails.json()
        assert {row["subject_id"] for row in rows} == {"7001", "7003"}

        by_issue = await client.get(
            "/api/v1/debug/evaluations", params={"issue_code": "emotion_overshift"}
        )
        assert {row["subject_id"] for row in by_issue.json()} == {"7001"}

        by_dimension = await client.get(
            "/api/v1/debug/evaluations", params={"dimension": "memory"}
        )
        assert {row["subject_id"] for row in by_dimension.json()} == {"7003"}

        detailed = await client.get(
            "/api/v1/debug/evaluations",
            params={"verdict": "fail", "include": "correlation", "limit": 1},
        )
        rows = detailed.json()
        assert len(rows) == 1
        correlation = rows[0]["correlation"]
        assert correlation["trace"]["request_id"] == "s-req-low"
        assert correlation["evaluation"]["verdict"] == "fail"


@pytest.mark.asyncio
async def test_evaluation_search_empty_window(db_session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/debug/evaluations", params={"window_hours": 0.000001}
        )
        assert resp.status_code == 200
        assert resp.json() == []
