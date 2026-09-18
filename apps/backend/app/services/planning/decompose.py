"""V2.5.0 PLAN-004 Goal → Task 拆解与工具绑定（Task Detail §4 / §6 / §8；architecture.md §3.5、§7.7、§8.6）。

本模块回答两件事：**「一步该用什么工具」**（`TaskDecomposer` 工具绑定）与
**「这算不算一步」**（`PlanValidator` 三闸）。它不执行这一步，也不决定这一步该不该做
（Task Detail §3.3 职责边界）。**零 LLM、零写库、零迁移**：`decompose` 只产出内存态
`DecompositionResult`，落库由 PLAN-003 经 `goal_repository` 计划面函数完成（单一写面）。

四阶段（Task Detail §4.1.3）

| 阶段 | 函数 | 产出 |
|---|---|---|
| ① 结构解析 | `_parse_structure` | `SubGoalSpec[]`（复用 `models/goal.py::validate_sub_goals`） |
| ② 工具绑定 | `_bind_tools` | 绑定列表 + 派生字段写回步骤（`tool_id` / `kind` / `expected_effects` / …）+ 弱校验 |
| ③ 判据补全 | `_complete_criteria` | `observation_keys` 白名单收敛 + `tool` 源合法性 |
| ④ 预算校验 | `_check_budget` | 步数 / 深度 / 每步尝试上限 / 计划 TTL 四项理由 |

**校验分层**（§5.2 / §6.5）：规划期只做**弱校验**（工具必填参数齐备，`invalid_step_params`，
失败即拒、不进入执行）；类型 / 格式 / 范围与语义（如地点存在性）留给执行期
`ParamValidator.validate`（唯一权威）。

三闸（`PlanValidator`，architecture.md §8.6）：`validate_shape` / `validate_binding` /
`validate_budget` 全部为纯函数——零 IO、零 LLM、零 `get_settings()` 直调（参数注入），
返回**可读理由列表**，**空列表 = 通过**（对齐既有 `ValidationReport` 形态与语义）。
理由码对齐 PLAN-003 §4.2.4 七道闸：能由七道闸覆盖的项一律复用其理由码
（`invalid_sub_goal_shape` / `subgoal_count_exceeded` / `plan_tool_unresolvable` /
`plan_tool_off_surface`），其余为本任务新增且逐条声明（`REASON_*` 常量）。

契约纪律

- **不新增工具选择逻辑**（architecture.md §7.7 关键裁决）：一能力多工具时的 tiebreak 只调
  既有 `ToolSelector.select_with_reason`（`priority` + `tool_id` 字典序，收件人感知），
  与执行期同函数同规则，故规划期绑定与执行期选择不会分歧。
- **不新增映射表**：能力 → 动作 → 工具的反查复用 `ACTION_TOOL_MAP`（角色资产，9 → 10）；
  `ACTION_CAPABILITY_MAP` 兜底路径由 `ToolSelector` 内部消费，本模块不复制。
- **确定性**：同输入（`proposal` + `ctx` + `registry` + `settings`）同输出，含
  `tool_id` / `binding_reason` / `observation_keys`（§10.1 可复现锚点）。
- **本任务零写库**：`decompose.py` 不导入任何仓储（`world_repository` 红线 G-WORLD、
  `goal_repository` 单一写面）、不导入 `ToolExecutor` / `Capability.execute`（G-EXEC）。

与 Task Detail 的四处实现核对（均为源码签名核对结果，已在测试留痕）

1. **§4.2.1 / §5.2 / §8 Step 2.5 的 `ToolDefinition.effects` 在 V2.4.0 源码中不存在**：
   `ToolDefinition` 只有静态声明的 `side_effects`（`TOOL_SIDE_EFFECT_KINDS`：`read` /
   `write_world` / `write_memory` / `send_external` / `irreversible`），`effects` 是运行期
   `ToolResult.effects`（由 payload 推导，见 `services/tool/normalizer.py::_effects`）。
   而 §5.6 要求 `models/tool.py` **零改动**，故 `expected_effects` 由 `side_effects` 投影
   （`_project_effects`：剥去 `write_` / `send_` 前缀后取 ∈ `TOOL_EFFECT_KINDS` 者），
   结果**按构造** ⊆ `TOOL_EFFECT_KINDS`（5 值），零新增映射表、零模型改动。
2. **Q4 冻结是双层落地**：`SubGoalSpec.validate_criteria`（PLAN-002）已在模型层拒绝
   `threshold_reached` + `source="tool"`，故经 ① 的路径由**模型层**先拒（`decompose` 按
   §6.6 上抛 `ValueError`，不吞）；③ 的合法性检查是对**未经 ① 构造的步骤**（如直接从
   `goal_plans.sub_goals` 还原、或上游构造的对象）的纵深防御，记入 `criteria_errors`。
3. **`plan_versions` 的取值**：`validate_budget` 的该参数是 architecture §8.6 冻结签名的一部分，
   而 §6.1 的 `decompose` 无版本链输入且本模块零仓储依赖（§4.1.1），故首次生成以
   `_FIRST_PLAN_VERSION`（1）传入；修订后的复核由调用方注入真实版本数。该参数在本闸只做
   **版本序号合法性**判定——修订预算上限属 PLAN-003 / PLAN-005，本闸不重算（不重叠纪律 D3）。
4. **闸序**：§4.1.2 / §4.3.1 把形状闸画在阶段①之后，但 `validate_shape` 含「`kind` 与父子
   结构相合」一条（§8 Step 4.1），而 `kind` 是阶段②的派生产物（§4.2.1）——先判会误拒所有
   含父步的合法提案。故本实现的形状闸紧接阶段②、仍在③④之前（形状理由非空即不进入 ③④）。

契约演进留痕（PLAN-004）

`tests/v25/test_plan001_static_scan.py::ALLOWED_CHARACTER_IMPORT_MODULES` 由 PLAN-003 的
1 项扩为 2 项：新增 `app.character.asuna.action`（`ACTION_TOOL_MAP` / `ACTION_CAPABILITY_MAP`
的**唯一声明处**，Task Detail §4.1.1 明确要求复用）。两份资产都不属 PLAN-001
`character_priority_asset_import` 禁令所指的「优先级资产」。仍按模块逐条枚举，不得扩成前缀。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.character.asuna.action import ACTION_TOOL_MAP
from app.models.action import ACTION_TYPES, ActionIntent
from app.models.goal import (
    COMPOSITE_CRITERION_TYPES,
    CRITERION_TOOL_FACT_SOURCE,
    GoalRecord,
    SubGoalSpec,
    validate_sub_goals,
)
from app.models.plan import PLAN_STEP_ACTION_CONFIDENCE, PlanStepBinding
from app.models.tool import (
    TOOL_EFFECT_KINDS,
    TOOL_EFFECT_KIND_VALUES,
    ToolBinding,
    ToolDefinition,
    ToolSurface,
)
from app.services import goal_planning
from app.services.tool.registry import TOOL_ID_PATTERN, ToolRegistry, get_tool_registry
from app.services.tool.surface import ToolSelector

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

__all__ = [
    "BINDING_REASONS",
    "BINDING_REASON_CAPABILITY_MAP",
    "BINDING_REASON_FALLBACK",
    "BINDING_REASON_TOOL_SELECTOR",
    "BUDGET_GOAL_WINDOW_HOURS",
    "BUDGET_KEYS",
    "BUDGET_MAX_DEPTH",
    "BUDGET_MAX_STEPS",
    "BUDGET_STEP_MAX_ATTEMPTS",
    "BUDGET_TTL_HOURS",
    "EXTENDED_REASONS",
    "GATE_REASONS",
    "PLAN_LEVELS",
    "DecompositionResult",
    "PlanStepSpec",
    "PlanValidator",
    "STEP_KIND_COMPOSITE",
    "STEP_KIND_OBSERVE",
    "STEP_KIND_TOOL",
    "TASK_GRANULARITY_CHECKS",
    "TaskDecomposer",
]


@dataclass
class DecompositionResult:
    """拆解产物（Task Detail §6.1）：内存态，只读返回，**不落库**。

    `passed` = 形状闸通过且绑定 / 判据 / 预算三份理由列表全空。结构解析失败**不在此承载**：
    按 §6.6 上抛 `ValueError`，由调用方（PLAN-003）转 `rejected` + `invalid_sub_goal_shape`；
    `shape_errors` 承载的是 `validate_shape` 对已解析步骤的**结构一致性**判定
    （`kind` 与 `parent_index` 相合、依赖引用存在），即解析闸之外的纵深防御。
    """

    steps: list[PlanStepSpec] = field(default_factory=list)
    bindings: list[PlanStepBinding] = field(default_factory=list)
    passed: bool = False
    shape_errors: list[str] = field(default_factory=list)
    binding_errors: list[str] = field(default_factory=list)
    criteria_errors: list[str] = field(default_factory=list)
    budget_errors: list[str] = field(default_factory=list)


class PlanValidator:
    """三闸（纯函数、零 IO、零 LLM）：形状 / 工具面 / 预算，返回值空列表即通过。

    三闸**互不重叠**（Task Detail §6.2 D3）：形状闸只看结构，绑定闸只看工具面与绑定一致性，
    预算闸只看四项预算。`validate_binding` 的语义前提是绑定子闸开启
    （`plan_step_binding_enabled` off 时不应调用，与 PLAN-003 闸门 5 / 6 的门控一致）。
    """

    @staticmethod
    def validate_shape(steps: list[PlanStepSpec], *, max_depth: int) -> list[str]:
        """形状闸：序号连续 / 无前向依赖 / 依赖与父引用存在 / 深度封顶 / `kind` 与父子结构相合。"""
        errors: list[str] = []
        child_counts: dict[int, int] = {}
        for spec in steps:
            if spec.parent_index is not None:
                child_counts[spec.parent_index] = child_counts.get(spec.parent_index, 0) + 1
        known: set[int] = set()
        depth_by_index: dict[int, int] = {}
        for position, spec in enumerate(steps):
            errors.extend(
                _shape_reference_errors(spec, position, known, depth_by_index, max_depth)
            )
            errors.extend(_shape_kind_errors(spec, child_counts))
            known.add(spec.index)
            depth_by_index[spec.index] = _step_depth(spec.parent_index, depth_by_index)
        return errors

    @staticmethod
    def validate_binding(
        steps: list[PlanStepSpec], surface: ToolSurface | None
    ) -> list[str]:
        """绑定闸：`kind="tool"` 必须带合法且**在面上**的 `tool_id`；效果集取值合法。"""
        on_surface = set(surface.tool_ids) if surface is not None else set()
        errors: list[str] = []
        for spec in steps:
            errors.extend(_binding_errors(spec, on_surface))
        return errors

    @staticmethod
    def validate_budget(
        steps: list[PlanStepSpec], plan_versions: int, budget: dict[str, int]
    ) -> list[str]:
        """预算闸：步数 / 深度 / 每步尝试上限 / 计划 TTL 四项（Task Detail §4.2.6）。"""
        errors: list[str] = []
        max_steps = _budget_int(budget, BUDGET_MAX_STEPS)
        if len(steps) > max_steps:
            errors.append(
                _reason(REASON_COUNT_EXCEEDED, f"步骤数 {len(steps)} 超出上限 {max_steps}")
            )
        max_depth = _budget_int(budget, BUDGET_MAX_DEPTH)
        depth = _max_depth(steps)
        if depth > max_depth:
            errors.append(
                _reason(REASON_DEPTH_EXCEEDED, f"嵌套深度 {depth} 超出上限 {max_depth}")
            )
        errors.extend(_attempt_budget_errors(steps, budget))
        errors.extend(_ttl_budget_errors(budget))
        if plan_versions < _FIRST_PLAN_VERSION:
            errors.append(
                _reason(
                    REASON_PLAN_VERSIONS_INVALID,
                    f"计划版本数必须至少为 {_FIRST_PLAN_VERSION}（当前 {plan_versions}）",
                )
            )
        return errors


class TaskDecomposer:
    """四阶段拆解器（Task Detail §4.1.2）：结构解析 → 工具绑定 → 判据补全 → 预算校验。

    `registry` / `selector` 为**可注入**的只读依赖（缺省取工具系统单例、既有
    `ToolSelector`），注入点只影响测试与被 PLAN-005 / PLAN-011 复用的场景，不改变语义。
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        selector: ToolSelector | None = None,
    ) -> None:
        self._registry = registry
        self._selector = selector

    def decompose(  # pylint: disable=unused-argument
        self,
        proposal: goal_planning.PlanningProposal,
        goal: GoalRecord,
        ctx,
        *,
        settings,
    ) -> DecompositionResult:
        """LLM 提案 → `DecompositionResult`（四阶段一次转换，无跨 tick 状态）。

        `goal` 是 §6.1 冻结签名的一部分（PLAN-011 契约对照）；当前绑定以 `action_type`
        为键（`ACTION_TOOL_MAP`），不消费目标域，故显式声明未使用——不为凑用途而发明语义。

        闸序说明：**形状闸在阶段②之后**判。原因可判定：`validate_shape` 的一条检查是
        「`kind` 与父子结构相合」，而 `kind` 是阶段②的派生字段（§4.2.1）——先判会把每一份
        含父步的合法提案误判为形状非法。结构性的非法（序号 / 前向依赖 / 超深嵌套 / 空列表）
        仍由阶段①的 `validate_sub_goals` 先行抛出（§4.3.1「形状失败不再进入后续阶段」对
        该闸依然成立：形状理由非空即不进入 ③④）。
        """
        max_depth = min(
            int(settings.autonomy_subgoal_max_depth), int(settings.plan_max_depth)
        )
        steps = _parse_structure(proposal, max_depth=max_depth)
        bindings, binding_errors = _bind_tools(
            steps,
            ctx,
            registry=self._registry if self._registry is not None else get_tool_registry(),
            enabled=_binding_enabled(settings),
            selector=self._selector,
        )
        shape_errors = PlanValidator.validate_shape(steps, max_depth=max_depth)
        if shape_errors:
            return DecompositionResult(
                steps=steps,
                bindings=bindings,
                shape_errors=shape_errors,
                binding_errors=binding_errors,
            )
        steps, criteria_errors = _complete_criteria(steps, bindings)
        budget_errors = _check_budget(
            steps, _FIRST_PLAN_VERSION, _plan_budget_limits(ctx, settings)
        )
        return DecompositionResult(
            steps=steps,
            bindings=bindings,
            passed=not (binding_errors or criteria_errors or budget_errors),
            binding_errors=binding_errors,
            criteria_errors=criteria_errors,
            budget_errors=budget_errors,
        )


def _plan_budget_limits(ctx, settings) -> dict[str, int]:
    """预算四项 + 目标激活窗的 settings / `PlanContext.budget` 投影（参数注入，零 IO）。

    步数与深度取 `plan_*` 与 `autonomy_subgoal_*` 的**较小值**（与 PLAN-003 闸门 2 / 3 同源）；
    TTL 与激活窗只在校验时参与判定，不落库（Task Detail §7 TL 存储说明）。
    模块私有（§6.7 冻结公开面只有四个）；外部调用方按 `BUDGET_KEYS` 自组字典即可调三闸。
    """
    return {
        BUDGET_MAX_STEPS: min(
            int(ctx.budget.get(BUDGET_MAX_STEPS, settings.plan_max_steps)),
            int(settings.autonomy_subgoal_max_count),
        ),
        BUDGET_MAX_DEPTH: min(
            int(ctx.budget.get(BUDGET_MAX_DEPTH, settings.plan_max_depth)),
            int(settings.autonomy_subgoal_max_depth),
        ),
        BUDGET_STEP_MAX_ATTEMPTS: int(
            ctx.budget.get(BUDGET_STEP_MAX_ATTEMPTS, settings.plan_step_max_attempts)
        ),
        BUDGET_TTL_HOURS: int(settings.plan_ttl_hours),
        BUDGET_GOAL_WINDOW_HOURS: int(settings.autonomy_goal_max_active_hours),
    }


def _parse_structure(
    proposal: goal_planning.PlanningProposal, *, max_depth: int
) -> list[PlanStepSpec]:
    """① 结构解析：`PlanningProposal.sub_goals` → `SubGoalSpec[]`。

    **复用** `models/goal.py::validate_sub_goals`（判据白名单 / 序号连续 / 无前向依赖 /
    深度封顶），本模块不重复实现。空 `sub_goals` 视为形状非法（无 Task 即无计划）；
    `ValueError` 按 §6.6 **上抛**给调用方，不在此吞。
    """
    raw = list(getattr(proposal, "sub_goals", None) or [])
    if not raw:
        raise ValueError("规划提案没有 Sub-Goal 步骤：无 Task 即无计划")
    return validate_sub_goals(raw, max_depth=max_depth)


def _binding_enabled(settings) -> bool:
    """绑定生效的合取判据（§8 Step 6）：绑定子闸 off 或工具面非要 off，都退化为 V2.4.0。"""
    return bool(settings.plan_step_binding_enabled) and bool(
        settings.plan_tool_required
    )


def _bind_tools(
    specs: list[PlanStepSpec],
    ctx,
    *,
    registry: ToolRegistry | None,
    enabled: bool,
    selector: ToolSelector | None = None,
) -> tuple[list[PlanStepBinding], list[str]]:
    """② 工具绑定（B2 关闭点）：返回 (绑定列表, 绑定错误列表)，并把派生字段**就地写回** `specs`。

    三段判定：查找候选（`ToolSelector`，含既有兜底）→ 绑定成功 → **弱校验**（工具必填参数齐备，
    §5.2 / §6.5，失败记 `invalid_step_params` 并进 `binding_errors`，该步在规划期即被拒）。

    `enabled` off → 阶段整体跳过（不绑定、不派生、不弱校验、零错误）：V2.4.0 原状，
    `tool_id` 只在执行期由 `ToolSelector` 产生——弱校验依赖工具声明，故与绑定同门控，
    避免在 Flag off 时新增 V2.4.0 不存在的拒绝路径（G-COMPAT）。`registry` 为 `None`
    （工具系统总闸 off）且绑定生效时，**全部步骤**记 `capability_binding_missing`（§6.6）。

    父步（作为 `parent_index` 承载者）不绑定：`composite` 不是执行单元（§4.3.2 表），
    其 `kind` 是结构属性，故 `kind` 判定优先于绑定结果（否则违反形状闸
    「非 composite 不可有子步」）。
    """
    if not enabled:
        return [], []
    if registry is None:
        return [], [
            _reason(
                REASON_BINDING_MISSING,
                f"步骤 {spec.index} 绑定失败：工具注册表不可得（工具系统总闸 off）",
            )
            for spec in specs
        ]
    tool_selector = (
        selector
        if selector is not None
        else ToolSelector(registry, tool_map=ACTION_TOOL_MAP)
    )
    parent_indexes = {spec.parent_index for spec in specs if spec.parent_index is not None}
    bindings: list[PlanStepBinding] = []
    errors: list[str] = []
    for position, spec in enumerate(specs):
        if spec.index in parent_indexes:
            specs[position] = _apply_derivations(spec, None, None, has_children=True)
            continue
        binding, reason, failure = _bind_step(spec, ctx.tool_surface, tool_selector)
        specs[position] = _apply_derivations(
            spec,
            binding,
            reason,
            has_children=False,
            sole_predecessor=_sole_predecessor(spec.index, specs),
        )
        if binding is None:
            errors.append(failure)
            continue
        missing = _missing_required_params(spec, binding)
        if missing:
            errors.append(_weak_validation_reason(spec, binding, missing))
        bindings.append(
            PlanStepBinding(step_index=spec.index, binding=binding, binding_reason=reason)
        )
    return bindings, errors


def _missing_required_params(spec: PlanStepSpec, binding: ToolBinding) -> list[str]:
    """规划期**弱校验**（Task Detail §5.2 / §6.5）：只问「必填齐备」，不问类型 / 格式 / 语义。

    权威来源是工具自己的 `input_schema`（与注册期「校验 5｜schema 自洽」同源）；类型 / 格式 /
    范围与语义校验留给执行期 `ParamValidator.validate`（唯一权威）——两层的边界是
    「规划期只排除**必然失败**的步骤」，不是第二次决策。
    """
    return [
        parameter.name
        for parameter in binding.definition.input_schema.parameters
        if parameter.required and parameter.name not in spec.params
    ]


def _weak_validation_reason(
    spec: PlanStepSpec, binding: ToolBinding, missing: list[str]
) -> str:
    return _reason(
        REASON_INVALID_PARAMS,
        f"步骤 {spec.index} 缺少工具 {binding.tool_id} 的必填参数：{', '.join(missing)}"
        "（规划期弱校验；类型 / 格式 / 语义由执行期 ParamValidator 裁决）",
    )


def _bind_step(
    spec: PlanStepSpec, surface: ToolSurface | None, tool_selector: ToolSelector
) -> tuple[ToolBinding | None, str | None, str]:
    """单步绑定：能力名 → `ToolSelector.select_with_reason` → `ToolBinding` + 绑定理由。

    **tiebreak 调用点唯一**：候选取一（含 `ACTION_TOOL_MAP` 未覆盖时按 `(capability, action)`
    的既有兜底）全部由 `ToolSelector` 完成，本模块零自造排序规则。LLM 建议的 `tool_id` 提示
    **不参与**选型：规划期与执行期必须同函数同规则（§7.7），honor 提示会引入第二套规则。
    """
    if spec.capability not in ACTION_TYPES:
        return (
            None,
            None,
            _reason(
                REASON_BINDING_MISSING,
                f"步骤 {spec.index} 绑定失败：能力 {spec.capability} 不在 ACTION_TYPES",
            ),
        )
    intent = ActionIntent(
        action_type=spec.capability,
        confidence=PLAN_STEP_ACTION_CONFIDENCE,
        params=dict(spec.params),
    )
    selection = tool_selector.select_with_reason(intent, surface)
    if selection.binding is None:
        return (
            None,
            None,
            _reason(
                REASON_BINDING_MISSING,
                f"步骤 {spec.index} 绑定失败：能力 {spec.capability} 在当前工具面上无候选工具",
            ),
        )
    return selection.binding, _binding_reason(spec.capability, tool_selector.tool_map), ""


def _binding_reason(capability: str, tool_map: Mapping[str, Sequence[str]]) -> str:
    """绑定理由三值（§4.2.2）：按**实际使用的**候选映射（`ToolSelector.tool_map`，生产即
    `ACTION_TOOL_MAP`）的声明重数判定裁决路径，故理由与实际情况一致。"""
    mapped = tool_map.get(capability)
    if mapped is None:
        return BINDING_REASON_FALLBACK
    if len(mapped) > 1:
        return BINDING_REASON_TOOL_SELECTOR
    return BINDING_REASON_CAPABILITY_MAP


def _apply_derivations(
    spec: PlanStepSpec,
    binding: ToolBinding | None,
    reason: str | None,
    *,
    has_children: bool,
    sole_predecessor: bool = False,
) -> PlanStepSpec:
    """把阶段②的派生字段写回步骤（§4.2.1 归因表）：返回新对象，不改写入参。"""
    return spec.model_copy(
        update={
            "tool_id": None if binding is None else binding.tool_id,
            "kind": _derive_kind(binding, has_children=has_children),
            "binding_reason": reason if binding is not None else None,
            "expected_effects": _project_effects(
                None if binding is None else binding.definition
            ),
            "retry_policy": _derive_retry_policy(spec, binding),
            "on_failure": _derive_on_failure(spec, sole_predecessor=sole_predecessor),
        }
    )


def _derive_kind(binding: ToolBinding | None, *, has_children: bool) -> str:
    """`kind` 推导（§4.3.2）：父步 → `composite`；有绑定 → `tool`；其余 → `observe`。"""
    if has_children:
        return STEP_KIND_COMPOSITE
    if binding is not None:
        return STEP_KIND_TOOL
    return STEP_KIND_OBSERVE


def _project_effects(definition: ToolDefinition | None) -> tuple[str, ...]:
    """`expected_effects` 投影（§4.2.1）：取 `ToolDefinition.side_effects` 中的效果种类。

    V2.4.0 的 `ToolDefinition` 无 `effects` 字段（该名字属运行期 `ToolResult.effects`），
    静态效果声明只有 `side_effects`；`write_world` / `write_memory` / `send_external`
    剥去前缀后即 `world` / `memory` / `external`，`read` 与 `irreversible` 不产生效果种类。
    """
    if definition is None:
        return ()
    kinds: list[str] = []
    for side_effect in definition.side_effects:
        candidate = side_effect
        for prefix in _SIDE_EFFECT_PREFIXES:
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :]
        if candidate in TOOL_EFFECT_KIND_VALUES and candidate not in kinds:
            kinds.append(candidate)
    return tuple(kinds)


def _derive_retry_policy(spec: PlanStepSpec, binding: ToolBinding | None) -> str:
    """`retry_policy` 推导（§4.2.1）：上游显式声明优先，否则按幂等性推导，默认 `once`。

    非幂等工具（`idempotency="none"`）与无绑定步骤一律 `none`——重试非幂等调用等于造重复副作用。
    """
    if spec.retry_policy != _RETRY_POLICY_DEFAULT:
        return spec.retry_policy
    if binding is None or binding.definition.idempotency == _IDEMPOTENCY_NONE:
        return _UNBOUND_RETRY_POLICY
    return _RETRY_POLICY_DEFAULT


def _derive_on_failure(spec: PlanStepSpec, *, sole_predecessor: bool) -> str:
    """`on_failure` 推导（§4.3.3）：**默认不放大失败影响**。

    默认取 `skip`；上游显式声明（非默认值）一律采信；仅当本步是其后继**唯一前置**
    （后继全部不可达）时升为 `abort`。
    """
    if spec.on_failure != _ON_FAILURE_DEFAULT:
        return spec.on_failure
    if sole_predecessor:
        return _ON_FAILURE_BLOCKING
    return _ON_FAILURE_DEFAULT


def _sole_predecessor(index: int, specs: list[PlanStepSpec]) -> bool:
    """本步是否为全部后继的唯一前置（`depends_on` 长度恒为 1 且含本步）。"""
    successors = [spec for spec in specs if index in spec.depends_on]
    if not successors:
        return False
    return all(len(spec.depends_on) == 1 for spec in successors)


def _complete_criteria(
    specs: list[PlanStepSpec], bindings: list[PlanStepBinding]
) -> tuple[list[PlanStepSpec], list[str]]:
    """③ 判据补全（B7 关闭点）：`tool` 源合法性 + `observation_keys` 白名单收敛。

    `observation_keys` 是「允许进入判据的 `ToolResult.observations` 键白名单」
    （architecture.md §4.4）：显式声明即权威；未声明时由**已绑定**步骤的
    `field_equals` 判据 `path` 反推（收敛而非放任）。未声明键**不报错**、但不在白名单内，
    运行期一律判为不可判定（`evaluate_criteria` 返回 `None`，**绝不默认 True**；
    求值本体属 PLAN-005 `PlanObserver.evaluate`）。
    """
    bound_indexes = {binding.step_index for binding in bindings}
    steps: list[PlanStepSpec] = []
    errors: list[str] = []
    for spec in specs:
        errors.extend(_tool_criteria_errors(spec))
        steps.append(
            spec.model_copy(
                update={
                    "observation_keys": _observation_keys(
                        spec, tool_bound=spec.index in bound_indexes
                    )
                }
            )
        )
    return steps, errors


def _observation_keys(spec: PlanStepSpec, *, tool_bound: bool) -> tuple[str, ...]:
    """白名单收敛：显式声明优先；未声明且已绑定 → 由 `tool` 源 `field_equals` 的 `path` 反推。

    未绑定步骤（纯观测 / 父步 / 绑定子闸 off）不产生 `ToolResult.observations`，白名单留空。
    """
    if spec.observation_keys:
        return spec.observation_keys
    if not tool_bound:
        return ()
    return _referenced_tool_keys(spec.criteria)


def _referenced_tool_keys(criteria) -> tuple[str, ...]:
    """判据树中被 `tool` 源 `field_equals` 引用的键（声明顺序、去重，确定性）。"""
    keys: list[str] = []
    _collect_tool_keys(criteria, keys)
    return tuple(keys)


def _collect_tool_keys(node, keys: list[str]) -> None:
    if not isinstance(node, dict):
        return
    criterion_type = node.get(_CRITERION_TYPE_KEY)
    if criterion_type in COMPOSITE_CRITERION_TYPES:
        for child in node.get(_CRITERION_CHILDREN_KEY) or []:
            _collect_tool_keys(child, keys)
        return
    if criterion_type != _CRITERION_FIELD_EQUALS:
        return
    if node.get(_CRITERION_SOURCE_KEY) != CRITERION_TOOL_FACT_SOURCE:
        return
    path = node.get(_CRITERION_PATH_KEY)
    if isinstance(path, str) and path and path not in keys:
        keys.append(path)


def _tool_criteria_errors(spec: PlanStepSpec) -> list[str]:
    """`tool` 源合法性（§4.2.5）：`action_succeeded` / `field_equals` 允许，`threshold_reached` 拒。

    Q4 冻结（architecture.md §9.7）：工具观测只提供键值等值判定，故 `threshold_reached`
    在 `tool` 源下**拒绝**，保持判据值集最小；放开须先定义工具侧指标路径词表。
    """
    errors: list[str] = []
    _check_tool_criterion(spec.criteria, spec.index, errors)
    return errors


def _check_tool_criterion(node, index: int, errors: list[str]) -> None:
    if not isinstance(node, dict):
        return
    criterion_type = node.get(_CRITERION_TYPE_KEY)
    if criterion_type in COMPOSITE_CRITERION_TYPES:
        for child in node.get(_CRITERION_CHILDREN_KEY) or []:
            _check_tool_criterion(child, index, errors)
        return
    if criterion_type != _CRITERION_THRESHOLD_REACHED:
        return
    if node.get(_CRITERION_SOURCE_KEY) != CRITERION_TOOL_FACT_SOURCE:
        return
    errors.append(
        _reason(
            REASON_CRITERIA_UNSUPPORTED,
            f"步骤 {index}：threshold_reached 判据不支持事实源 'tool'（Q4 冻结，保持值集最小）",
        )
    )


def _check_budget(
    specs: list[PlanStepSpec], plan_versions: int, budget: dict[str, int]
) -> list[str]:
    """④ 预算校验（复用 `PlanValidator.validate_budget`，单一实现）。"""
    return PlanValidator.validate_budget(specs, plan_versions, budget)


def _task_granularity(
    spec: PlanStepSpec, specs: list[PlanStepSpec], surface: ToolSurface | None
) -> tuple[str, ...]:
    """L2 粒度三条判据的未通过清单（空 = 构成 Task；§4.2.4）。

    这是「一步是否构成 Task」的**可举证判定**，不是拒绝闸——拒绝由 `PlanValidator` 三闸裁决。
    代码与 `TASK_GRANULARITY_CHECKS` 逐条对应，供 PLAN-011 契约对照与粒度讨论使用。

    父步容器（`composite`）只判 G3：它是「多个 Task 的承载者」而非一个 Task，故 G1 / G2
    对它不适用（G3 不成立正是「拆成多 Task」这一动作的判据）。
    """
    if any(other.parent_index == spec.index for other in specs) or (
        spec.kind == STEP_KIND_COMPOSITE
    ):
        return ("G3",)
    on_surface = set(surface.tool_ids) if surface is not None else set()
    failed: list[str] = []
    if not spec.criteria:
        failed.append("G1")
    if not spec.tool_id or spec.tool_id not in on_surface:
        failed.append("G2")
    return tuple(failed)


def _shape_reference_errors(
    spec: PlanStepSpec,
    position: int,
    known: set[int],
    depth_by_index: dict[int, int],
    max_depth: int,
) -> list[str]:
    """形状闸的序号 / 依赖 / 父引用 / 深度四项（形状闸不管绑定，也不管预算）。"""
    errors: list[str] = []
    if spec.index != position + 1:
        errors.append(
            _reason(
                REASON_INVALID_SHAPE,
                f"步骤序号不连续：第 {position + 1} 个步骤的 index={spec.index}",
            )
        )
    for reference in spec.depends_on:
        if reference >= spec.index:
            errors.append(
                _reason(REASON_INVALID_SHAPE, f"步骤 {spec.index} 依赖前向引用 {reference}")
            )
        elif reference not in known:
            errors.append(
                _reason(REASON_INVALID_SHAPE, f"步骤 {spec.index} 依赖的步骤 {reference} 不存在")
            )
    depth = _STEP_DEPTH_ROOT
    if spec.parent_index is None:
        depth = _STEP_DEPTH_ROOT
    elif spec.parent_index >= spec.index:
        errors.append(
            _reason(
                REASON_INVALID_SHAPE,
                f"步骤 {spec.index} 的父步 {spec.parent_index} 为前向引用",
            )
        )
    elif spec.parent_index not in depth_by_index:
        errors.append(
            _reason(
                REASON_INVALID_SHAPE, f"步骤 {spec.index} 的父步 {spec.parent_index} 不存在"
            )
        )
    else:
        depth = _step_depth(spec.parent_index, depth_by_index)
    if depth > max_depth:
        errors.append(
            _reason(
                REASON_INVALID_SHAPE, f"步骤 {spec.index} 嵌套 {depth} 层，超出上限 {max_depth}"
            )
        )
    return errors


def _step_depth(parent_index: int | None, depth_by_index: dict[int, int]) -> int:
    if parent_index is None:
        return _STEP_DEPTH_ROOT
    return depth_by_index.get(parent_index, _STEP_DEPTH_ROOT) + 1


def _shape_kind_errors(spec: PlanStepSpec, child_counts: dict[int, int]) -> list[str]:
    """形状闸的 `kind` 与父子结构一致性（§8 Step 4.1）：composite ⇔ 有子步。"""
    has_children = child_counts.get(spec.index, 0) > 0
    if has_children and spec.kind != STEP_KIND_COMPOSITE:
        return [
            _reason(
                REASON_INVALID_SHAPE,
                f"步骤 {spec.index} 有子步，kind 必须为 composite（当前 {spec.kind}）",
            )
        ]
    if spec.kind == STEP_KIND_COMPOSITE and not has_children:
        return [
            _reason(REASON_INVALID_SHAPE, f"步骤 {spec.index} 声明为 composite 但没有子步")
        ]
    return []


def _binding_errors(spec: PlanStepSpec, on_surface: set[str]) -> list[str]:
    """绑定闸单步判定：工具可解析性与在面性、`binding_reason` 三值、效果集取值。"""
    errors: list[str] = []
    illegal = [effect for effect in spec.expected_effects if effect not in TOOL_EFFECT_KIND_VALUES]
    if illegal:
        errors.append(
            _reason(
                REASON_INVALID_EFFECTS,
                f"步骤 {spec.index} 的 expected_effects 越出 TOOL_EFFECT_KINDS：{illegal}；"
                f"合法值集: {', '.join(TOOL_EFFECT_KINDS)}",
            )
        )
    if spec.binding_reason is not None and spec.binding_reason not in BINDING_REASONS:
        errors.append(
            _reason(
                REASON_INVALID_BINDING,
                f"步骤 {spec.index} 的 binding_reason 不在三值集：{spec.binding_reason!r}",
            )
        )
    if spec.kind == STEP_KIND_TOOL:
        errors.extend(_tool_step_errors(spec, on_surface))
    elif spec.tool_id:
        errors.append(
            _reason(
                REASON_INVALID_BINDING,
                f"步骤 {spec.index} kind={spec.kind} 不应携带工具绑定：{spec.tool_id}",
            )
        )
    return errors


def _tool_step_errors(spec: PlanStepSpec, on_surface: set[str]) -> list[str]:
    if not spec.tool_id:
        return [_reason(REASON_BINDING_MISSING, f"步骤 {spec.index} kind=tool 但 tool_id 缺失")]
    if not TOOL_ID_PATTERN.fullmatch(spec.tool_id):
        return [
            _reason(REASON_TOOL_UNRESOLVABLE, f"步骤 {spec.index} 的 tool_id 非法：{spec.tool_id}")
        ]
    if spec.tool_id not in on_surface:
        return [
            _reason(
                REASON_TOOL_OFF_SURFACE,
                f"步骤 {spec.index} 的工具 {spec.tool_id} 不在当前工具面上",
            )
        ]
    return []


def _attempt_budget_errors(
    steps: list[PlanStepSpec], budget: dict[str, int]
) -> list[str]:
    """每步尝试上限：`until_budget` 的界在 settings，上限非法即无法界定尝试次数。"""
    attempts = _budget_int(budget, BUDGET_STEP_MAX_ATTEMPTS)
    if attempts >= 1:
        return []
    if not any(spec.retry_policy == "until_budget" for spec in steps):
        return []
    return [
        _reason(
            REASON_STEP_ATTEMPTS_EXCEEDED,
            f"存在 retry_policy=until_budget 的步骤，但每步尝试上限为 {attempts}",
        )
    ]


def _ttl_budget_errors(budget: dict[str, int]) -> list[str]:
    """计划 TTL：必须为正，且不得超出目标激活窗（`autonomy_goal_max_active_hours`）。"""
    ttl_hours = _budget_int(budget, BUDGET_TTL_HOURS)
    window_hours = _budget_int(budget, BUDGET_GOAL_WINDOW_HOURS)
    if ttl_hours < 1:
        return [_reason(REASON_TTL_EXCEEDED, f"计划 TTL 必须至少为 1 小时（当前 {ttl_hours}）")]
    if ttl_hours > window_hours:
        return [
            _reason(
                REASON_TTL_EXCEEDED,
                f"计划 TTL {ttl_hours}h 超出目标激活窗 {window_hours}h",
            )
        ]
    return []


def _max_depth(steps: list[PlanStepSpec]) -> int:
    depth_by_index: dict[int, int] = {}
    depth = 0
    for spec in steps:
        depth = _step_depth(spec.parent_index, depth_by_index)
        depth_by_index[spec.index] = depth
    return depth


def _budget_int(budget: dict[str, int], key: str) -> int:
    try:
        return int(budget.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _reason(code: str, detail: str) -> str:
    """可读理由：`<理由码>:<中文说明>`——理由码可与 PLAN-003 §4.2.4 逐条对照。"""
    return f"{code}:{detail}"
