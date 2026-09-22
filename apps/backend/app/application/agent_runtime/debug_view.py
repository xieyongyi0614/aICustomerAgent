"""Runtime 观测读门面（RT-019 / RT-ALL-code-review H-2）：Debug / Replay 的**组合层**。

分层纪律：`services/observability/trace_query.py` 只做仓储级取行；**运行时语义派生**
（段 → 六段环节 → `ErrorKind`）与**回放组合**（RT-018 执行历史投影）归本模块，
因为它们是 `application` 的知识。这样 `services` 无需 import `agent_runtime`。

- `debug_view` / `debug_views_for_session`：在仓储视图上补 `phase` / `error_kind`。
- `replay_bundle`：以 `agent_state_snapshots` 为时点锚点的只读包，不执行副作用。

零写入：全部只读（V7.5 Evaluation 铁律）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.application.agent_runtime import execution_history
from app.application.agent_runtime.loop import ERROR_KIND_BY_PHASE, STAGE_TO_PHASE
from app.services.observability import trace_query
from app.services.observability.trace_query import (
    DEFAULT_SESSION_RUN_LIMIT,
    RunDebugView,
)

__all__ = [
    "ReplayBundle",
    "RunDebugView",
    "debug_view",
    "debug_views_for_session",
    "replay_bundle",
]


@dataclass(frozen=True, slots=True)
class ReplayBundle:
    """只读回放包：调用方自行比对时点，不执行任何副作用（D4）。"""

    run_id: str
    snapshot_anchor: Mapping[str, Any] | None
    decisions: tuple[Mapping[str, Any], ...]
    actions: tuple[Mapping[str, Any], ...]
    state_changes: tuple[Mapping[str, Any], ...]
    traces: tuple[Mapping[str, Any], ...]


def annotate_stages(
    steps: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """段落账 → 调试条目：补 `phase` / `error_kind`（映射表派生，未知段标 None）。"""
    annotated: list[Mapping[str, Any]] = []
    for step in steps:
        item = dict(step)
        phase = STAGE_TO_PHASE.get(str(item.get("step") or ""))
        item["phase"] = phase
        item["error_kind"] = ERROR_KIND_BY_PHASE.get(phase) if phase else None
        annotated.append(item)
    return tuple(annotated)


def _annotated(view: RunDebugView | None) -> RunDebugView | None:
    if view is None:
        return None
    return replace(view, stages=annotate_stages(view.stages))


def debug_view(run_id: str) -> RunDebugView | None:
    """按 `run_id` 还原段顺序、耗时、降级与 `ErrorKind`（AC1）。"""
    return _annotated(trace_query.by_run_id(run_id))


def debug_views_for_session(
    session_id: str, *, limit: int = DEFAULT_SESSION_RUN_LIMIT
) -> list[RunDebugView]:
    """同 Session 的 Run 时间线（升序），条目已补 `phase` / `error_kind`。"""
    return [
        view
        for view in (_annotated(item) for item in trace_query.by_session(session_id, limit=limit))
        if view is not None
    ]


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
