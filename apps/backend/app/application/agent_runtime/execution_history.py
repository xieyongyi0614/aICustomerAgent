"""执行历史只读投影（RT-018）：跨表聚合 Debug / Replay / Evaluation 取材。

全部只读：任何查询零 `INSERT/UPDATE/DELETE`（D5 / AC5）。关联策略——
trace 按 `correlation_id` / `action_id` / 用户时间窗；decision 按 `action_id` /
`request_id` / 用户时间窗；action 按 `run_id`；状态变更按用户时间窗与
`session_id`；锚点取 `agent_state_snapshots`（`run_id` 优先，否则 latest）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.application.agent_runtime.contracts import DEFAULT_CHARACTER_ID
from app.repositories import loop_run_repository
from app.services import domain_ledger


def _row_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "model_dump"):
        return dict(row.model_dump())
    table = getattr(row, "__table__", None)
    if table is not None:
        return {col.name: getattr(row, col.name) for col in table.columns}
    return {
        name: getattr(row, name)
        for name in vars(row)
        if not name.startswith("_")
    }


@dataclass(frozen=True, slots=True)
class ExecutionHistory:
    run_id: str
    run: Mapping[str, Any]
    traces: tuple[Mapping[str, Any], ...]
    decisions: tuple[Mapping[str, Any], ...]
    actions: tuple[Mapping[str, Any], ...]
    state_changes: tuple[Mapping[str, Any], ...]
    snapshot_anchor: Mapping[str, Any] | None


def latest_snapshot_anchor(
    user_id: str, character_id: str = DEFAULT_CHARACTER_ID
) -> Mapping[str, Any] | None:
    row = domain_ledger.latest_state_snapshot(user_id, character_id)
    return _row_mapping(row) if row is not None else None


def _history_window(
    started_at: datetime, finished_at: datetime | None
) -> tuple[datetime, datetime]:
    ended = finished_at or datetime.now()
    if ended < started_at:
        ended = started_at
    return started_at, ended + timedelta(seconds=1)


def _collect_traces(
    run_id: str,
    action_ids: list[str],
    user_id: str | None,
    window: tuple[datetime, datetime],
) -> list[Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for row in domain_ledger.list_traces_by_correlation_id(run_id):
        rows[row.id] = _row_mapping(row)
    for row in domain_ledger.list_traces_by_action_ids(action_ids):
        rows[row.id] = _row_mapping(row)
    if user_id:
        for row in domain_ledger.list_traces_by_user_window(
            user_id, window[0], window[1]
        ):
            rows[row.id] = _row_mapping(row)
    return list(rows.values())


def _collect_decisions(
    run_id: str,
    action_ids: list[str],
    user_id: str | None,
    window: tuple[datetime, datetime],
) -> list[Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for action_id in action_ids:
        for record in domain_ledger.list_decisions_by_action(action_id):
            rows[record.id] = _row_mapping(record)
    for record in domain_ledger.search_decisions(request_id=run_id, limit=100):
        rows[record.id] = _row_mapping(record)
    if user_id:
        for row in domain_ledger.list_decisions_by_user_window(
            user_id, window[0], window[1]
        ):
            rows[row.id] = _row_mapping(row)
    return list(rows.values())


def _collect_state_changes(
    session_id: str | None,
    user_id: str | None,
    window: tuple[datetime, datetime],
) -> list[Mapping[str, Any]]:
    changes: list[Mapping[str, Any]] = []
    if user_id:
        for row in domain_ledger.list_development_changes(
            user_id, since=window[0], until=window[1]
        ):
            item = _row_mapping(row)
            item["source"] = "development_changes"
            changes.append(item)
        for event in domain_ledger.list_relationship_events(
            user_id, session_id=session_id, since=window[0], until=window[1], limit=200
        ):
            item = _row_mapping(event)
            item["source"] = "relationship_events"
            changes.append(item)
    return changes


def history_for_run(run_id: str) -> ExecutionHistory | None:
    run = loop_run_repository.get(run_id)
    if run is None:
        return None
    started_at = run.started_at or datetime.now()
    window = _history_window(started_at, run.finished_at)
    action_records = domain_ledger.list_actions_by_run_id(run_id)
    action_ids = [record.id for record in action_records]
    user_id = run.user_id
    session_id = run.session_id
    anchor_row = domain_ledger.state_snapshot_by_run_id(run_id)
    if anchor_row is None and user_id:
        anchor_row = domain_ledger.latest_state_snapshot(user_id)
    return ExecutionHistory(
        run_id=run_id,
        run=_row_mapping(run),
        traces=tuple(_collect_traces(run_id, action_ids, user_id, window)),
        decisions=tuple(_collect_decisions(run_id, action_ids, user_id, window)),
        actions=tuple(_row_mapping(record) for record in action_records),
        state_changes=tuple(_collect_state_changes(session_id, user_id, window)),
        snapshot_anchor=_row_mapping(anchor_row) if anchor_row is not None else None,
    )


def history_for_session(session_id: str, *, limit: int = 50) -> list[ExecutionHistory]:
    rows = loop_run_repository.list_recent(session_id=session_id, limit=max(1, limit))
    histories: list[ExecutionHistory] = []
    for row in rows:
        history = history_for_run(row.id)
        if history is not None:
            histories.append(history)
    return histories
