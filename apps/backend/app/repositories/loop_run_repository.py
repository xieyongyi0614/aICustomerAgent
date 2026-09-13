"""loop_runs 周期记账仓储（LIFE-002）。

run 是账不是业务状态：create→逐步 mark_step（崩溃留 running 现场可查）→
finish 落终态与汇总。全部写入单事务、幂等键为 run_id 本身。
"""

import logging
import uuid
from datetime import datetime

from app.core.db import LoopRunRow, SessionLocal

logger = logging.getLogger(__name__)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now()


def get(run_id: str) -> LoopRunRow | None:
    with SessionLocal() as session:
        return session.query(LoopRunRow).filter(LoopRunRow.id == run_id).first()


def list_recent(
    user_id: str | None = None,
    limit: int = 50,
    status: str | None = None,
    kind: str | None = None,
    run_kind: str | None = None,
) -> list[LoopRunRow]:
    with SessionLocal() as session:
        query = session.query(LoopRunRow)
        if user_id is not None:
            query = query.filter(LoopRunRow.user_id == user_id)
        if status is not None:
            query = query.filter(LoopRunRow.status == status)
        if kind is not None:
            query = query.filter(LoopRunRow.kind == kind)
        if run_kind is not None:
            query = query.filter(LoopRunRow.run_kind == run_kind)
        return query.order_by(LoopRunRow.started_at.desc()).limit(limit).all()


def create_run(
    user_id: str | None,
    kind: str,
    reason: str,
    trigger_id: str | None = None,
    trigger_type: str | None = None,
    now: datetime | None = None,
    run_kind: str | None = None,
    profile: dict | None = None,
) -> LoopRunRow:
    now = _now(now)
    run = LoopRunRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        kind=kind,
        run_kind=run_kind,
        profile=profile,
        trigger_id=trigger_id,
        trigger_type=trigger_type,
        reason=reason,
        status="running",
        steps=[],
        llm_call_count=0,
        token_total=0,
        budget_state={},
        started_at=now,
        created_at=now,
    )
    with SessionLocal() as session:
        session.add(run)
        session.commit()
    return run


def mark_step(run_id: str, step: dict, now: datetime | None = None) -> None:
    """追加步骤记录（崩溃安全：每步落一次，现场保留已执行步骤）。"""
    now = _now(now)
    with SessionLocal() as session:
        row = session.query(LoopRunRow).filter(LoopRunRow.id == run_id).first()
        if row is None:
            return
        row.steps = list(row.steps or []) + [step]
        row.current_step = str(step.get("step", ""))
        session.commit()


def finish_run(
    run_id: str,
    status: str,
    steps: list[dict] | None = None,
    llm_call_count: int = 0,
    token_total: int = 0,
    budget_state: dict | None = None,
    now: datetime | None = None,
) -> None:
    now = _now(now)
    with SessionLocal() as session:
        row = session.query(LoopRunRow).filter(LoopRunRow.id == run_id).first()
        if row is None:
            return
        row.status = status
        if steps is not None:
            row.steps = steps
        row.llm_call_count = llm_call_count
        row.token_total = token_total
        if budget_state is not None:
            row.budget_state = budget_state
        row.finished_at = now
        session.commit()
