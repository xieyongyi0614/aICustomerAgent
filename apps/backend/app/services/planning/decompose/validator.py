"""PLAN-004 三闸：形状 / 绑定 / 预算（原 `decompose.py` 的 `PlanValidator` 段）。

三闸全部为纯函数——零 IO、零 LLM、零 `get_settings()` 直调（参数注入），返回**可读理由列表**，
**空列表 = 通过**。`_task_granularity` 是「一步是否构成 Task」的举证工具，不是拒绝闸。
"""

from __future__ import annotations

from app.models.tool import TOOL_EFFECT_KIND_VALUES, TOOL_EFFECT_KINDS, ToolSurface
from app.services.tool.registry import TOOL_ID_PATTERN

from .constants import (
    BINDING_REASONS,
    BUDGET_GOAL_WINDOW_HOURS,
    BUDGET_MAX_DEPTH,
    BUDGET_MAX_STEPS,
    BUDGET_STEP_MAX_ATTEMPTS,
    BUDGET_TTL_HOURS,
    REASON_BINDING_MISSING,
    REASON_COUNT_EXCEEDED,
    REASON_DEPTH_EXCEEDED,
    REASON_INVALID_BINDING,
    REASON_INVALID_EFFECTS,
    REASON_INVALID_SHAPE,
    REASON_PLAN_VERSIONS_INVALID,
    REASON_STEP_ATTEMPTS_EXCEEDED,
    REASON_TOOL_OFF_SURFACE,
    REASON_TOOL_UNRESOLVABLE,
    REASON_TTL_EXCEEDED,
    STEP_KIND_COMPOSITE,
    STEP_KIND_TOOL,
    PlanStepSpec,
    _FIRST_PLAN_VERSION,
    _STEP_DEPTH_ROOT,
    _budget_int,
    _reason,
)


class PlanValidator:
    """三闸（纯函数、零 IO、零 LLM）：形状 / 工具面 / 预算，返回值空列表即通过。

    三闸**互不重叠**（Task Detail §6.2 D3）：形状闸只看结构，绑定闸只看工具面与绑定一致性，
    预算闸只看四项预算。`validate_binding` 的语义前提是绑定子闸开启
    （`plan_tool_required` off 时不应调用，与 PLAN-003 闸门 5 / 6 的门控一致）。
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
