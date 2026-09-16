"""PLAN-011 共享构造：审计行播种 / 计划步骤构造 / 管理面 HTTP 入口 / 只读探针。

只做构造与探测，不做断言（与 `plan004_support.py` ~ `plan010_support.py` 同款纪律）。
四条纪律：

1. **复用既有写面**：目标 / 计划经 `goal_repository` 既有函数落库；审计行经
   `observer` 的两条公共写入面（`record_plan_advance` / `record_plan_revision`）落
   `decision_records`，**不手写行对象**（否则投影对照失去意义）。
2. **审计落库经既有仓储**：`observability.on_decision` 是进程内的采集入口（受
   `observability_persist_enabled` 异步门控），用例一律把它接到
   `decision_repository.save`，使「写入面 → 行 → 投影」三段在内存 SQLite 上闭环。
3. **只读探针不改语义**：`ReadOnlySession` 只在会话级拦截写方法（记录为调用名），
   读路径原样透传——被探测对象仍是既有实现。
4. **管理面经真实路由**：HTTP 用例走 `app.main.app` 的 ASGI 传输，
   `ASGITransport` 的引用使本目录用例被 `tests/conftest.py` 标记为 `api`。
"""

from __future__ import annotations

from datetime import datetime

from httpx import ASGITransport, AsyncClient

from app.application import observability
from app.main import app
from app.models.observability import DecisionRecord
from app.models.plan import PlanAdvance, PlanRevision
from app.repositories import decision_repository

NOW = datetime(2026, 9, 16, 12, 0, 0)
USER = "plan11-user"
OTHER_USER = "plan11-other-user"

REMINDER_CREATE = "builtin.reminder.create"
OFF_SURFACE_TOOL = "world.object.teleport"

PLAN_DEBUG_BASE = "/api/v1/debug/plans"

PLAN_ROUTER_BASE = "/debug/plans"

PLAN_ROUTER_PATHS: tuple[str, ...] = (
    PLAN_ROUTER_BASE,
    f"{PLAN_ROUTER_BASE}/{{plan_id}}",
    f"{PLAN_ROUTER_BASE}/{{plan_id}}/steps",
    f"{PLAN_ROUTER_BASE}/context",
    f"{PLAN_ROUTER_BASE}/revisions",
    f"{PLAN_ROUTER_BASE}/pending",
)
"""六个端点在 `debug_router` 上的路径形状（§6.3；不含 `/api/v1` 前缀）。"""

WRITE_CALL_NAMES: tuple[str, ...] = (
    "add",
    "add_all",
    "commit",
    "delete",
    "merge",
    "flush",
    "execute",
    "bulk_save_objects",
)


class ReadOnlySession:
    """会话级只读探针：拦截写方法并记名，读方法原样透传。"""

    def __init__(self, session) -> None:
        self._session = session
        self.writes: list[str] = []

    def __getattr__(self, name):
        if name in WRITE_CALL_NAMES:
            return lambda *args, **kwargs: self.writes.append(name)
        return getattr(self._session, name)

    def __enter__(self):
        self._session.__enter__()
        return self

    def __exit__(self, *exc):
        return self._session.__exit__(*exc)


def readonly_sessions(monkeypatch, module, session_factory) -> list[ReadOnlySession]:
    """把模块的 `SessionLocal` 接到只读探针；返回探针清单（断言 `writes` 全空）。"""
    probes: list[ReadOnlySession] = []

    def _factory():
        probe = ReadOnlySession(session_factory())
        probes.append(probe)
        return probe

    monkeypatch.setattr(module, "SessionLocal", _factory)
    return probes


async def plan_get(path: str, **params):
    """计划调试面 GET（真实路由 + ASGI 传输）。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path, params=params)


def plan_url(path: str) -> str:
    return f"{PLAN_DEBUG_BASE}{path}"


def step_spec(
    index: int = 1,
    *,
    capability: str = "create_reminder",
    tool_id: str | None = None,
    kind: str = "tool",
    status: str = "pending",
    depends_on: list[int] | None = None,
    last_attempt_at: datetime | None = None,
    on_failure: str = "skip",
    observation_keys: tuple[str, ...] = (),
    expected_effects: tuple[str, ...] = (),
    binding_reason: str | None = None,
) -> dict:
    """计划步骤构造（`SubGoalSpec.model_validate` 的入参形态，零硬编码字段）。

    形参多于 5 个与「无独立 docstring」的少量 pylint 提示属测试构造器的既有形态
    （与 `plan006_support.tool_definition` / `plan010_support` 同款），不引入生产面。
    """
    return {
        "index": index,
        "description": f"步骤{index}",
        "capability": capability,
        "params": {},
        "criteria": {"type": "action_succeeded", "capability": capability},
        "kind": kind,
        "tool_id": tool_id,
        "status": status,
        "depends_on": list(depends_on or []),
        "last_attempt_at": last_attempt_at,
        "on_failure": on_failure,
        "observation_keys": observation_keys,
        "expected_effects": expected_effects,
        "binding_reason": binding_reason,
    }


def advance(
    goal_id: str,
    plan_id: str,
    *,
    decision: str = "advanced",
    reason: str = "plan_step_advanced",
    version: int = 1,
    step_index: int | None = 1,
    at: datetime = NOW,
) -> PlanAdvance:
    return PlanAdvance(
        goal_id=goal_id,
        plan_id=plan_id,
        plan_version=version,
        decision=decision,
        reason=reason,
        at=at,
        step_index=step_index,
        facts_digest={"sources": ["world"]},
    )


def revision(
    from_version: int,
    to_version: int,
    *,
    reason: str = "step_attempt_exhausted",
    trigger_source: str | None = None,
    evidence_refs: list[str] | None = None,
    kept_steps: list[int] | None = None,
    at: datetime = NOW,
) -> PlanRevision:
    return PlanRevision(
        from_version=from_version,
        to_version=to_version,
        reason=reason,
        trigger_source=trigger_source or reason,
        at=at,
        evidence_refs=list(evidence_refs or []),
        kept_steps=list(kept_steps or []),
    )


def persist_decisions(monkeypatch) -> None:
    """把审计采集入口接到既有决策仓储（写入面 → 行 → 投影三段闭环）。"""
    monkeypatch.setattr(observability, "on_decision", decision_repository.save)


def goal_decision_rows(user_id: str, *, decision: str | None = None) -> list[DecisionRecord]:
    """该用户的计划审计行（`kind='goal_lifecycle'`；可选按 `decision` 过滤）。"""
    rows = decision_repository.search(
        user_id=user_id, kind="goal_lifecycle", limit=200
    )
    if decision is None:
        return rows
    return [row for row in rows if row.decision == decision]
