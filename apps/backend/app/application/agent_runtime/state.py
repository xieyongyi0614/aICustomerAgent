"""Runtime State Manager（RT-003）：带版本、带时点一致性的状态门面。

把 V2.1 Agent State Assembler 的「规则投影」升级为「读哪一版 / 当前到哪一版 /
两版差什么」：版本一律是**既有审计行的只读聚合**（零新表，Q3 裁决），门面对业务表
**零写入**；`reconcile` 只出裁决报告，写入仍回各域合法通道（RT-012）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.application import agent_state_assembler
from app.application.agent_runtime.contracts import (
    DEFAULT_CHARACTER_ID,
    RuntimeEvent,
)
from app.core.settings import get_settings
from app.models.agent_state import AgentStateSnapshot
from app.repositories import (
    action_repository,
    agent_state_snapshot_repository,
    decision_repository,
    development_change_repository,
    relationship_event_repository,
)

FAST_DOMAINS: frozenset[str] = frozenset(
    {"mood", "energy", "intensity", "relationship"}
)
SLOW_DOMAINS: frozenset[str] = frozenset({"personality", "goal"})

SNAPSHOT_DOMAINS: tuple[str, ...] = (
    "character",
    "goal",
    "memory",
    "world",
    "personality",
)

_OBSERVED: dict[tuple[str, str], "StateVersion"] = {}


@dataclass(frozen=True, slots=True)
class StateVersion:
    domain: str
    version: int | None
    basis: str
    latest_at: datetime | None
    observed_at: datetime
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeState:
    snapshot: AgentStateSnapshot
    snapshot_version: int
    time_point: datetime
    versions: Mapping[str, StateVersion]


@dataclass(frozen=True, slots=True)
class ReconcileConflict:
    domain: str
    kind: str
    snapshot_value: Any
    write_value: Any
    resolution: str


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    time_point: datetime
    snapshot_version: int
    conflicts: tuple[ReconcileConflict, ...]
    resolved: Mapping[str, Any]


def _first_created_at(rows: list) -> datetime | None:
    if not rows:
        return None
    return getattr(rows[0], "created_at", None)


def _ledger_source(
    domain: str,
    count_fn: Callable[[str], int],
    latest_fn: Callable[[str], datetime | None],
) -> Callable[[str, str, datetime | None], StateVersion]:
    def _build(user_id: str, _character_id: str, now: datetime | None) -> StateVersion:
        observed_at = now or datetime.now()
        try:
            count = count_fn(user_id)
            latest_at = latest_fn(user_id)
        except Exception:
            return StateVersion(domain, None, "unavailable", None, observed_at)
        return StateVersion(domain, count, "ledger", latest_at, observed_at)

    return _build


def _snapshot_source(
    domain: str,
) -> Callable[[str, str, datetime | None], StateVersion]:
    def _build(user_id: str, character_id: str, now: datetime | None) -> StateVersion:
        observed_at = now or datetime.now()
        try:
            row = agent_state_snapshot_repository.latest(user_id, character_id)
        except Exception:
            return StateVersion(domain, None, "unavailable", None, observed_at)
        if row is None:
            return StateVersion(domain, None, "snapshot", None, observed_at)
        return StateVersion(domain, row.version, "snapshot", row.created_at, observed_at)

    return _build


DOMAIN_SOURCES: dict[str, Callable[[str, str, datetime | None], StateVersion]] = {
    "relationship": _ledger_source(
        "relationship",
        relationship_event_repository.count_events,
        lambda user_id: _first_created_at(
            relationship_event_repository.list_events(user_id, limit=1)
        ),
    ),
    "development": _ledger_source(
        "development",
        development_change_repository.count_changes,
        development_change_repository.latest_change,
    ),
    "decision": _ledger_source(
        "decision",
        lambda user_id: len(decision_repository.search(user_id=user_id, limit=1000)),
        lambda user_id: _first_created_at(
            decision_repository.search(user_id=user_id, limit=1)
        ),
    ),
    "action": _ledger_source(
        "action",
        action_repository.count_active,
        lambda user_id: _first_created_at(
            action_repository.recent_records(user_id, limit=1)
        ),
    ),
}
for _domain in SNAPSHOT_DOMAINS:
    DOMAIN_SOURCES[_domain] = _snapshot_source(_domain)


def snapshot(
    user_id: str,
    character_id: str = DEFAULT_CHARACTER_ID,
    now: datetime | None = None,
) -> AgentStateSnapshot:
    return agent_state_assembler.assemble(user_id, character_id, now)


def version(
    domain: str,
    user_id: str,
    character_id: str = DEFAULT_CHARACTER_ID,
    now: datetime | None = None,
) -> StateVersion:
    source = DOMAIN_SOURCES.get(domain)
    if source is None:
        return StateVersion(domain, None, "unavailable", None, now or datetime.now())
    return source(user_id, character_id, now)


def observe(domain: str, event: RuntimeEvent) -> None:
    """接收域写事件，仅更新进程内观察缓存（不落库）。"""
    _OBSERVED[(domain, event.run_id)] = StateVersion(
        domain,
        None,
        "event",
        event.occurred_at,
        event.occurred_at,
        {"event_type": event.event_type},
    )


def observed_version(domain: str, run_id: str) -> StateVersion | None:
    return _OBSERVED.get((domain, run_id))


def reset_observed_cache() -> None:
    _OBSERVED.clear()


def _snapshot_value(agent_state: AgentStateSnapshot, domain: str) -> Any:
    if domain == "goal":
        focus = agent_state.current_focus
        return getattr(focus, "goal_id", None) if focus is not None else None
    if domain == "relationship":
        return agent_state.relationship
    return getattr(agent_state, domain, None)


def reconcile(
    agent_state: AgentStateSnapshot,
    writes: Mapping[str, Any],
    now: datetime | None = None,
) -> ReconcileReport:
    """纯函数：只裁决快 / 慢变量冲突，不执行任何写入。"""
    conflicts: list[ReconcileConflict] = []
    resolved: dict[str, Any] = {}
    for domain, write_value in writes.items():
        snapshot_value = _snapshot_value(agent_state, domain)
        if snapshot_value == write_value:
            conflict = ReconcileConflict(
                domain, "noop", snapshot_value, write_value, "no_change"
            )
            final = snapshot_value
        elif domain in SLOW_DOMAINS:
            conflict = ReconcileConflict(
                domain,
                "stale_snapshot",
                snapshot_value,
                write_value,
                "snapshot_retained",
            )
            final = snapshot_value
        else:
            conflict = ReconcileConflict(
                domain, "value_conflict", snapshot_value, write_value, "write_wins"
            )
            final = write_value
        conflicts.append(conflict)
        resolved[domain] = final
    return ReconcileReport(
        time_point=now or datetime.now(),
        snapshot_version=agent_state.snapshot_version,
        conflicts=tuple(conflicts),
        resolved=resolved,
    )


def activate(
    run,
    user_id: str,
    character_id: str = DEFAULT_CHARACTER_ID,
    now: datetime | None = None,
) -> RuntimeState | None:
    """Run 开始时按 `run.started_at` 钉住时点并冻结；开关关闭时不落 `run.data`。"""
    if run is None or not get_settings().runtime_state_versioning_enabled:
        return None
    cached = run.data.get("runtime_state")
    if cached is not None:
        return cached
    time_point = run.started_at or now or datetime.now()
    agent_state = snapshot(user_id, character_id, now=time_point)
    versions = {
        domain: version(domain, user_id, character_id, now=time_point)
        for domain in DOMAIN_SOURCES
    }
    state = RuntimeState(
        snapshot=agent_state,
        snapshot_version=agent_state.snapshot_version,
        time_point=time_point,
        versions=versions,
    )
    run.data["runtime_state"] = state
    return state


def current(run) -> RuntimeState | None:
    if run is None:
        return None
    return run.data.get("runtime_state")


def reset(run) -> None:
    if run is not None:
        run.data.pop("runtime_state", None)
