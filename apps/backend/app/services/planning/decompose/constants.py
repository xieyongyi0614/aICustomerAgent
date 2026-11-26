"""PLAN-004 拆解模块的共享常量与轻量助手（原 `decompose.py` 的常量段）。

拆包后常量集中在此，`validator.py`（三闸）与 `decomposer.py`（四阶段）共同消费；
`PlanStepSpec` 别名、`_reason` / `_budget_int` 两个无依赖助手同置此处，避免两个子模块互相导入。
"""

from __future__ import annotations

from app.models.goal import SubGoalSpec
from app.services.goal import planning as goal_planning

PlanStepSpec = SubGoalSpec
"""§4.2.1 的 `PlanStepSpec` 即**扩展后的 `SubGoalSpec`**（本任务零新建步骤模型）。"""

STEP_KIND_TOOL = "tool"
STEP_KIND_OBSERVE = "observe"
STEP_KIND_COMPOSITE = "composite"

BINDING_REASON_TOOL_SELECTOR = "tool_selector"
BINDING_REASON_CAPABILITY_MAP = "capability_map"
BINDING_REASON_FALLBACK = "fallback"

BINDING_REASONS: tuple[str, ...] = (
    BINDING_REASON_TOOL_SELECTOR,
    BINDING_REASON_CAPABILITY_MAP,
    BINDING_REASON_FALLBACK,
)
"""`binding_reason` 三值（Task Detail §4.2.2）：裁决路径与实际情况一致方可进审计。"""

REASON_INVALID_SHAPE = goal_planning.REASON_INVALID_SHAPE
REASON_COUNT_EXCEEDED = goal_planning.REASON_COUNT_EXCEEDED
REASON_TOOL_UNRESOLVABLE = "plan_tool_unresolvable"
REASON_TOOL_OFF_SURFACE = "plan_tool_off_surface"
REASON_BINDING_MISSING = "capability_binding_missing"
REASON_DEPTH_EXCEEDED = "plan_depth_exceeded"
REASON_STEP_ATTEMPTS_EXCEEDED = "plan_step_attempts_exceeded"
REASON_TTL_EXCEEDED = "plan_ttl_exceeded"
REASON_PLAN_VERSIONS_INVALID = "plan_versions_invalid"
REASON_INVALID_BINDING = "invalid_step_binding"
REASON_INVALID_EFFECTS = "invalid_expected_effects"
REASON_INVALID_PARAMS = "invalid_step_params"
REASON_CRITERIA_UNSUPPORTED = "plan_criteria_unsupported"

GATE_REASONS: tuple[str, ...] = (
    REASON_INVALID_SHAPE,
    REASON_TOOL_UNRESOLVABLE,
    REASON_TOOL_OFF_SURFACE,
    REASON_BINDING_MISSING,
    REASON_COUNT_EXCEEDED,
)
"""与 PLAN-003 §4.2.4 七道闸共用的理由码（复用而非另立）。"""

EXTENDED_REASONS: tuple[str, ...] = (
    REASON_DEPTH_EXCEEDED,
    REASON_STEP_ATTEMPTS_EXCEEDED,
    REASON_TTL_EXCEEDED,
    REASON_PLAN_VERSIONS_INVALID,
    REASON_INVALID_BINDING,
    REASON_INVALID_EFFECTS,
    REASON_INVALID_PARAMS,
    REASON_CRITERIA_UNSUPPORTED,
)
"""本任务新增的理由码（七道闸未覆盖的预算三项 / 绑定一致性 / 弱校验 / 判据合法性），逐条声明。"""

BUDGET_MAX_STEPS = "max_steps"
BUDGET_MAX_DEPTH = "max_depth"
BUDGET_STEP_MAX_ATTEMPTS = "step_max_attempts"
BUDGET_TTL_HOURS = "ttl_hours"
BUDGET_GOAL_WINDOW_HOURS = "goal_max_active_hours"

BUDGET_KEYS: tuple[str, ...] = (
    BUDGET_MAX_STEPS,
    BUDGET_MAX_DEPTH,
    BUDGET_STEP_MAX_ATTEMPTS,
    BUDGET_TTL_HOURS,
    BUDGET_GOAL_WINDOW_HOURS,
)

PLAN_LEVELS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "L1",
        "Goal",
        "GoalRecord",
        "goal_planning.materialize / goal_service.review",
        "Planning / Autonomy",
        "一句话可陈述，短期不可直接执行",
    ),
    (
        "L2",
        "Task",
        "PlanStepSpec（= 扩展后的 SubGoalSpec）",
        "TaskDecomposer",
        "PlanScheduler / PlanExecutorBridge",
        "有独立达成判据 + 独立工具绑定 + 可在一次 Action 内完成",
    ),
    (
        "L3",
        "Action",
        "ActionIntent / ActionRecord",
        "PlanExecutorBridge（PLAN-005）",
        "action_engine",
        "一次六闸门 + 单步 ActionStep 装配",
    ),
    (
        "L4",
        "Tool",
        "ToolBinding / ToolExecution",
        "ToolSelector",
        "ToolExecutor",
        "一次原子外部调用",
    ),
)
"""L1~L4 四级映射的可举证清单（Task Detail §4.2.3）：逐列与 architecture.md §3.5 对照。"""

TASK_GRANULARITY_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("G1", "有独立达成判据", "step.criteria 非空（且已过判据白名单校验）"),
    ("G2", "有独立工具绑定", "step.tool_id 合法且 ∈ 工具面"),
    ("G3", "可在一次 Action 内完成", "叶子步（非 composite）且已界定 retry_policy / on_failure"),
)
"""L2 粒度三条判据（Task Detail §4.2.4）：可判定、可举证、可回归。"""

_RETRY_POLICY_DEFAULT = "once"
_ON_FAILURE_DEFAULT = "skip"
_ON_FAILURE_BLOCKING = "abort"
_UNBOUND_RETRY_POLICY = "none"
_STEP_DEPTH_ROOT = 1
_FIRST_PLAN_VERSION = 1
_SIDE_EFFECT_PREFIXES: tuple[str, ...] = ("write_", "send_")
_CRITERION_TYPE_KEY = "type"
_CRITERION_SOURCE_KEY = "source"
_CRITERION_PATH_KEY = "path"
_CRITERION_CHILDREN_KEY = "children"
_CRITERION_FIELD_EQUALS = "field_equals"
_CRITERION_THRESHOLD_REACHED = "threshold_reached"
_IDEMPOTENCY_NONE = "none"


def _reason(code: str, detail: str) -> str:
    """可读理由：`<理由码>:<中文说明>`——理由码可与 PLAN-003 §4.2.4 逐条对照。"""
    return f"{code}:{detail}"


def _budget_int(budget: dict[str, int], key: str) -> int:
    try:
        return int(budget.get(key, 0))
    except (TypeError, ValueError):
        return 0
