"""V2.5.0 Planning System 计划域运行期值对象（architecture.md §4.1 ~ §4.9 / PLAN-002）。

纯值对象层：零 IO、零执行、零治理逻辑——不触达仓储、不调 LLM、不做状态迁移判定。
与 `models/goal.py` / `models/tool.py` 同级，依赖方向只允许指向同为模型层的模块
（禁止 `app.repositories` / `app.services` / `app.application`，由静态扫描断言强制）。

职责边界：本模块只回答「计划、步骤、上下文、结果长什么样」，不生成计划、不校验计划、
不执行计划。装配属 PLAN-003，拆解属 PLAN-004，执行 / 观测 / 修订属 PLAN-005。

值集单一来源：步骤级枚举（`STEP_KINDS` / `RETRY_MODES` / `ON_FAILURE_MODES`）定义在
`goal.py`（`SubGoalSpec` 所在处，是避免模型层循环导入的唯一可行落点），本模块按
Task Detail §6.1 契约**再导出**，对外仍以本模块为唯一类型契约入口。
"""

from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

from app.models.goal import (
    GOAL_PRIORITY_MAX,
    GOAL_PRIORITY_MIN,
    ON_FAILURE_MODES,
    ON_FAILURE_MODE_VALUES,
    RETRY_MODES,
    RETRY_MODE_VALUES,
    STEP_KINDS,
    STEP_KIND_VALUES,
    GoalDomain,
    GoalLayer,
    GoalRecord,
    GoalStatus,
    GoalType,
    OnFailureMode,
    RetryMode,
    StepKind,
)
from app.models.reflection import InsightSummary
from app.models.tool import ToolBinding, ToolFailureKind, ToolSurface
from app.models.world import WorldContext
from app.models.world_simulation import SceneProfile, UserSituation, WorldBrief

PlanStepOutcomeStatus = Literal[
    "succeeded",
    "failed",
    "timeout",
    "blocked",
    "skipped",
    "hold",
]

PLAN_STEP_OUTCOMES: tuple[str, ...] = (
    "succeeded",
    "failed",
    "timeout",
    "blocked",
    "skipped",
    "hold",
)

PLAN_STEP_OUTCOME_VALUES: frozenset[str] = frozenset(get_args(PlanStepOutcomeStatus))

PlanAdvanceDecision = Literal[
    "advanced",
    "completed",
    "failed",
    "replanning",
    "skipped",
    "hold",
]

PLAN_ADVANCE_DECISIONS: tuple[str, ...] = (
    "advanced",
    "completed",
    "failed",
    "replanning",
    "skipped",
    "hold",
)

PLAN_ADVANCE_DECISION_VALUES: frozenset[str] = frozenset(get_args(PlanAdvanceDecision))

PLAN_ADVANCE_TERMINAL_DECISIONS: tuple[str, ...] = (
    "completed",
    "failed",
    "skipped",
)

PlanRevisionReason = Literal[
    "step_attempt_exhausted",
    "tool_persistently_unavailable",
    "criteria_undecidable",
    "insight_driven",
]

PLAN_REVISION_REASONS: tuple[str, ...] = (
    "step_attempt_exhausted",
    "tool_persistently_unavailable",
    "criteria_undecidable",
    "insight_driven",
)

PLAN_REVISION_REASON_VALUES: frozenset[str] = frozenset(get_args(PlanRevisionReason))

PLAN_STEP_DEDUPE_KEY_TEMPLATE: str = "plan:{goal_id}:{version}:{index}"

PLAN_ACTION_DEDUPE_KEY_TEMPLATE: str = "goal:{goal_id}:{version}:{index}"

PLAN_STEP_ACTION_CONFIDENCE: str = "confident"

PLAN_STEP_ACTION_SOURCE: str = "autonomy"

PLAN_STEP_ATTEMPT_INCREMENT_STATUSES: tuple[str, ...] = ("succeeded", "failed")

PLAN_STEP_OUTCOME_ACTION_STATUS: dict[str, str | None] = {
    "succeeded": "succeeded",
    "failed": "failed",
    "timeout": "failed",
    "blocked": "cancelled",
    "skipped": None,
    "hold": "planned",
}

PLAN_STEP_BLOCKED_GATE_REASONS: tuple[str, ...] = (
    "capability_unavailable",
    "permission_denied",
    "invalid_params",
    "pending_confirmation",
)

__all__ = [
    "ON_FAILURE_MODES",
    "ON_FAILURE_MODE_VALUES",
    "OnFailureMode",
    "PLAN_ACTION_DEDUPE_KEY_TEMPLATE",
    "PLAN_ADVANCE_DECISIONS",
    "PLAN_ADVANCE_DECISION_VALUES",
    "PLAN_ADVANCE_TERMINAL_DECISIONS",
    "PLAN_REVISION_REASONS",
    "PLAN_REVISION_REASON_VALUES",
    "PLAN_STEP_ACTION_CONFIDENCE",
    "PLAN_STEP_ACTION_SOURCE",
    "PLAN_STEP_ATTEMPT_INCREMENT_STATUSES",
    "PLAN_STEP_BLOCKED_GATE_REASONS",
    "PLAN_STEP_DEDUPE_KEY_TEMPLATE",
    "PLAN_STEP_OUTCOMES",
    "PLAN_STEP_OUTCOME_ACTION_STATUS",
    "PLAN_STEP_OUTCOME_VALUES",
    "RETRY_MODES",
    "RETRY_MODE_VALUES",
    "RetryMode",
    "STEP_KINDS",
    "STEP_KIND_VALUES",
    "StepKind",
    "GoalRef",
    "MemoryRef",
    "PlanAdvance",
    "PlanAdvanceDecision",
    "PlanContext",
    "PlanRevision",
    "PlanRevisionReason",
    "PlanStepBinding",
    "PlanStepOutcome",
    "PlanStepOutcomeStatus",
    "PlanValidationReport",
    "RetryPolicy",
]


class GoalRef(BaseModel):
    """父目标链 / 同层同域目标的只读最小投影（不持有完整 `GoalRecord`，避免上下文耦合）。"""

    id: str
    type: GoalType
    status: GoalStatus
    layer: GoalLayer | None = None
    domain: GoalDomain | None = None
    priority: int = Field(default=3, ge=GOAL_PRIORITY_MIN, le=GOAL_PRIORITY_MAX)


class MemoryRef(BaseModel):
    """进 `PlanContext` 的长期记忆只读投影（条数由 `plan_context_memory_limit` 约束）。"""

    id: str
    type: str = ""
    content: str = ""
    importance: float = 0.0


class RetryPolicy(BaseModel):
    """Plan 层重试策略（architecture.md §4.3.4 / §5.5）。

    只承载「尝试上限由谁裁决」：`none` / `once` 的界在本对象，`until_budget` 的界在
    `plan_step_max_attempts`。退避数学**只有一份**，在 Action 层，本对象不复制。
    """

    mode: RetryMode = "once"
    max_attempts: int = Field(default=1, ge=0)

    @property
    def is_bounded(self) -> bool:
        """`until_budget` 的界在 settings，其余两种模式的界在本对象。"""

        return self.mode != "until_budget"


class PlanStepBinding(BaseModel):
    """拆解产物（PLAN-004）：步骤序号 + 工具绑定 + 绑定理由（进审计）。"""

    step_index: int = Field(ge=1)
    binding: ToolBinding
    binding_reason: str | None = None


class PlanStepOutcome(BaseModel):
    """步骤执行与观测结果契约（双落点：`action_records.steps` + `goal_plans.sub_goals`）。

    `observations` 只做结构承载；白名单裁剪（`SubGoalSpec.observation_keys`）由 PLAN-005
    的归一器完成，本模块不做裁剪逻辑。
    """

    step_index: int = Field(ge=1)
    status: PlanStepOutcomeStatus
    at: datetime
    action_id: str | None = None
    tool_id: str = ""
    failure_kind: ToolFailureKind | None = None
    attempt: int = Field(default=0, ge=0)
    effects: list[dict[str, Any]] = Field(default_factory=list)
    observations: dict[str, Any] = Field(default_factory=dict)
    criteria_result: bool | None = None
    duration_ms: int | None = None


class PlanAdvance(BaseModel):
    """推进裁决（落 `decision_records`，复用既有 `kind='goal_lifecycle'`）。"""

    goal_id: str
    plan_id: str
    plan_version: int = Field(ge=1)
    decision: PlanAdvanceDecision
    reason: str = Field(max_length=60)
    at: datetime
    step_index: int | None = Field(default=None, ge=1)
    facts_digest: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """终态裁决（`completed` / `failed` / `skipped`）不再推进同一计划版本。"""

        return self.decision in PLAN_ADVANCE_TERMINAL_DECISIONS


class PlanRevision(BaseModel):
    """修订记录（落 `goal_plans` 新版本行；`reason` 与 `trigger_source` 共用四值理由码）。"""

    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    reason: PlanRevisionReason
    trigger_source: PlanRevisionReason
    at: datetime
    evidence_refs: list[str] = Field(default_factory=list)
    kept_steps: list[int] = Field(default_factory=list)


class PlanValidationReport(BaseModel):
    """三闸校验报告（形状 / 工具面 / 预算）：只读返回，不落库。"""

    shape_errors: list[str] = Field(default_factory=list)
    surface_errors: list[str] = Field(default_factory=list)
    budget_errors: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        """三闸错误集全空即通过。"""

        return not (self.shape_errors or self.surface_errors or self.budget_errors)


class PlanContext(BaseModel):
    """规划输入契约（六源投影 + 预算 + 降级登记；内存值对象，不落库）。

    `goal` 与 `tool_surface` 为硬依赖：前者是唯一规划主体，后者是「可绑工具面」的既有
    类型契约（Task Detail §4.2.1）。其余源由装配器按可用性填充，缺失的源逐条登记进
    `degraded`，使「计划为什么规划成这样」事后可解释。
    """

    goal: GoalRecord
    tool_surface: ToolSurface
    budget: dict[str, Any]
    ancestors: list[GoalRef] = Field(default_factory=list)
    siblings: list[GoalRef] = Field(default_factory=list)
    world: dict[str, Any] = Field(default_factory=dict)
    world_brief: WorldBrief | None = None
    world_context: WorldContext | None = None
    situations: list[UserSituation] = Field(default_factory=list)
    scene: SceneProfile | None = None
    relationship: dict[str, Any] = Field(default_factory=dict)
    memories: list[MemoryRef] = Field(default_factory=list)
    insights: list[InsightSummary] = Field(default_factory=list)
    run: dict[str, Any] = Field(default_factory=dict)
    degraded: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
