"""Runtime Persistence & Recovery（RT-018）：孤儿 Run 回收 + Session 续接。

「恢复」= Session 视角开启下一次 Run；进程重启**不重放**未完成 Run，也不恢复
Run 内中间态。扫掠只写 `loop_runs` 自身台账（steps / status / finished_at），
幂等：已收敛或未超时的 Run 零副作用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core import timeutil
from app.application.agent_runtime.contracts import SessionContext
from app.application.agent_runtime.session import resume_session
from app.core.settings import get_settings
from app.repositories import loop_run_repository

logger = logging.getLogger(__name__)

ORPHAN_STEP = {
    "step": "orphan_sweep",
    "status": "error",
    "error": "orphan_timeout",
}


def _now(now: datetime | None) -> datetime:
    return timeutil.ensure_aware(now) or timeutil.now()


def _timeout_minutes(timeout_minutes: int | None) -> int:
    if timeout_minutes is not None:
        return max(0, int(timeout_minutes))
    return max(0, int(get_settings().runtime_orphan_run_timeout_minutes))


def pending_orphan_ids(now: datetime | None = None) -> list[str]:
    """只读预览：当前会被扫掠收敛的 run_id 列表（不产生写入）。"""
    now = _now(now)
    cutoff = now - timedelta(minutes=_timeout_minutes(None))
    return [row.id for row in loop_run_repository.list_running_started_before(cutoff)]


def sweep_orphan_runs(
    now: datetime | None = None, *, timeout_minutes: int | None = None
) -> list[str]:
    """running 且超时的 Run → aborted；返回被收敛的 run_id（幂等：重复扫掠返回空）。"""
    if not get_settings().runtime_orphan_run_sweep_enabled:
        return []
    now = _now(now)
    cutoff = now - timedelta(minutes=_timeout_minutes(timeout_minutes))
    candidates = loop_run_repository.list_running_started_before(cutoff)
    swept: list[str] = []
    for row in candidates:
        existing = list(row.steps or [])
        if any(step.get("step") == "orphan_sweep" for step in existing):
            continue
        steps = existing + [dict(ORPHAN_STEP)]
        loop_run_repository.finish_run(
            row.id,
            status="aborted",
            steps=steps,
            llm_call_count=row.llm_call_count or 0,
            token_total=row.token_total or 0,
            budget_state=row.budget_state or {},
            now=now,
        )
        swept.append(row.id)
    if swept:
        logger.info(
            "孤儿 Run 收敛：%d 条（timeout=%smin）",
            len(swept),
            _timeout_minutes(timeout_minutes),
        )
    return swept


def resume_session_context(session_id: str) -> SessionContext | None:
    """Session 续接下一次 Run 的载体；不恢复 Run 内中间态（D4）。"""
    return resume_session(session_id)
