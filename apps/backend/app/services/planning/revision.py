"""V2.5.0 PLAN-005 重规划裁决（Task Detail §4.2.6 / §4.2.7 / §6.5；architecture.md §3.9、§8.5）。

本模块回答「这个计划还值不值得继续，要不要换一种做法」。**纯函数策略，不是执行者**：
不执行动作、不入队、不落库（D14）——它只返回**理由码**，入队与落库由调用方完成
（`enqueue_planning(TRIGGER_REPLAN)` 属 PLAN-003 / PLAN-010 的接线，本任务只定义判定入口）。

四个重规划理由码（§4.2.7，任一成立即返回；判定序固定 = 表序）

| 理由码 | 触发条件 | 判定依据 |
|---|---|---|
| `step_attempt_exhausted` | 达尝试上限且 `on_failure=replan` | `attempt_count ≥ 限值` 或失败类型不可重试 |
| `tool_persistently_unavailable` | 工具连续 N tick 始终 `off_surface` | `ctx.off_surface_streak` 达阈 |
| `criteria_undecidable` | `evaluate_criteria` 连续返回 `None` | `ctx.undecidable_streak` 达阈 |
| `insight_driven` | Reflection Insight 达门槛并指向该目标 | `ctx.insight_driven`（PLAN-010 投递，本任务只定义入口） |

**避免「无限重规划」是本模块存在的首要理由**：既有 `goal_planning._LLM_RETRY_ATTEMPTS` 只管
LLM 调用失败，管不了「计划本身行不通」。终止路径由 `budget_exhausted` 判定
（`plan.version ≥ v25_plan_revision_budget`）→ 计划 `rejected` + 目标
`failed("plan_exhausted")`（终态由既有 `PlanningEngine.revise::_exhaust` 落，本模块不写）。

**保留已完成步骤（G-RETRY，本任务最容易写错的一处）**：步级幂等键由
`PLAN_STEP_DEDUPE_KEY_TEMPLATE`（`models/plan.py` 的唯一字面声明处）渲染为
`plan:<goal_id>:<version>:<index>`，版本号变化会让所有步骤的幂等键改变——若不保留已完成步骤，
重规划会把已经产生世界副作用（如已创建的提醒）的步骤**再做一遍**。故 `kept_steps` 是修正路径
的**强制载荷**（D15），`explain` 也必带该字段。

`ctx` 契约（鸭子类型，零 IO / 零 `get_settings()` 直调）

| 键 | 含义 | 缺省 |
|---|---|---|
| `ctx.step_max_attempts` 或 `ctx.budget` 同名键 | Plan 层尝试限值 | `STEP_MAX_ATTEMPTS_DEFAULT` |
| `ctx.off_surface_threshold` | `off_surface` 连续计数阈值 | 2 |
| `ctx.undecidable_threshold` | 判据不可判定连续计数阈值 | 2 |
| `ctx.off_surface_streak` / `ctx.undecidable_streak` | 连续计数（调用方维护） | 0 |
| `ctx.insight_driven` | PLAN-010 的 Insight 投递信号 | `False` |

阈值 N 由本模块定义（settings 无对应项）：新增 `v25_*` 参数会改动 PLAN-002 冻结的
「13 Flag + 14 参数」快照，与零迁移 / 零新增配置的强断言冲突；阈值是**判定纪律**而非可调
策略，故以模块常量承载。退避数学**只有一份**（Action 层），本模块不复制、不新增退避字段。
"""

from __future__ import annotations

from app.models.goal import SubGoalSpec
from app.models.plan import RetryPolicy

PlanStepSpec = SubGoalSpec

STEP_MAX_ATTEMPTS_DEFAULT = 2
OFF_SURFACE_THRESHOLD = 2
UNDECIDABLE_THRESHOLD = 2

REASON_STEP_ATTEMPT_EXHAUSTED = "step_attempt_exhausted"
REASON_TOOL_PERSISTENTLY_UNAVAILABLE = "tool_persistently_unavailable"
REASON_CRITERIA_UNDECIDABLE = "criteria_undecidable"
REASON_INSIGHT_DRIVEN = "insight_driven"

REVISION_REASONS: tuple[str, ...] = (
    REASON_STEP_ATTEMPT_EXHAUSTED,
    REASON_TOOL_PERSISTENTLY_UNAVAILABLE,
    REASON_CRITERIA_UNDECIDABLE,
    REASON_INSIGHT_DRIVEN,
)

NON_RETRYABLE_FAILURE_KINDS: tuple[str, ...] = ("denied", "invalid", "permanent")
"""按 §4.3.6 不重试的三类（授权拒绝 / 参数非法 / 永久失败）：`replan` 策略下直接判「做法不行」。"""

STEP_STATUS_DONE = "done"
STEP_STATUS_FAILED = "failed"

OUTCOME_FAILED = "failed"
OUTCOME_BLOCKED = "blocked"

ON_FAILURE_REPLAN = "replan"

RETRY_MODE_NONE = "none"
RETRY_MODE_ONCE = "once"
RETRY_MODE_UNTIL_BUDGET = "until_budget"

RETRY_POLICY_ATTEMPTS: dict[str, int] = {RETRY_MODE_NONE: 0, RETRY_MODE_ONCE: 1}
"""`none` / `once` 的界在 `RetryPolicy` 自身；`until_budget` 的界在 settings（`is_bounded=False`）。"""

BUDGET_ATTEMPTS_KEY = "step_max_attempts"

__all__ = [
    "BUDGET_ATTEMPTS_KEY",
    "NON_RETRYABLE_FAILURE_KINDS",
    "OFF_SURFACE_THRESHOLD",
    "PlanRevisionPolicy",
    "REASON_CRITERIA_UNDECIDABLE",
    "REASON_INSIGHT_DRIVEN",
    "REASON_STEP_ATTEMPT_EXHAUSTED",
    "REASON_TOOL_PERSISTENTLY_UNAVAILABLE",
    "RETRY_POLICY_ATTEMPTS",
    "REVISION_REASONS",
    "STEP_MAX_ATTEMPTS_DEFAULT",
    "UNDECIDABLE_THRESHOLD",
]


class PlanRevisionPolicy:
    """纯函数重规划策略：理由码判定 / 保留步 / 策略映射 / 可读裁决。"""

    def should_replan(self, outcome, plan, ctx) -> str | None:
        """四条判据（§4.2.7，判定序 = 表序），返回理由码；`None` = 不重规划（零副作用）。"""
        step = _find_step(plan, outcome.step_index)
        if self._attempt_exhausted(outcome, step, ctx):
            return REASON_STEP_ATTEMPT_EXHAUSTED
        if _streak_value(ctx, "off_surface_streak") >= _threshold(
            ctx, "off_surface_threshold", OFF_SURFACE_THRESHOLD
        ):
            return REASON_TOOL_PERSISTENTLY_UNAVAILABLE
        if _streak_value(ctx, "undecidable_streak") >= _threshold(
            ctx, "undecidable_threshold", UNDECIDABLE_THRESHOLD
        ):
            return REASON_CRITERIA_UNDECIDABLE
        if bool(getattr(ctx, "insight_driven", False)):
            return REASON_INSIGHT_DRIVEN
        return None

    @staticmethod
    def policy_for(
        step: PlanStepSpec, *, max_attempts: int = STEP_MAX_ATTEMPTS_DEFAULT
    ) -> RetryPolicy:
        """由 `step.retry_policy` 映射为 `RetryPolicy`（**引用 settings，不自建退避**）。

        `until_budget` 的界在 `v25_plan_step_max_attempts`（由调用方经 `max_attempts` 注入，
        缺省即该设置项的出厂值）；`none` / `once` 的界在本对象。`RetryPolicy` 只承载
        「尝试上限由谁裁决」，**零退避字段**——退避数学只有一份，在 Action 层。
        """
        mode = step.retry_policy
        if mode == RETRY_MODE_UNTIL_BUDGET:
            return RetryPolicy(mode=mode, max_attempts=max(int(max_attempts), 0))
        if mode not in RETRY_POLICY_ATTEMPTS:
            raise ValueError(f"retry_policy 取值非法：{mode!r}")
        return RetryPolicy(mode=mode, max_attempts=RETRY_POLICY_ATTEMPTS[mode])

    @staticmethod
    def kept_steps(plan) -> list[int]:
        """保留步（§4.1.5 ② / G-RETRY）：已 `done` 的步骤序号，新版本复用同 `index` / 同判据。"""
        return [
            spec.index for spec in plan.sub_goals if spec.status == STEP_STATUS_DONE
        ]

    @staticmethod
    def dropped_steps(plan) -> list[int]:
        """丢弃步（新版本重规划的部分）：非 `done` 的步骤序号。"""
        return [
            spec.index for spec in plan.sub_goals if spec.status != STEP_STATUS_DONE
        ]

    @staticmethod
    def budget_exhausted(plan, *, revision_budget: int) -> bool:
        """修订预算终止判定（§4.1.5 ①）：`plan.version ≥ v25_plan_revision_budget`。

        引擎侧的终止动作由既有 `PlanningEngine.revise` 承担（计划置 `rejected` + 目标
        `failed("plan_exhausted")`，其自身另有一道 `count_plans` 守卫）；本判定是「该不该再修」
        的可判定投影，`version` 每次修订 +1 且单调，与 `count_plans` 互为交叉校验。
        """
        return int(plan.version) >= max(int(revision_budget), 0)

    def explain(self, plan, reason: str) -> dict:
        """可读裁决（进计划审计）：**必带 `kept_steps`**（D15）与失败步证据。"""
        kept = self.kept_steps(plan)
        dropped = self.dropped_steps(plan)
        return {
            "reason": reason,
            "goal_id": plan.goal_id,
            "plan_id": plan.id,
            "from_version": plan.version,
            "to_version": plan.version + 1,
            "kept_steps": kept,
            "dropped_steps": dropped,
            "failed_steps": _failed_steps(plan),
            "narrative": (
                f"重规划理由 {reason}：保留已完成步骤 {kept}，"
                f"其余步骤 {dropped} 在新版本 v{plan.version + 1} 中重做"
            ),
        }

    @staticmethod
    def _attempt_exhausted(outcome, step, ctx) -> bool:
        """判据一：`on_failure=replan` 且（尝试达限 或 失败类型不可重试）。"""
        if step is None or step.on_failure != ON_FAILURE_REPLAN:
            return False
        if outcome.status not in (OUTCOME_FAILED, OUTCOME_BLOCKED):
            return False
        limit = _step_max_attempts(ctx)
        if step.attempt_count >= limit:
            return True
        return outcome.failure_kind in NON_RETRYABLE_FAILURE_KINDS


def _failed_steps(plan) -> list[dict]:
    return [
        {
            "index": spec.index,
            "attempt_count": spec.attempt_count,
            "failure_note": spec.failure_note,
        }
        for spec in plan.sub_goals
        if spec.status == STEP_STATUS_FAILED
    ]


def _find_step(plan, step_index) -> PlanStepSpec | None:
    return next(
        (spec for spec in plan.sub_goals if spec.index == step_index), None
    )


def _step_max_attempts(ctx) -> int:
    """Plan 层尝试限值：`ctx.step_max_attempts` → `ctx.budget["step_max_attempts"]` → 出厂默认。"""
    explicit = getattr(ctx, "step_max_attempts", None)
    if explicit is None:
        budget = getattr(ctx, "budget", None)
        explicit = budget.get(BUDGET_ATTEMPTS_KEY) if isinstance(budget, dict) else None
    if explicit is None:
        return STEP_MAX_ATTEMPTS_DEFAULT
    try:
        return max(int(explicit), 0)
    except (TypeError, ValueError):
        return STEP_MAX_ATTEMPTS_DEFAULT


def _streak_value(ctx, name: str, default: int = 0) -> int:
    """连续计数 / 阈值取值（缺省与非法值一律回退默认，纯函数不抛错）。"""
    raw = getattr(ctx, name, None)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _threshold(ctx, name: str, default: int) -> int:
    return max(_streak_value(ctx, name, default), 0)
