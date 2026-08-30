"""V7.5 evaluation_reports 仓储（persistence.md §4）。

同一 subject 允许多次评估并存，查询口返回 created_at 最新一条；
retention 惰性清理在 save 路径顺带执行。
"""

import logging
import uuid
from datetime import datetime, timedelta

from app.core.db import EvaluationReportRow, SessionLocal
from app.core.settings import get_settings
from app.models.evaluation import EvaluationMeta, EvaluationReport, Issue

logger = logging.getLogger(__name__)


def _to_model(row: EvaluationReportRow) -> EvaluationReport:
    return EvaluationReport(
        id=row.id,
        subject=row.subject,
        subject_id=row.subject_id,
        session_id=row.session_id,
        user_id=row.user_id,
        character_id=row.character_id,
        overall_score=row.overall_score,
        verdict=row.verdict,
        scores=row.scores or {},
        issues=[Issue(**issue) for issue in (row.issues or [])],
        context_digest=row.context_digest or {},
        meta=EvaluationMeta(**(row.meta or {})),
        created_at=row.created_at,
    )


def _from_model(report: EvaluationReport) -> EvaluationReportRow:
    return EvaluationReportRow(
        id=report.id,
        subject=report.subject.value,
        subject_id=report.subject_id,
        session_id=report.session_id,
        user_id=report.user_id,
        character_id=report.character_id,
        overall_score=report.overall_score,
        verdict=report.verdict,
        scores={
            dimension.value if hasattr(dimension, "value") else dimension: score.model_dump()
            for dimension, score in report.scores.items()
        },
        issues=[issue.model_dump() for issue in report.issues],
        context_digest=report.context_digest,
        meta=report.meta.model_dump(),
        created_at=report.created_at,
    )


def save(report: EvaluationReport) -> None:
    now = datetime.now()
    with SessionLocal() as session:
        session.add(_from_model(report))
        session.commit()
    prune_before(now - timedelta(days=get_settings().evaluation_retention_days))


def get_by_subject(subject: str, subject_id: str) -> EvaluationReport | None:
    with SessionLocal() as session:
        row = (
            session.query(EvaluationReportRow)
            .filter(
                EvaluationReportRow.subject == subject,
                EvaluationReportRow.subject_id == subject_id,
            )
            .order_by(EvaluationReportRow.created_at.desc())
            .first()
        )
        return _to_model(row) if row is not None else None


def list_by_user(user_id: str, limit: int = 50, offset: int = 0) -> list[EvaluationReport]:
    with SessionLocal() as session:
        rows = (
            session.query(EvaluationReportRow)
            .filter(EvaluationReportRow.user_id == user_id)
            .order_by(EvaluationReportRow.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def list_since(
    cutoff: datetime,
    verdict: str | None = None,
    limit: int = 2000,
) -> list[EvaluationReport]:
    with SessionLocal() as session:
        query = session.query(EvaluationReportRow).filter(
            EvaluationReportRow.created_at >= cutoff
        )
        if verdict is not None:
            query = query.filter(EvaluationReportRow.verdict == verdict)
        rows = (
            query.order_by(EvaluationReportRow.created_at.desc())
            .limit(max(1, min(limit, 5000)))
            .all()
        )
        return [_to_model(row) for row in rows]


def prune_before(cutoff: datetime) -> int:
    with SessionLocal() as session:
        deleted = (
            session.query(EvaluationReportRow)
            .filter(EvaluationReportRow.created_at < cutoff)
            .delete()
        )
        session.commit()
        return deleted


def new_report_id() -> str:
    return uuid.uuid4().hex
