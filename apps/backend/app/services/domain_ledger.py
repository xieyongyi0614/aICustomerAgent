"""多域审计账本只读门面（R-5 / H-3）。

供 Runtime 版本投影与执行历史聚合调用：`application` 不得直连域仓储读。
纯直通、零行为变化；调用点经模块属性迟绑定，便于测试打桩。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.repositories import (
    action_repository,
    agent_state_snapshot_repository,
    decision_repository,
    development_change_repository,
    relationship_event_repository,
    trace_repository,
)


def count_relationship_events(user_id: str) -> int:
    return relationship_event_repository.count_events(user_id)


def latest_relationship_event_at(user_id: str) -> datetime | None:
    rows = relationship_event_repository.list_events(user_id, limit=1)
    return getattr(rows[0], "created_at", None) if rows else None


def list_relationship_events(
    user_id: str,
    *,
    session_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
) -> list[Any]:
    return relationship_event_repository.list_events(
        user_id, limit, session_id=session_id, since=since, until=until
    )


def count_development_changes(user_id: str) -> int:
    return development_change_repository.count_changes(user_id)


def latest_development_change_at(user_id: str) -> datetime | None:
    return development_change_repository.latest_change(user_id)


def list_development_changes(
    user_id: str, *, since: datetime | None = None, until: datetime | None = None
) -> list[Any]:
    return development_change_repository.list_changes(user_id, since=since, until=until)


def count_decisions(user_id: str) -> int:
    return decision_repository.count_by_user(user_id)


def search_decisions(
    *,
    user_id: str | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    action_id: str | None = None,
    request_id: str | None = None,
    limit: int = 50,
) -> list[Any]:
    return decision_repository.search(
        user_id=user_id,
        kind=kind,
        since=since,
        until=until,
        action_id=action_id,
        request_id=request_id,
        limit=limit,
    )


def list_decisions_by_action(action_id: str) -> list[Any]:
    return decision_repository.get_by_action(action_id)


def list_decisions_by_user_window(
    user_id: str, started_at: datetime, finished_at: datetime
) -> list[Any]:
    return decision_repository.list_rows_by_user_window(user_id, started_at, finished_at)


def latest_decision_at(user_id: str) -> datetime | None:
    rows = decision_repository.search(user_id=user_id, limit=1)
    return getattr(rows[0], "created_at", None) if rows else None


def count_active_actions(user_id: str) -> int:
    return action_repository.count_active(user_id)


def recent_actions(user_id: str, *, limit: int = 20) -> list[Any]:
    return action_repository.recent_records(user_id, limit=limit)


def list_actions_by_run_id(run_id: str, *, limit: int = 100) -> list[Any]:
    return action_repository.list_by_run_id(run_id, limit=limit)


def latest_action_at(user_id: str) -> datetime | None:
    rows = action_repository.recent_records(user_id, limit=1)
    return getattr(rows[0], "created_at", None) if rows else None


def get_action_record(action_id: str) -> Any:
    return action_repository.get_record(action_id)


def latest_state_snapshot(user_id: str, character_id: str = "asuna") -> Any:
    return agent_state_snapshot_repository.latest(user_id, character_id)


def state_snapshot_by_run_id(run_id: str) -> Any:
    return agent_state_snapshot_repository.get_by_run_id(run_id)


def list_traces_by_user_window(
    user_id: str, started_at: datetime, finished_at: datetime
) -> list[Any]:
    return trace_repository.list_rows_by_user_window(user_id, started_at, finished_at)


def list_traces_by_action_ids(action_ids: list[str]) -> list[Any]:
    return trace_repository.list_by_action_ids(action_ids)


def list_traces_by_correlation_id(correlation_id: str) -> list[Any]:
    return trace_repository.list_by_correlation_id(correlation_id)
