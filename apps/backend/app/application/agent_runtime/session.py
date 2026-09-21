"""Session 生命周期门面（RT-002）。

Session 是 Run 的宿主：渠道身份 → `session_id` → `SessionContext`，再由 Run 挂接。
Session **无独立 SoT**（裁决 D1）：open / resume / close 不写任何会话表，`close_session`
只聚合 `loop_runs` 台账；`resume_session` 只重建「台账可证」的部分（裁决 D5）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.application.agent_runtime.contracts import (
    DEFAULT_CHARACTER_ID,
    SessionContext,
)
from app.application.agent_runtime.models import TRIGGER_CHANNEL_MESSAGE
from app.repositories import loop_run_repository
from app.services.channel_identity_service import build_session_id


@dataclass(frozen=True, slots=True)
class SessionCloseSummary:
    session_id: str
    run_count: int
    status_counts: Mapping[str, int]
    first_started_at: datetime | None
    last_finished_at: datetime | None
    closed_at: datetime


def build_session_context(
    session_id: str,
    *,
    character_id: str = DEFAULT_CHARACTER_ID,
    channel: str | None = None,
    external_user_id: str | None = None,
    thread_id: str | None = None,
    trigger_type: str = TRIGGER_CHANNEL_MESSAGE,
    run_id: str | None = None,
    now: datetime | None = None,
) -> SessionContext:
    return SessionContext(
        session_id=session_id,
        character_id=character_id,
        channel=channel,
        external_user_id=external_user_id,
        thread_id=thread_id,
        trigger_type=trigger_type,
        run_id=run_id,
        started_at=now or datetime.now(),
    )


def open_session(
    channel: str,
    external_user_id: str,
    *,
    character_id: str = DEFAULT_CHARACTER_ID,
    thread_id: str | None = None,
    trigger_type: str = TRIGGER_CHANNEL_MESSAGE,
    now: datetime | None = None,
) -> SessionContext:
    """渠道身份 → `session_id`（复用既有派生，不改结果）→ `SessionContext`。"""
    return build_session_context(
        build_session_id(channel, external_user_id),
        character_id=character_id,
        channel=channel,
        external_user_id=external_user_id,
        thread_id=thread_id,
        trigger_type=trigger_type,
        now=now,
    )


def resume_session(
    session_id: str, *, now: datetime | None = None
) -> SessionContext | None:
    """从 `loop_runs` 台账重建 `SessionContext`；无任何 Run 记录时返回 None。

    限制（D5）：仅能重建台账可证的字段（`session_id` / 触发类型 / Run 挂接）；
    `character_id` 取默认值，渠道身份为 None，由入站网关（RT-013）补全。
    """
    rows = loop_run_repository.list_recent(session_id=session_id, limit=1)
    if not rows:
        return None
    latest = rows[0]
    return build_session_context(
        session_id,
        trigger_type=latest.trigger_type or TRIGGER_CHANNEL_MESSAGE,
        run_id=latest.id,
        now=now,
    )


def close_session(
    context: SessionContext, *, now: datetime | None = None
) -> SessionCloseSummary:
    """会话收口：只聚合该 `session_id` 下全部 Run，不落会话表（D1）。"""
    rows = loop_run_repository.list_recent(session_id=context.session_id, limit=100000)
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    started = [row.started_at for row in rows if row.started_at is not None]
    finished = [row.finished_at for row in rows if row.finished_at is not None]
    return SessionCloseSummary(
        session_id=context.session_id,
        run_count=len(rows),
        status_counts=status_counts,
        first_started_at=min(started) if started else None,
        last_finished_at=max(finished) if finished else None,
        closed_at=now or datetime.now(),
    )
