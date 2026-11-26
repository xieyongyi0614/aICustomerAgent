"""PLAN-004 四阶段拆解器：结构解析 → 工具绑定 → 判据补全 → 预算校验（原 `decompose.py` 主体）。

本模块回答「一步该用什么工具」与「这算不算一步」两件事，不执行这一步，也不决定这一步该不该做。
**零 LLM、零写库、零迁移**：只产出内存态 `DecompositionResult`，落库由 PLAN-003 完成（单一写面）。

契约纪律：不新增工具选择逻辑（tiebreak 只调既有 `ToolSelector.select_with_reason`）；
不新增映射表（能力 → 动作 → 工具反查复用 `ACTION_TOOL_MAP`）；同输入同输出（可复现锚点）。
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
    validate_sub_goals,
)
from app.models.plan import PLAN_STEP_ACTION_CONFIDENCE, PlanStepBinding
from app.models.tool import (
    TOOL_EFFECT_KIND_VALUES,
    ToolBinding,
    ToolDefinition,
    ToolSurface,
)
from app.services.goal import planning as goal_planning
from app.services.tool.registry import ToolRegistry, get_tool_registry
from app.services.tool.surface import ToolSelector

from .constants import (
    BINDING_REASON_CAPABILITY_MAP,
    BINDING_REASON_FALLBACK,
    BINDING_REASON_TOOL_SELECTOR,
    BUDGET_GOAL_WINDOW_HOURS,
    BUDGET_MAX_DEPTH,
    BUDGET_MAX_STEPS,
    BUDGET_STEP_MAX_ATTEMPTS,
    BUDGET_TTL_HOURS,
    REASON_BINDING_MISSING,
    REASON_CRITERIA_UNSUPPORTED,
    REASON_INVALID_PARAMS,
    STEP_KIND_COMPOSITE,
    STEP_KIND_OBSERVE,
    STEP_KIND_TOOL,
    PlanStepSpec,
    _CRITERION_CHILDREN_KEY,
    _CRITERION_FIELD_EQUALS,
    _CRITERION_PATH_KEY,
    _CRITERION_SOURCE_KEY,
    _CRITERION_THRESHOLD_REACHED,
    _CRITERION_TYPE_KEY,
    _FIRST_PLAN_VERSION,
    _IDEMPOTENCY_NONE,
    _ON_FAILURE_BLOCKING,
    _ON_FAILURE_DEFAULT,
    _RETRY_POLICY_DEFAULT,
    _SIDE_EFFECT_PREFIXES,
    _UNBOUND_RETRY_POLICY,
    _reason,
)
from .validator import PlanValidator


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
    """绑定生效判据（§8 Step 6）：绑定子闸已随开关体系删除，只剩保留的策略位。"""
    return bool(settings.plan_tool_required)


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
