"""PLAN-004 单测共享构造：工具注册表 / 工具面 / 拆解上下文 / 提案与步骤工厂。

只做构造，不做断言：绑定与三闸的语义全部在 `test_plan004_*.py` 各自断言。
`ctx` 用 `SimpleNamespace` 注入——`decompose` 只消费 `tool_surface` 与 `budget` 两个投影，
故拆解单测零 DB、零世界、零 LLM（与 `PlanContext` 的装配解耦，装配属 PLAN-003）。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.models.goal import GoalRecord
from app.models.tool import ToolSurface
from app.services import goal_planning
from app.services.planning import decompose as decompose_mod
from app.services.tool.registry import ToolRegistry, register_builtin_tools

NOW = datetime(2026, 9, 16, 12, 0, 0)


@pytest.fixture(autouse=True)
def plan004_binding_on():
    """PLAN-004 绑定面锚点（历史名保留，避免 34 处用例签名变动）。

    绑定子闸 `plan_step_binding_enabled` 已随开关体系删除：绑定生效只取决于保留的
    策略位 `plan_tool_required`（默认 on）。本夹具退化为只做设置缓存隔离，
    「off 时零绑定」的旧专测语义由 `test_plan004_flags.py` 的常开断言接替。
    """
    get_settings.cache_clear()

RUN_KIND_AUTONOMOUS = "autonomous_tick"
RUN_KIND_FOREGROUND = "foreground_chat"

REMINDER_CREATE = "builtin.reminder.create"
MEMORY_SAVE = "builtin.memory.save"
ENV_QUERY = "world.env.query"
NOTIFICATION_SEND = "builtin.notification.send"
CHANNEL_SEND = "channel.feishu.send"
SEARCH_QUERY = "builtin.search.query"

DEFAULT_BUDGET: dict[str, int] = {
    "max_steps": 5,
    "max_depth": 2,
    "step_max_attempts": 2,
    "revision_budget": 3,
}


def builtin_registry() -> ToolRegistry:
    """全量内置声明注册表（10 条；状态按当前 Flag 派生）。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def tool_surface(*tool_ids: str, run_kind: str = RUN_KIND_AUTONOMOUS) -> ToolSurface:
    return ToolSurface(run_kind=run_kind, tool_ids=tuple(tool_ids))


def bound_surface() -> ToolSurface:
    """全部 `ACTION_TOOL_MAP` 候选工具的合成面（含通道工具，用于一能力多工具用例）。"""
    candidates = sorted(
        {tool_id for tool_ids in decompose_mod.ACTION_TOOL_MAP.values() for tool_id in tool_ids}
    )
    return tool_surface(*candidates)


def make_ctx(*tool_ids: str, budget: dict | None = None) -> SimpleNamespace:
    surface = tool_surface(*tool_ids) if tool_ids else bound_surface()
    return SimpleNamespace(tool_surface=surface, budget=dict(budget or DEFAULT_BUDGET))


def make_goal() -> GoalRecord:
    """内存目标记录（拆解不消费目标域，只为对齐 §6.1 签名）。"""
    return GoalRecord(
        user_id="plan4-user",
        type="user_care",
        description="规划一次旅行",
        created_at=NOW,
        updated_at=NOW,
    )


def proposal(*steps: dict) -> goal_planning.PlanningProposal:
    return goal_planning.PlanningProposal(sub_goals=[dict(step) for step in steps])


DEFAULT_STEP_PARAMS: dict = {
    "content": "提醒内容",
    "due_at": "2026-09-16T09:00:00",
}
"""`create_reminder` 的必填参数（规划期弱校验要求齐备，§5.2 / §6.5）。"""


def step(index: int = 1, capability: str = "create_reminder", **overrides) -> dict:
    """默认步骤：能力与判据一致、必填参数齐备，可用 overrides 覆盖任意字段。"""
    payload = {
        "index": index,
        "description": f"步骤{index}",
        "capability": capability,
        "params": dict(DEFAULT_STEP_PARAMS) if capability == "create_reminder" else {},
        "criteria": {"type": "action_succeeded", "capability": capability},
    }
    payload.update(overrides)
    return payload


def tool_criteria(path: str, value=None, **overrides) -> dict:
    payload = {
        "type": "field_equals",
        "source": "tool",
        "path": path,
        "value": "ok" if value is None else value,
    }
    payload.update(overrides)
    return payload


def settings():
    return get_settings()


def decompose(
    *steps: dict,
    ctx=None,
    registry=None,
    selector=None,
    settings_override=None,
):
    """拆解入口快捷式：缺省注入内置注册表与合成工具面（一能力多工具可判）。

    「注册表不可得」（工具系统总闸 off）的单列用例不走本入口：直接构造
    `TaskDecomposer()` 并 monkeypatch `decompose.get_tool_registry` 返回 `None`。
    """
    decomposer = decompose_mod.TaskDecomposer(
        registry=registry if registry is not None else builtin_registry(),
        selector=selector,
    )
    resolved_settings = settings_override if settings_override is not None else settings()
    return decomposer.decompose(
        proposal(*steps),
        make_goal(),
        ctx if ctx is not None else make_ctx(),
        settings=resolved_settings,
    )


def bind(specs, ctx=None, *, registry=None, enabled=True, selector=None):
    """阶段②直达入口：返回 (被写回派生字段的 specs 列表, bindings, errors)。"""
    work = list(specs)
    bindings, errors = decompose_mod._bind_tools(
        work,
        ctx if ctx is not None else make_ctx(),
        registry=registry if registry is not None else builtin_registry(),
        enabled=enabled,
        selector=selector,
    )
    return work, bindings, errors


def parsed(*steps: dict, max_depth: int = 2):
    return decompose_mod._parse_structure(proposal(*steps), max_depth=max_depth)
