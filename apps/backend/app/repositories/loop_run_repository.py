"""loop_runs 周期记账仓储（LIFE-002）。

run 是账不是业务状态：create→逐步 mark_step（崩溃留 running 现场可查）→
finish 落终态与汇总。全部写入单事务、幂等键为 run_id 本身。
"""

import logging
from datetime import datetime

from app.core import timeutil
from app.core import ids
from app.core.db import LoopRunRow, SessionLocal

logger = logging.getLogger(__name__)


def _now(now: datetime | None) -> datetime:
    return timeutil.ensure_aware(now) or timeutil.now()


def get(run_id: str) -> LoopRunRow | None:
    with SessionLocal() as session:
        return session.query(LoopRunRow).filter(LoopRunRow.id == run_id).first()


def list_running_started_before(cutoff: datetime, limit: int = 200) -> list[LoopRunRow]:
    """status=running 且 started_at 早于 cutoff 的 Run（孤儿扫掠候选，只读）。"""
    with SessionLocal() as session:
        return (
            session.query(LoopRunRow)
            .filter(LoopRunRow.status == "running", LoopRunRow.started_at < cutoff)
            .order_by(LoopRunRow.started_at.asc())
            .limit(limit)
            .all()
        )


def list_recent(
    user_id: str | None = None,
    limit: int = 50,
    status: str | None = None,
    kind: str | None = None,
    run_kind: str | None = None,
    session_id: str | None = None,
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
        if session_id is not None:
            query = query.filter(LoopRunRow.session_id == session_id)
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
    session_id: str | None = None,
) -> LoopRunRow:
    now = _now(now)
    run = LoopRunRow(
        id=ids.new_id_str(),
        user_id=user_id,
        kind=kind,
        run_kind=run_kind,
        profile=profile,
        trigger_id=trigger_id,
        trigger_type=trigger_type,
        reason=reason,
        session_id=session_id,
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
    """追加步骤记录（崩溃安全：每步落一次，现场保留已执行步骤）。

    PG 下 `FOR UPDATE` 行锁，消除与孤儿扫掠的 RMW 竞态；SQLite 单写事务内读改写。
    """
    now = _now(now)
    with SessionLocal() as session:
        query = session.query(LoopRunRow).filter(LoopRunRow.id == run_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        row = query.first()
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
) -> bool:
    """Run Close：终态 + 成本汇总。

    **仅 `running` 可关**（M-5）：条件 UPDATE 原子落终态，扫掠与真实关账不互相覆盖。
    返回是否真正完成关账（未关账 = 行不存在或已非 `running`）。
    """
    now = _now(now)
    values: dict = {
        "status": status,
        "llm_call_count": llm_call_count,
        "token_total": token_total,
        "finished_at": now,
    }
    if steps is not None:
        values["steps"] = steps
    if budget_state is not None:
        values["budget_state"] = budget_state
    with SessionLocal() as session:
        updated = (
            session.query(LoopRunRow)
            .filter(LoopRunRow.id == run_id, LoopRunRow.status == "running")
            .update(values, synchronize_session=False)
        )
        session.commit()
        return bool(updated)
