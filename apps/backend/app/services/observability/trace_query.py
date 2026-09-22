"""Runtime Observability 查询面（RT-019）：Debug / Replay 的**仓储级只读**读面。

分层纪律（RT-ALL-code-review H-2）：本模块位于 `services`，**只依赖 `app.repositories`**，
不得 import `app.application.agent_runtime`（允许方向是 application → services）。
因此这里只做「按 run / session / correlation 取行」，不含任何运行时语义派生；
段序 / 错误类型映射与回放组合由上层门面 `application/agent_runtime/debug_view.py` 完成。

- **Debug**：`by_run_id` / `by_session` / `by_correlation`——段顺序、耗时、降级原因与因果链关联集。
- **Replay / Evaluation**：见 `application/agent_runtime/debug_view.py`（组合 RT-018 执行历史投影）。

零写入（V7.5 Evaluation 铁律）：全部为只读查询。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.repositories import (
    action_repository,
    decision_repository,
    loop_run_repository,
    trace_repository,
)

logger = logging.getLogger(__name__)

LAYER_TRACE = "trace"
LAYER_DECISION = "decision"
LAYER_ACTION = "action"

DEFAULT_SESSION_RUN_LIMIT = 50
DEFAULT_CORRELATION_LIMIT = 200


@dataclass(frozen=True, slots=True)
class RunDebugView:
    """一次 Run 的台账视图（段顺序 / 耗时 / 降级 / 预算）。

    `stages` 原样承载 `loop_runs.steps` 的条目（含 `phase` / `error_kind`，若产生方已落账）；
    本层不派生任何运行时语义。
    """

    run_id: str
    session_id: str | None
    run_kind: str | None
    trigger_type: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    stages: tuple[Mapping[str, Any], ...]
    llm_call_count: int
    budget_state: Mapping[str, Any]

    @property
    def degraded(self) -> bool:
        """终态为 degraded，或任一段落账为 error（后台 `promote_degraded=False` 时）。"""
        return self.status == "degraded" or any(
            str(stage.get("status")) == "error" for stage in self.stages
        )

    @property
    def failed_stages(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            stage for stage in self.stages if str(stage.get("status")) == "error"
        )

    @property
    def correlation_id(self) -> str:
        """Run 的因果链标识：段事件与 trace 落库都用 `run_id`（D3）。"""
        return self.run_id


def _row_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "model_dump"):
        return dict(row.model_dump())
    table = getattr(row, "__table__", None)
    if table is not None:
        return {column.name: getattr(row, column.name) for column in table.columns}
    return {name: getattr(row, name) for name in vars(row) if not name.startswith("_")}


def _view_of(row: Any) -> RunDebugView:
    return RunDebugView(
        run_id=row.id,
        session_id=row.session_id,
        run_kind=row.run_kind,
        trigger_type=row.trigger_type,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        stages=tuple(
            dict(step) for step in (row.steps or []) if isinstance(step, Mapping)
        ),
        llm_call_count=int(row.llm_call_count or 0),
        budget_state=dict(row.budget_state or {}),
    )


def by_run_id(run_id: str) -> RunDebugView | None:
    """按 `run_id` 取一次 Run 的台账视图（段顺序 / 耗时 / 降级 / 错误）。"""
    row = loop_run_repository.get(run_id)
    return _view_of(row) if row is not None else None


def by_session(
    session_id: str, *, limit: int = DEFAULT_SESSION_RUN_LIMIT
) -> list[RunDebugView]:
    """同 Session 的 Run 时间线，按 `started_at` 升序（旧 → 新）。"""
    rows = loop_run_repository.list_recent(session_id=session_id, limit=max(1, limit))
    views = [_view_of(row) for row in rows]
    views.sort(key=lambda view: (view.started_at, view.run_id))
    return views


def _put(
    entries: dict[tuple[str, str], Mapping[str, Any]],
    layer: str,
    key: str,
    payload: Mapping[str, Any],
) -> None:
    item = dict(payload)
    item["layer"] = layer
    entries[(layer, key)] = item


def by_correlation(
    correlation_id: str, *, limit: int = DEFAULT_CORRELATION_LIMIT
) -> list[Mapping[str, Any]]:
    """因果链关联集：trace + decision + action（层内按行序，同 id 去重）。

    关联方式：trace 直接按 `correlation_id`；decision 按 `request_id` 与 trace 携带的
    `action_id`；action 按 `run_id`（Run 因果链）与上述 `action_id`（主动链，RT-017）。
    """
    entries: dict[tuple[str, str], Mapping[str, Any]] = {}
    action_ids: list[str] = []

    for row in trace_repository.list_by_correlation_id(correlation_id, limit=limit):
        _put(entries, LAYER_TRACE, row.id, _row_mapping(row))
        if row.action_id:
            action_ids.append(row.action_id)

    decisions = list(decision_repository.search(request_id=correlation_id, limit=limit))
    for action_id in action_ids:
        decisions.extend(decision_repository.get_by_action(action_id))
    for record in decisions:
        _put(entries, LAYER_DECISION, record.id, _row_mapping(record))
        if record.action_id:
            action_ids.append(record.action_id)

    actions = {
        record.id: record
        for record in action_repository.list_by_run_id(correlation_id, limit=limit)
    }
    for action_id in action_ids:
        record = action_repository.get_record(action_id)
        if record is not None:
            actions[record.id] = record
    for record in actions.values():
        _put(entries, LAYER_ACTION, record.id, _row_mapping(record))

    return list(entries.values())
