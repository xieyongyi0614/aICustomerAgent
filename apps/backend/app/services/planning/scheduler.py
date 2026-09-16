"""V2.5.0 PLAN-005 计划调度（Task Detail §4.4 / §4.5 / §6.1；architecture.md §3.6、§8.4）。

本模块回答「下一步该做哪个步」。**先搬后改**：`order` / `current_step` / `all_done` /
`has_executable` 四者逐条搬运自既有 `goal_observation` 的四个私有函数
（`_execution_order` / `_current_step` / `_all_done` / `_has_executable`），签名与服务逻辑
保持等价——搬运期由 `tests/v25/test_plan005_scheduler.py::TestCarryOverEquivalence` 做
**新旧实现逐条对照**（Task Detail §9.1 U1，Step 1 的出口条件）。既有私有函数保留一个版本
窗口（本任务不改其调用点），故新实现的行为变更不可能污染既有观测语义。

顺序即结构序（Task Detail §4.4）

| 规则 | 落点 |
|---|---|
| 依赖优先 | `depends_on` 必须全为 `done`（`ready_steps`） |
| 叶子优先 | 父步（`kind=composite` 或有子步）不作为执行单元，只在子步全 `done` 后由 `advance_goal` 结算 |
| 结构序 | 同层就绪步按 `index` 升序；**不按 Goal priority 重排**（PLAN-001 §4.3.4 红线） |
| 面感知 | 就绪但 `tool_id ∉ 当前工具面` → 不进「可执行」，记 `blocked_reason=off_surface` |

零 IO / 零 LLM / 零 `get_settings()` 直调：全部判定只读入参（`plan` 与鸭子类型的 `ctx`），
阈值与时刻一律由调用方注入 —— 同输入同输出（对齐 `ToolSurface.surface_hash` 工程标准）。

`ctx` 契约（鸭子类型，缺省即不判该项，绝不猜测）

| 键 | 取用方 | 缺省后果 |
|---|---|---|
| `ctx.tool_surface.tool_ids` | `blocked_reason` 的面感知 | 不判 `off_surface` |
| `ctx.now`（`datetime`） | `blocked_reason` 的冷却判定 | 不判 `cooldown` |
| `ctx.step_cooldown_minutes` / `ctx.settings.v25_plan_step_cooldown_minutes` | 同上 | 不判 `cooldown` |

与 Task Detail 的一处接口核对（已在测试留痕）

§6.1 / §8.4 把 `order` 冻结为 `order(plan) -> list[int]`，而 §8 Step 1.1 要求与
`_execution_order`「签名与服务逻辑保持等价」——后者返回**步骤对象**（叶子优先的执行序）。
本实现以「先搬后改、行为零变更」为准：`order` 返回 `list[PlanStepSpec]`（与搬运源逐条一致），
下标形状由 `order_indexes` 提供；两者同源，任一形状都可断言。`order` 的第二个形参 `goal`
是 PLAN-001 deferred 断言（`test_plan001_deferred.py`）的既有调用形态，本实现保留可选占位；
搬运源不消费目标域，故本模块也不消费（不为凑用途而发明语义）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from app.models.goal import (
    ON_FAILURE_MODE_VALUES,
    OnFailureMode,
    SubGoalSpec,
)

PlanStepSpec = SubGoalSpec
"""§4.2.1 的 `PlanStepSpec` 即**扩展后的 `SubGoalSpec`**（与 PLAN-004 同款别名，零新建模型）。"""

STEP_STATUS_PENDING = "pending"
STEP_STATUS_IN_PROGRESS = "in_progress"
STEP_STATUS_DONE = "done"
STEP_STATUS_FAILED = "failed"

READY_STATUSES: tuple[str, ...] = (STEP_STATUS_PENDING, STEP_STATUS_IN_PROGRESS)
"""就绪集状态（§4.3.1：`pending` 与 `in_progress` 都进就绪集，`done` / `failed` 不进）。"""

ACTIVE_STATUSES: tuple[str, ...] = READY_STATUSES
"""未终态步骤（矩阵处置的作用域）。"""

STEP_KIND_COMPOSITE = "composite"

ON_FAILURE_ABORT: OnFailureMode = "abort"
ON_FAILURE_SKIP: OnFailureMode = "skip"
ON_FAILURE_REPLAN: OnFailureMode = "replan"
ON_FAILURE_CONTINUE: OnFailureMode = "continue"

BLOCKED_OFF_SURFACE = "off_surface"
BLOCKED_COOLDOWN = "cooldown"
BLOCKED_PREDECESSOR_FAILED = "predecessor_failed"

BLOCKED_REASONS: tuple[str, ...] = (
    BLOCKED_OFF_SURFACE,
    BLOCKED_COOLDOWN,
    BLOCKED_PREDECESSOR_FAILED,
)
"""§4.5 的三类阻塞原因（`None` = 存在可执行步，非阻塞）。"""

COOLDOWN_MINUTES_KEY = "step_cooldown_minutes"
COOLDOWN_SETTING_NAME = "v25_plan_step_cooldown_minutes"

__all__ = [
    "ACTIVE_STATUSES",
    "BLOCKED_COOLDOWN",
    "BLOCKED_OFF_SURFACE",
    "BLOCKED_PREDECESSOR_FAILED",
    "BLOCKED_REASONS",
    "COOLDOWN_MINUTES_KEY",
    "FailurePropagation",
    "ON_FAILURE_ABORT",
    "ON_FAILURE_CONTINUE",
    "ON_FAILURE_REPLAN",
    "ON_FAILURE_SKIP",
    "PlanScheduler",
    "PlanStepSpec",
    "READY_STATUSES",
    "STEP_KIND_COMPOSITE",
    "STEP_STATUS_DONE",
    "STEP_STATUS_FAILED",
    "STEP_STATUS_IN_PROGRESS",
    "STEP_STATUS_PENDING",
]


@dataclass(frozen=True)
class FailurePropagation:
    """`on_failure` 四值 × 后继矩阵的处置结果（§4.3.2，纯数据）。

    `specs` 是**处置后的新列表**（原列表与其中的步骤对象不被改写）；`plan_failed` 表示计划
    整体判定失败（`abort` 全置 `failed`），是否结算目标终态由 `PlanObserver.settle` 裁决。
    """

    mode: str
    specs: list[PlanStepSpec] = field(default_factory=list)
    failed_indexes: tuple[int, ...] = ()
    plan_failed: bool = False
    paused: bool = False
    relaxed: bool = False


class PlanScheduler:
    """纯函数调度器（零 IO / 零 LLM / 零 `get_settings()`）：顺序、就绪、当前步、终态、阻塞。"""

    @staticmethod
    def order(  # pylint: disable=unused-argument
        plan, goal=None
    ) -> list[PlanStepSpec]:
        """叶子优先执行序（搬运自 `goal_observation._execution_order`，逐条等价）。

        每顶层步的子步先于父步；`goal` 是 PLAN-001 deferred 断言的既有调用形态，不参与判定。
        """
        specs = list(plan.sub_goals)
        order: list[PlanStepSpec] = []
        for top in (spec for spec in specs if spec.parent_index is None):
            order.extend(child for child in specs if child.parent_index == top.index)
            order.append(top)
        return order

    @staticmethod
    def order_indexes(plan) -> list[int]:
        """`order` 的下标投影（§6.1 冻结形状 `list[int]`）。"""
        return [spec.index for spec in PlanScheduler.order(plan)]

    @staticmethod
    def current_step(plan) -> PlanStepSpec | None:
        """下一个待执行步（搬运自 `_current_step`）：执行序中首个 `pending` / `in_progress`。"""
        for spec in PlanScheduler.order(plan):
            if spec.status in READY_STATUSES:
                return spec
        return None

    @staticmethod
    def all_done(plan) -> bool:
        """全部步骤 `done`（搬运自 `_all_done`；空步骤集按 `all([])` 语义为真）。"""
        return all(spec.status == STEP_STATUS_DONE for spec in plan.sub_goals)

    @staticmethod
    def has_executable(plan) -> bool:
        """是否还有可执行的**顶层**步（搬运自 `_has_executable`，语义与判据逐字一致）。"""
        return any(
            spec.status in READY_STATUSES and spec.parent_index is None
            for spec in plan.sub_goals
        )

    @staticmethod
    def ready_steps(plan) -> list[PlanStepSpec]:
        """就绪集（§4.2.1 / §4.3.1）：前驱全 `done`、自身未终态、且**是执行单元**（叶子优先）。

        「执行单元」= 非 `composite` 且无子步——父步只在子步全 `done` 后由 `advance_goal`
        结算，不产生 Action（§4.4 叶子优先）。同层按 `index` 升序（结构序），确定性可复现。
        """
        specs = list(plan.sub_goals)
        status_by_index = {spec.index: spec.status for spec in specs}
        ready = [
            spec
            for spec in specs
            if spec.status in READY_STATUSES
            and _is_execution_unit(spec, specs)
            and all(
                status_by_index.get(reference) == STEP_STATUS_DONE
                for reference in spec.depends_on
            )
        ]
        return sorted(ready, key=lambda spec: spec.index)

    @staticmethod
    def blocked_reason(plan, ctx) -> str | None:
        """为何此刻没有可执行步（§4.5 三值；`None` = 存在可执行步）。

        判定序固定（同 tick 多因并存时取首个可判因）：可执行 → `None`；无就绪步 →
        `predecessor_failed`（存在被前驱失败堵住且未被 `continue` 显式放宽的就绪步）；
        否则就绪步被面剔除 → `off_surface`；其余即冷却窗口内 → `cooldown`。
        """
        specs = list(plan.sub_goals)
        ready = PlanScheduler.ready_steps(plan)
        if not ready:
            if _has_failed_predecessor(specs):
                return BLOCKED_PREDECESSOR_FAILED
            return None
        if any(
            not _off_surface(spec, ctx) and not _in_cooldown(spec, ctx)
            for spec in ready
        ):
            return None
        if any(_off_surface(spec, ctx) for spec in ready):
            return BLOCKED_OFF_SURFACE
        return BLOCKED_COOLDOWN

    @staticmethod
    def propagate_failure(plan, step_index: int) -> FailurePropagation:
        """`on_failure` 四值 × 后继矩阵（§4.3.2）：把单步失败**确定性地**扩散到后继。

        四值语义（逐条与 §4.3.2 一致，`mode` 非法即抛实现缺陷异常）：

        | `on_failure` | 后继处置 | 计划终态 |
        |---|---|---|
        | `abort` | 全部未终态步置 `failed` | `plan_failed=True` |
        | `skip` | **直接**后继置 `failed`，旁支继续 | 视剩余步骤判定 |
        | `replan` | 暂停（不改状态），由 `PlanRevisionPolicy` 触发重规划 | 视重规划结果 |
        | `continue` | 全部继续（`depends_on` 语义被**显式放宽**） | 视其余步骤判定 |

        本函数只改`PlanStepSpec` 的**内存副本**（返回新列表），落库仍由调用方经
        `goal_repository.update_plan_progress` 完成（单一写面）。
        """
        specs = list(plan.sub_goals)
        failed_step = next(
            (spec for spec in specs if spec.index == step_index), None
        )
        if failed_step is None:
            raise ValueError(f"步骤 {step_index} 不在计划中（实现缺陷）")
        mode = failed_step.on_failure
        if mode not in ON_FAILURE_MODE_VALUES:
            raise ValueError(f"on_failure 取值非法：{mode!r}")
        if mode == ON_FAILURE_CONTINUE:
            return FailurePropagation(
                mode=mode, specs=specs, relaxed=True
            )
        if mode == ON_FAILURE_REPLAN:
            return FailurePropagation(mode=mode, specs=specs, paused=True)
        targets = _propagation_targets(specs, step_index, mode)
        updated = [
            _as_failed(spec, step_index, mode) if spec.index in targets else spec
            for spec in specs
        ]
        return FailurePropagation(
            mode=mode,
            specs=updated,
            failed_indexes=tuple(sorted(targets)),
            plan_failed=mode == ON_FAILURE_ABORT,
        )


def _is_execution_unit(spec: PlanStepSpec, specs: Sequence[PlanStepSpec]) -> bool:
    """是否构成执行单元（叶子优先，§4.4）：非父步且无子步。"""
    if spec.kind == STEP_KIND_COMPOSITE:
        return False
    return not any(other.parent_index == spec.index for other in specs)


def _has_failed_predecessor(specs: Sequence[PlanStepSpec]) -> bool:
    """是否存在「前驱已 `failed` 且本步未被 `continue` 显式放宽」的未终态步（§4.5）。"""
    status_by_index = {spec.index: spec.status for spec in specs}
    return any(
        spec.status in READY_STATUSES
        and spec.on_failure != ON_FAILURE_CONTINUE
        and any(
            status_by_index.get(reference) == STEP_STATUS_FAILED
            for reference in spec.depends_on
        )
        for spec in specs
    )


def _propagation_targets(
    specs: Sequence[PlanStepSpec], step_index: int, mode: str
) -> set[int]:
    """`abort` 的全部未终态步 / `skip` 的直接后继（§4.3.2）。"""
    if mode == ON_FAILURE_ABORT:
        return {
            spec.index for spec in specs if spec.status in READY_STATUSES
        }
    return {
        spec.index
        for spec in specs
        if spec.status in READY_STATUSES and step_index in spec.depends_on
    }


def _as_failed(spec: PlanStepSpec, step_index: int, mode: str) -> PlanStepSpec:
    """矩阵处置后的步骤副本（`failure_note` 记明来源，便于事后归因）。"""
    return spec.model_copy(
        update={
            "status": STEP_STATUS_FAILED,
            "failure_note": f"前置步骤 {step_index} 失败（on_failure={mode}）",
        }
    )


def _off_surface(spec: PlanStepSpec, ctx) -> bool:
    """就绪步的工具是否不在当前工具面上（无 `tool_id` 或无面可判时不构成阻塞）。"""
    if not spec.tool_id:
        return False
    tool_ids = getattr(getattr(ctx, "tool_surface", None), "tool_ids", None)
    if tool_ids is None:
        return False
    return spec.tool_id not in set(tool_ids)


def _in_cooldown(spec: PlanStepSpec, ctx) -> bool:
    """距上次尝试是否不足冷却窗口（缺 `now` 或缺冷却值时**不判**，绝不猜测）。"""
    now = getattr(ctx, "now", None)
    minutes = _cooldown_minutes(ctx)
    if now is None or minutes is None or spec.last_attempt_at is None:
        return False
    return (now - spec.last_attempt_at) < timedelta(minutes=minutes)


def _cooldown_minutes(ctx) -> int | None:
    """冷却窗口：显式 `ctx.step_cooldown_minutes` 优先，其次 `ctx.settings` 的既有设置项。"""
    explicit = getattr(ctx, COOLDOWN_MINUTES_KEY, None)
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            return None
    settings = getattr(ctx, "settings", None)
    value = getattr(settings, COOLDOWN_SETTING_NAME, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
