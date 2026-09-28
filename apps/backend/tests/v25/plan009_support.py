"""PLAN-009 单测共享构造：判据 A 五类场景表 / 计划终态夹具 / 政策闸与投递探针。

只做构造与探测，不做断言（与 `plan004_support.py` ~ `plan008_support.py` 同款纪律）。四条纪律：

1. **判据 A 的场景以 Task Detail §4.2.1 原文为数据**：五类场景的四个输入逐条枚举，用例只做
   「输入 → 裁决」对照，不另立判据。
2. **复用既有台账**：幂等标记的承载位是既有 `action_records` 行，夹具经既有
   `action_repository.save_record` 落库（不手搓 ORM 行）。
3. **探针不改语义**：政策闸 / 落库 / 摄取三类探针只记录调用并透传（摄取探针允许注入桩返回），
   判定逻辑一行未改。
4. **静态扫描复用**：扫描器与 PLAN-001 ~ PLAN-008 同源（`tests/v25/_plan_scan.py`）。
"""

from __future__ import annotations

import ast
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.action import ActionRecord
from app.models.goal import GoalPlanRecord, GoalRecord, SubGoalSpec
from app.models.plan import PLAN_STEP_DEDUPE_KEY_TEMPLATE
from app.repositories import action_repository, memory_repository

from . import _plan_scan as scan

NOW = datetime(2026, 9, 16, 12, 0, 0)

USER = "plan9-user"
GOAL_ID = "plan9-goal"
PLAN_ID = "plan9-plan"

COMPLETED_DESCRIPTION = "把后天的面试准备好"
FAILED_DESCRIPTION = "准备周末的旅行计划"

REMINDER_CREATE = "builtin.reminder.create"
ENV_QUERY = "world.env.query"
MEMORY_SAVE = "builtin.memory.save"

PLAN_DEDUPE_KEY = "plan:plan9-goal:1:1"

TOOL_SIDE_MEMORY_DETAIL = "已记住"
"""工具侧 / V9 落库时写入的既有 detail（`action_engine._append_effect(record, "memory", ...)`）。"""

PERSIST_SCENARIOS: tuple[tuple[str, dict, bool], ...] = (
    (
        "把杯子放桌上（单步、当场可验）",
        {
            "step_count": 1,
            "cross_tick": False,
            "every_step_has_criteria": True,
            "needs_idempotency_or_recovery": False,
        },
        False,
    ),
    (
        "帮我准备后天的面试（多步、跨天）",
        {
            "step_count": 4,
            "cross_tick": True,
            "every_step_has_criteria": True,
            "needs_idempotency_or_recovery": True,
        },
        True,
    ),
    (
        "提醒我明早八点开会（单步但需跨天确认送达）",
        {
            "step_count": 1,
            "cross_tick": True,
            "every_step_has_criteria": True,
            "needs_idempotency_or_recovery": False,
        },
        False,
    ),
    (
        "周末陪我看部电影（需先查日程再定时间）",
        {
            "step_count": 2,
            "cross_tick": False,
            "every_step_has_criteria": True,
            "needs_idempotency_or_recovery": True,
        },
        True,
    ),
    (
        "今天天气怎么样（纯查询）",
        {
            "step_count": 1,
            "cross_tick": False,
            "every_step_has_criteria": False,
            "needs_idempotency_or_recovery": False,
        },
        False,
    ),
)
"""Task Detail §4.2.1 的五类场景裁决表（可判定形态）。

第三行的 ❌ 由 **A3** 承载（单步却需跨天，A1 的 `cross_tick` 分支本就成立；工具自带
`pending_confirmation` 与 `action_records` 重试 ⇒ 计划层不需要幂等 / 失败恢复），文档该行
「命中的判据」列写 A1 是简写，判定结果与表格一致。
"""


def plan_modules() -> list:
    return scan.planning_modules()


def repo_root():
    return scan.REPO_ROOT


def module_path(name: str):
    return scan.PLANNING_PACKAGE_DIR / name


def module_literals(path) -> set[str]:
    """模块内非文档字符串的字面量集合（`_plan_scan.string_literals` 同口径）。

    文档字符串与注释同口径排除：契约声明本身必须能写出被禁的取值，否则无法声明禁令。
    """
    return scan.string_literals(path)


def module_numbers(path) -> list[float]:
    return [
        node.value
        for node in ast.walk(scan.tree(path))
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ]


def function_node(path, name: str):
    for node in ast.walk(scan.tree(path)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def function_call_names(path, name: str) -> set[str]:
    """指定函数的全部调用名（`f(...)` 取 `f`，`a.f(...)` 取 `a.f`）。"""
    node = function_node(path, name)
    if node is None:
        return set()
    found: set[str] = set()
    for call in (item for item in ast.walk(node) if isinstance(item, ast.Call)):
        func = call.func
        if isinstance(func, ast.Name):
            found.add(func.id)
        elif isinstance(func, ast.Attribute):
            base = func.value.id if isinstance(func.value, ast.Name) else ""
            found.add(f"{base}.{func.attr}" if base else func.attr)
    return found


def assigned_names(path) -> set[str]:
    """模块级赋值目标名（常量复用断言：既有常量只允许 import，不允许就地重定义）。"""
    names: set[str] = set()
    for node in scan.tree(path).body:
        if isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def dict_keys(path) -> list[str]:
    """模块内全部字典字面量的字符串键（工具边界表形态的扫描面）。"""
    keys: list[str] = []
    for node in ast.walk(scan.tree(path)):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.append(key.value)
    return keys


def raw_goal(description: str, *, goal_id: str = GOAL_ID, user_id: str = USER):
    """鸭子类型目标：`GoalRecord.description` 有 40 字上限，长度预算用例需要更长的输入。"""
    return SimpleNamespace(id=goal_id, user_id=user_id, description=description)


def tool_record(
    *,
    tool_id: str = REMINDER_CREATE,
    action_type: str = "create_reminder",
    status: str = "succeeded",
    params: dict | None = None,
    dedupe_key: str = "",
    user_id: str = USER,
    goal_id: str = GOAL_ID,
) -> ActionRecord:
    """工具侧沉积判定的输入（含 `params`：模板渲染缺参会让候选落空，故必须给齐）。"""
    return ActionRecord(
        id="plan9-tool-record",
        user_id=user_id,
        goal_id=goal_id,
        action_type=action_type,
        status=status,
        dedupe_key=dedupe_key,
        params={"content": "该休息了"} if params is None else dict(params),
        steps=[
            {
                "index": 1,
                "status": status,
                "tool_id": tool_id,
                "params": {},
                "result": {"status": status},
            }
        ],
        created_at=NOW,
        updated_at=NOW,
    )


def dedupe_key(goal_id: str = GOAL_ID, version: int = 1, index: int = 1) -> str:
    """计划域幂等键（既有模板，零硬编码）：幂等标记落在同前缀的台账行上。"""
    return PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(
        goal_id=goal_id, version=version, index=index
    )


def goal(description: str = COMPLETED_DESCRIPTION, **overrides) -> GoalRecord:
    payload = {
        "id": GOAL_ID,
        "user_id": USER,
        "type": "user_care",
        "description": description,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return GoalRecord.model_validate(payload)


def step(index: int = 1, **overrides) -> SubGoalSpec:
    capability = overrides.pop("capability", "create_reminder")
    payload = {
        "index": index,
        "description": overrides.pop("description", f"步骤{index}"),
        "capability": capability,
        "params": overrides.pop("params", {"content": "该休息了"}),
        "criteria": overrides.pop(
            "criteria", {"type": "action_succeeded", "capability": capability}
        ),
        "tool_id": overrides.pop("tool_id", REMINDER_CREATE),
        "kind": overrides.pop("kind", "tool"),
    }
    payload.update(overrides)
    return SubGoalSpec.model_validate(payload)


def plan(specs: list[SubGoalSpec] | None = None, *, goal_id: str = GOAL_ID, version: int = 1):
    return GoalPlanRecord(
        id=PLAN_ID,
        goal_id=goal_id,
        version=version,
        status="active",
        sub_goals=list(specs) if specs is not None else [step()],
        created_at=NOW,
        updated_at=NOW,
    )


def plan_record(
    *,
    user_id: str = USER,
    goal_id: str = GOAL_ID,
    dedupe_key: str = PLAN_DEDUPE_KEY,
    record_id: str = "plan9-action",
    effects: list[dict] | None = None,
) -> ActionRecord:
    """计划域台账行（幂等标记的承载位）：`result.effects` 可注入既有工具侧标记做正交性对照。"""
    return ActionRecord(
        id=record_id,
        user_id=user_id,
        goal_id=goal_id,
        action_type="create_reminder",
        status="succeeded",
        dedupe_key=dedupe_key,
        steps=[{"index": 1, "status": "succeeded", "tool_id": REMINDER_CREATE}],
        result={"status": "succeeded", "effects": list(effects or [])},
        created_at=NOW,
        updated_at=NOW,
    )


def seed_plan_record(**overrides) -> ActionRecord:
    """落库一条计划域台账行（幂等标记的读写面）。"""
    return action_repository.save_record(plan_record(**overrides))


def stored_record(record_id: str = "plan9-action") -> ActionRecord | None:
    return action_repository.get_record(record_id)


def receipt_effects(record: ActionRecord) -> list[dict]:
    return list((record.result or {}).get("effects") or [])


def memories(user_id: str = USER) -> list:
    return memory_repository.list_by_user(user_id, limit=50)


def memory_contents(user_id: str = USER) -> list[str]:
    return [memory.content for memory in memories(user_id)]


def ingest_row(content: str, row_id: str = "cand-1") -> SimpleNamespace:
    """`ingest_from_goal_completion` 的返回形态（既有 `MemoryCandidateRow` 的鸭子类型投影）。"""
    return SimpleNamespace(id=row_id, content=content)


class DeliveryProbe:
    """政策闸 / 落库 / 摄取的调用记录（判定逻辑一行未改，只记调用序列）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.policy_candidates: list[list] = []
        self.saved: list[dict] = []
        self.ingested: list[tuple] = []

    @property
    def order(self) -> list[str]:
        return list(self.calls)


def install_delivery_probe(monkeypatch, *, ingest_content: str | None = None) -> DeliveryProbe:
    """打桩三处既有入口：`apply_policy` / `create_memory` / `ingest_from_goal_completion`。

    `ingest_content=None` 时摄取探针返回桩行（内容由用例给定）；给 `""` 即模拟「无候选行」。
    """
    from app.repositories import memory_repository as repo
    from app.services import memory_policy as policy_gate
    from app.services.memory2 import ingest as ingest_mod

    probe = DeliveryProbe()
    original_policy = policy_gate.apply_policy
    original_create = repo.create_memory

    def _policy(candidates, active_contents=None):
        probe.calls.append("apply_policy")
        probe.policy_candidates.append(list(candidates))
        return original_policy(candidates, active_contents)

    def _create(user_id, character_id, content, memory_type, importance, **kwargs):
        probe.calls.append("create_memory")
        probe.saved.append(
            {
                "user_id": user_id,
                "content": content,
                "type": memory_type,
                "importance": importance,
                "source": kwargs.get("source"),
            }
        )
        return original_create(
            user_id, character_id, content, memory_type, importance, **kwargs
        )

    def _ingest(user_id, goal_id, description):
        probe.calls.append("ingest_from_goal_completion")
        probe.ingested.append((user_id, goal_id, description))
        content = ingest_content
        if content is None:
            content = f"完成了目标：{description}"
        return None if content == "" else ingest_row(content)

    monkeypatch.setattr(policy_gate, "apply_policy", _policy)
    monkeypatch.setattr(repo, "create_memory", _create)
    monkeypatch.setattr(ingest_mod, "ingest_from_goal_completion", _ingest)
    return probe


def read_only_definition(tool_id: str, *, policy_key: str | None = None):
    """读类工具声明（`side_effects ⊆ {read}`）：硬纪律①「读类强制不沉淀」的输入。"""
    from app.models.tool import PermissionProfile, ToolDefinition, ToolSchema

    namespace = tool_id.split(".")[0]
    return ToolDefinition(
        id=tool_id,
        name=tool_id,
        description=f"{tool_id} 读类探针",
        namespace=namespace,
        capability="reminder",
        action="create",
        input_schema=ToolSchema(),
        permission=PermissionProfile(level="normal"),
        side_effects=("read",),
        memory_policy_key=policy_key,
    )


def install_ingest_stub(monkeypatch, *, content: str | None = None) -> list[tuple]:
    """只打桩既有摄取入口（返回桩行 / 无行），记录调用参数——I6 复用举证的轻量探针。"""
    from app.services.memory2 import ingest as ingest_mod

    calls: list[tuple] = []

    def _ingest(user_id, goal_id, description):
        calls.append((user_id, goal_id, description))
        resolved = f"完成了目标：{description}" if content is None else content
        return None if resolved == "" else ingest_row(resolved)

    monkeypatch.setattr(ingest_mod, "ingest_from_goal_completion", _ingest)
    return calls


def latest_candidate_row(session_factory, goal_id: str):
    """既有 `memory_candidates` 行的投影（摄取通道的落库证据：source / status / content）。

    经测试会话读取：`app.core.db.SessionLocal` 未被 autouse 夹具替换，直用会连真实库。
    """
    from sqlalchemy import select

    from app.core.db import MemoryCandidateRow

    stmt = select(MemoryCandidateRow).where(
        MemoryCandidateRow.source_id == f"{goal_id}:completed"
    )
    with session_factory() as session:
        return session.scalars(stmt).first()


@pytest.fixture
def planning_memory_on(override_settings):
    """PLAN-009 记忆面：编排与记忆子闸已随开关体系删除转常开；执行面保持开启（夹具确定）。"""
    override_settings(
        plan_tool_required="true",
        action_memory_policy_enabled="true",
        action_relationship_enabled="false",
        action_outbox_enabled="false",
        observability_persist_enabled="false")
    return True
