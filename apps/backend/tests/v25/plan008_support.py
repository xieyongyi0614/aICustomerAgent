"""PLAN-008 单测共享构造：世界写入面 / 白名单七 op / 出站探针 / 广播探针。

只做构造与探测，不做断言（与 `plan004_support.py` / `plan005_support.py` /
`plan006_support.py` 同款纪律）。四条纪律：

1. **真实世界优先**：世界夹具经既有 `tests.v24.tool007_support` 的播种函数建（世界记录 /
   物品 / 事件 / 日程），不手搓 ORM 行；本模块只补「世界写面探针」与「op 白名单资产」。
2. **白名单即 Task Detail §4.2.3 原文**：`WORLD_OP_WHITELIST` 七值逐字对应文档表格，
   用例以它为上界做双向断言（文档值 ⊆ `world_engine` 可解析面；**产出方字面量 ⊆ 文档值**）。
3. **静态扫描复用**：扫描器与 PLAN-001 ~ PLAN-007 同源（`tests/v25/_plan_scan.py`），
   本模块只加 PLAN-008 专属的「op 字面量产出点」扫描。
4. **探针不改语义**：写面探针只记录调用并透传/兜底（`None`），判定逻辑一行未改。
"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest

from app.application import world_engine
from app.models.goal import GoalPlanRecord, GoalRecord, SubGoalSpec
from app.repositories import outbox_repository, world_repository
from app.services.planning import context as plan_context

from . import _plan_scan as scan

NOW = datetime(2026, 9, 16, 12, 0, 0)

USER = "plan8-user"
GOAL_ID = "plan8-goal"
PLAN_ID = "plan8-plan"

REMINDER_CREATE = "builtin.reminder.create"
ENV_QUERY = "world.env.query"

BROADCAST_IDEMPOTENCY_PREFIX = "char:goal_done:"

WORLD_OP_WHITELIST: tuple[str, ...] = (
    "create_event",
    "cancel_events_by_type",
    "create_object",
    "move_object",
    "apply_object_action",
    "set_environment",
    "set_location",
)
"""Task Detail §4.2.3 的合法世界操作白名单（七值，逐字对应文档表格）。"""

WORLD_OP_LITERAL_PRODUCERS: tuple[Path, ...] = (
    scan.PLANNING_PACKAGE_DIR.parent / "action" / "capabilities" / "reminder.py",
    scan.PLANNING_PACKAGE_DIR.parent / "action" / "capabilities" / "world_action.py",
    scan.PLANNING_PACKAGE_DIR.parent / "world" / "event_bridge.py",
)
"""生产 `deferred_world_op` 的**全部**现有代码点（计划层零产出，故产出集合即全仓产出集合）。"""

WORLD_WRITE_FACE: tuple[str, ...] = (
    "run_turn_update",
    "run_maintenance",
    "run_simulation_maintenance",
    "create_event",
    "cancel_events_by_type",
    "complete_events_by_type",
    "trigger_due_events",
    "expire_stale_events",
    "create_object",
    "move_object",
    "apply_object_action",
    "discard_object",
    "consume_object",
    "expire_due_objects",
    "set_environment",
    "set_location",
    "advance_time",
    "seed_default_household",
    "record_character_action_event",
    "merge_character_action_notes",
)
"""`world_engine` 的写面（装配期零调用断言的打桩集合）。"""

WORLD_DIRECT_WRITE_FACE: tuple[str, ...] = ("save_world", "save_event", "save_object")
"""`world_repository` 的直写面（装配期零调用断言的第二道探针）。"""

RELATIONSHIP_WRITE_TOKENS: tuple[str, ...] = (
    "relationship_repository",
    "relationship_event_repository",
    "relationship_bridge",
    "commit_relationship_update",
    "relationship_state",
    "relationship_events",
)

CHARACTER_DOMAIN_WRITE_TOKENS: tuple[str, ...] = (
    "character_state",
    "personality_state",
)


def repo_root() -> Path:
    return scan.REPO_ROOT


def planning_modules() -> list[Path]:
    return scan.planning_modules()


def op_literals(path: Path) -> set[str]:
    """源码中 `{"op": <字面量>}` 形态的 op 值（AST 口径：不受注释与字符串拼接影响）。"""
    found: set[str] = set()
    for node in ast.walk(scan.tree(path)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if (
                isinstance(key, ast.Constant)
                and key.value == "op"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                found.add(value.value)
    return found


def produced_op_literals() -> dict[str, set[str]]:
    return {path.name: op_literals(path) for path in WORLD_OP_LITERAL_PRODUCERS}


def world_engine_attributes_in(path: Path) -> set[str]:
    """模块内触达 `world_engine` 的全部成员名（读 + 写，属性访问 + 具名导入）。"""
    names = scan.called_attributes(path, "world_engine")
    names |= scan.import_from_names(path).get("app.application.world_engine", set())
    return names


def table_counts(session_factory) -> dict[str, int]:
    from sqlalchemy import func, select

    from app.core.db import Base

    with session_factory() as session:
        return {
            name: session.execute(select(func.count()).select_from(table)).scalar()
            for name, table in Base.metadata.tables.items()
        }


def world_event_rows(user_id: str) -> list[dict]:
    """世界事件投影（类型 / 来源 / 载荷 / 重要性 / 幂等键）：广播的落库证据。"""
    world = world_repository.get_world(user_id)
    if world is None:
        return []
    return [
        {
            "id": event.id,
            "type": event.type,
            "source": event.source.value,
            "importance": event.importance.value,
            "payload": dict(event.payload or {}),
            "idempotency_key": event.idempotency_key,
        }
        for event in world_repository.list_events(world.world_id, limit=50)
    ]


def world_object_names(user_id: str) -> list[str]:
    world = world_repository.get_world(user_id)
    if world is None:
        return []
    return [
        obj.name
        for obj in world_repository.list_objects(world.world_id, status="active")
    ]


def outbox_keys(user_id: str) -> list[str]:
    """outbox 行的幂等键（广播/出站登记的可见面）。"""
    return [row.idempotency_key for row in outbox_repository.list_pending(limit=50)]


def goal(user_id: str = USER, description: str = "规划一次旅行", **overrides) -> GoalRecord:
    payload = {
        "id": GOAL_ID,
        "user_id": user_id,
        "type": "user_care",
        "description": description,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return GoalRecord.model_validate(payload)


def step(
    index: int = 1,
    *,
    capability: str = "create_reminder",
    tool_id: str | None = REMINDER_CREATE,
    **overrides,
) -> SubGoalSpec:
    params = overrides.pop("params", {"content": "该休息了", "due_at": "2027-01-01T09:00:00"})
    payload = {
        "index": index,
        "description": overrides.pop("description", f"步骤{index}"),
        "capability": capability,
        "params": params,
        "criteria": overrides.pop(
            "criteria", {"type": "action_succeeded", "capability": capability}
        ),
        "tool_id": tool_id,
        "kind": overrides.pop("kind", "tool"),
    }
    payload.update(overrides)
    return SubGoalSpec.model_validate(payload)


def plan(specs: list[SubGoalSpec], *, goal_id: str = GOAL_ID, version: int = 1):
    return GoalPlanRecord(
        id=PLAN_ID,
        goal_id=goal_id,
        version=version,
        status="active",
        sub_goals=list(specs),
        created_at=NOW,
        updated_at=NOW,
    )


class WorldWriteProbe:
    """世界写面调用记录：`written` 为写函数名，`direct` 为仓储直写名。"""

    def __init__(self) -> None:
        self.written: list[str] = []
        self.direct: list[str] = []

    @property
    def total(self) -> int:
        return len(self.written) + len(self.direct)


def install_world_write_probe(monkeypatch) -> WorldWriteProbe:
    """打桩 `world_engine` 写面与 `world_repository` 直写面：记录调用并返回 `None`。"""
    probe = WorldWriteProbe()

    def _stub(name: str, sink: list[str]):
        def _call(*args, **kwargs):
            sink.append(name)
            return None

        return _call

    for name in WORLD_WRITE_FACE:
        monkeypatch.setattr(world_engine, name, _stub(name, probe.written))
    for name in WORLD_DIRECT_WRITE_FACE:
        monkeypatch.setattr(world_repository, name, _stub(name, probe.direct))
    return probe


def surface_context(*tool_ids: str, now: datetime | None = NOW):
    """步骤执行的鸭子类型上下文：工具面 + 执行期时刻（`PlanScheduler` 消费面）。"""
    from types import SimpleNamespace

    from app.models.tool import ToolSurface

    return SimpleNamespace(
        tool_surface=ToolSurface(run_kind="autonomous_tick", tool_ids=tuple(tool_ids)),
        now=now,
        step_cooldown_minutes=0,
    )


@pytest.fixture
def planning_world_on(override_settings):
    """PLAN-008 装配面：v25 三闸 + 世界（V2.3.0 事件链）+ 工具总闸；自动播种关闭（夹具确定）。"""
    override_settings(
        planning_enabled="true",
        plan_context_enabled="true",
        plan_observation_enabled="true",
        plan_scheduler_enabled="true",
        plan_execution_enabled="true",
        plan_step_binding_enabled="true",
        plan_tool_required="true",
        plan_world_feedback_enabled="true",
        tool_system_enabled="true",
        action_enabled="true",
        world_enabled="true",
        world_household_autoseed_enabled="false",
        action_relationship_enabled="false",
        action_outbox_enabled="false",
        observability_persist_enabled="false")
    return True


@pytest.fixture
def assembler():
    return plan_context.PlanContextAssembler()


def memoryless_facts() -> dict:
    """四源事实包的最小空壳（判据按不可判定处理：`None`，绝不默认 `True`）。"""
    return {"now": NOW, "world": {}, "state": {}, "memory": {}}
