"""Runtime Observability 查询面（RT-019）：Debug / Replay / Evaluation 只读取材。

三种消费场景（architecture §7.2）共用同一读面，**零写入**（V7.5 Evaluation 铁律）：

- **Debug**：`by_run_id` / `by_session` / `by_correlation`——段顺序、耗时、降级原因、
  `ErrorKind` 与因果链（`correlation_id`）关联集。
- **Replay**：`replay_bundle`——以 `agent_state_snapshots` 为时点锚点的只读包
  （锚点 + 决策 + 行动 + 状态变更 + trace），不执行任何副作用。
- **Evaluation**：`execution_history.history_for_run`（RT-018 投影）+ 既有指标。

关联策略（D2/D3）：段序以 `loop_runs.steps` 为权威，`runtime_traces` 为补充；
`ErrorKind` 由 `loop.STAGE_TO_PHASE` / `ERROR_KIND_BY_PHASE`（唯一映射表）派生，
未知阶段（`abort` / `orphan_sweep` 等伪步骤）标记缺失而非报错；`correlation_id`
只来自既有链路（Run / 段事件 / RT-017 主动链），本模块不新造键。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.agent_runtime import execution_history
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
    """一次 Run 的调试视图：段顺序 / 耗时 / 降级 / 预算账户。"""

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


@dataclass(frozen=True, slots=True)
class ReplayBundle:
    """只读回放包：调用方自行比对时点，不执行任何副作用（D4）。"""

    run_id: str
    snapshot_anchor: Mapping[str, Any] | None
    decisions: tuple[Mapping[str, Any], ...]
    actions: tuple[Mapping[str, Any], ...]
    state_changes: tuple[Mapping[str, Any], ...]
    traces: tuple[Mapping[str, Any], ...]


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


def _annotate_stages(steps: Any) -> tuple[Mapping[str, Any], ...]:
    """`loop_runs.steps` → 调试视图条目，补 `phase` / `error_kind`（映射表派生）。"""
    raw = [step for step in (steps or []) if isinstance(step, Mapping)]
    try:
        from app.application.agent_runtime.loop import (
            ERROR_KIND_BY_PHASE,
            STAGE_TO_PHASE,
        )
    except Exception:  # noqa: BLE001 — 调试视图不得因映射不可用而失败
        logger.exception("段映射不可用，调试视图只返回原始步骤")
        return tuple(dict(step) for step in raw)
    annotated: list[Mapping[str, Any]] = []
    for step in raw:
        item = dict(step)
        phase = STAGE_TO_PHASE.get(str(item.get("step") or ""))
        item["phase"] = phase
        item["error_kind"] = ERROR_KIND_BY_PHASE.get(phase) if phase else None
        annotated.append(item)
    return tuple(annotated)


def _view_of(row: Any) -> RunDebugView:
    return RunDebugView(
        run_id=row.id,
        session_id=row.session_id,
        run_kind=row.run_kind,
        trigger_type=row.trigger_type,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        stages=_annotate_stages(row.steps),
        llm_call_count=int(row.llm_call_count or 0),
        budget_state=dict(row.budget_state or {}),
    )


def by_run_id(run_id: str) -> RunDebugView | None:
    """按 `run_id` 还原一次 Run 的段顺序、耗时、降级与错误（AC1）。"""
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


def replay_bundle(run_id: str) -> ReplayBundle | None:
    """只读回放包：取材委托 RT-018 执行历史投影（零写入、零副作用）。"""
    history = execution_history.history_for_run(run_id)
    if history is None:
        return None
    return ReplayBundle(
        run_id=history.run_id,
        snapshot_anchor=history.snapshot_anchor,
        decisions=history.decisions,
        actions=history.actions,
        state_changes=history.state_changes,
        traces=history.traces,
    )
