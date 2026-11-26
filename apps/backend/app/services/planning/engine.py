"""V2.5.0 PLAN-003 规划引擎核心（Task Detail §4.1.4 / §4.1.5 / architecture.md §3.4、§8.1）。

本模块回答「这个目标能不能变成一份合法计划」。**包装既有 `goal_planning`，不新建规划器**：
规划 LLM 面经 `goal_planning.propose_plan` 复用（同 prompt、同 `_LLM_RETRY_ATTEMPTS` 重试语义），
计划落库经 `goal_repository` 计划面四函数（单一写面）。

七道闸短路（Task Detail §4.2.4）

| # | 闸门 | 理由码 | 依据 |
|---|---|---|---|
| 1 | 总闸与尝试次数 | `attempt_cap` | `count_plans` vs `autonomy_planning_max_attempts` |
| 2 | 步骤数上限 | `subgoal_count_exceeded` | `min(plan_max_steps, autonomy_subgoal_max_count)` |
| 3 | 形状合法 | `invalid_sub_goal_shape` | `validate_sub_goals`（序号 / 前向依赖 / 深度） |
| 4 | 能力对齐 | `capability_unaligned` | `capability ∈ ACTION_TYPES` |
| 5 | **工具可解析** | `plan_tool_unresolvable` | `ToolRegistry.resolve(tool_id)` |
| 6 | **工具在面上** | `plan_tool_off_surface` | `tool_id ∈ ctx.tool_surface.tool_ids` |
| 7 | LLM 失败 | `llm_failed` | 既有重试耗尽 |

闸门 5 与 6 的区别是评审要点：5 问「这个工具存在吗」（声明面），6 问「这一刻它能用吗」
（运行时面）。`channel.feishu.send` 在 `late_night` 被工具面剔除时**闸门 5 过、闸门 6 拒**——
计划步数与内容不变，只是暂不装配该步。两道闸门默认为 on（绑定子闸已随开关体系删除），
且可分别独立关闭（构造参数），用于单列验证。

PLAN-006 补齐的判定细节（Task Detail §6.1 的两个内部接口，实现为模块级纯函数以便单列验证）

```text
_evaluate_tool_resolvable(steps, registry) -> str | None   # 闸门 5：不可解析的 tool_id
_evaluate_tool_on_surface(steps, surface) -> str | None     # 闸门 6：不在面上的 tool_id
```

1. **判定对象收窄为 `kind="tool"` 且 `tool_id` 非空**的步骤（Task Detail §8 Step 1.1 / Step 1.2）：
   与其判定面不相干的步骤（纯观测 / 复合父步）不参与——「`kind != tool` 却带 `tool_id`」属
   PLAN-004 `PlanValidator.validate_binding` 的判定面（`invalid_step_binding`），本闸不越界。
2. **闸门 6 零面重算**（D2）：只读 `surface.tool_ids`，**不自行调用 `ToolSurfaceResolver`**
   （面由装配期提供，本模块零面解析）；`engine.py` 不导入 `services.tool.surface`。
3. **闸门 5 零注册表改动**（D1）：只调 `ToolRegistry.resolve`（只读），注册表快照前后一致；
   注册表不可得（工具系统总闸 off）时 **fail-closed**（判不可解析），不静默放行。

契约纪律（Task Detail §6.1）

- `plan` / `revise` 为 async（含 LLM 调用），受 `llm_gateway`（经 `goal_planning` 既有 profile）
  与 `life_loop_budget` 双重约束；预算降级时**优雅跳过**（`status="skipped"`，不抛错）。
- **拒绝路径不抛异常**：拒绝是正常业务结果（`status="rejected"` + 理由码）。
- `engine.py` 零 session / 零 ORM 写构造；落库只经 `goal_repository` 计划面四函数。
- 零工具选择逻辑：只用 `ToolRegistry.resolve` 做可解析判定（选择属执行期 `ToolSelector`）。

与 Task Detail 的两处实现裁决（均已在测试留痕）

1. §4.1.4 闸门 2（步数）与闸门 3（形状）的编号顺序不可直接照搬：步数必须在
   `validate_sub_goals` 解析出 specs 之后才可数。故实际判定序为「形状 → 步数 → 能力」，
   与既有 AUT-002 `plan_goal` 的实现顺序一致（同一组闸门，无新增语义）。
2. 计划阶段子步骤（`plan_assemble` / `plan_generate` / `plan_revise`）由本模块记入
   `loop_runs.steps`（`ctx.run["run_id"]` 存在时），**不由 `assemble` 写**——`assemble`
   的零写库是本任务的硬断言（Task Detail §7），二者冲突时以零写库为准。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.core import timeutil
from app.core.settings import get_settings
from app.models.action import ACTION_TYPES
from app.models.goal import GoalPlanRecord, GoalRecord, SubGoalSpec, validate_sub_goals
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.repositories import goal_repository, loop_run_repository
from app.services.goal import planning as goal_planning
from app.services.life import budget as life_loop_budget
from app.services.planning.context import context_digest
from app.services.planning.goal_contract import PLANNING_FAILURE_REASON_PLAN_EXHAUSTED
from app.services.tool.registry import ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

REASON_ATTEMPT_CAP = goal_planning.REASON_ATTEMPT_CAP
REASON_COUNT_EXCEEDED = goal_planning.REASON_COUNT_EXCEEDED
REASON_INVALID_SHAPE = goal_planning.REASON_INVALID_SHAPE
REASON_CAPABILITY_UNALIGNED = goal_planning.REASON_CAPABILITY_UNALIGNED
REASON_TOOL_UNRESOLVABLE = "plan_tool_unresolvable"
REASON_TOOL_OFF_SURFACE = "plan_tool_off_surface"
REASON_LLM_FAILED = goal_planning.REASON_LLM_FAILED

PLANNING_REASONS: tuple[str, ...] = (
    REASON_ATTEMPT_CAP,
    REASON_COUNT_EXCEEDED,
    REASON_INVALID_SHAPE,
    REASON_CAPABILITY_UNALIGNED,
    REASON_TOOL_UNRESOLVABLE,
    REASON_TOOL_OFF_SURFACE,
    REASON_LLM_FAILED,
)

REASON_REVISION_EXHAUSTED = "plan_revision_exhausted"
REASON_BUDGET_DEGRADED = "budget_degraded"

STEP_KIND_TOOL = "tool"
"""闸门 5/6 的判定对象类型：值域取自 `models/goal.py::StepKind`（`tool` / `observe` / `composite`）。

本模块**不导入** PLAN-004 拆解模块的同名常量：PLAN-004 的静态红线是「引擎不接线拆解」
（见 `tests/v25/test_plan004_static_scan.py` 的对应用例），即 PLAN-003 的引擎不得依赖
PLAN-004 的产物方向。值域漂移由 `tests/v25/test_plan006_static_scan.py` 对模型值域的
对照断言兜住（`SubGoalSpec.kind` 的默认值与 `STEP_KIND_VALUES`）。
"""

PLAN_STATUS_VALIDATED = "validated"
PLAN_STATUS_REJECTED = "rejected"
PLAN_STATUS_SKIPPED = "skipped"

PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_DONE = "done"

PLAN_STEP_ASSEMBLE = "plan_assemble"
PLAN_STEP_GENERATE = "plan_generate"
PLAN_STEP_REVISE = "plan_revise"

@dataclass
class PlanOutcome:
    """`plan` / `revise` 的返回契约（Task Detail §4.2.2）。

    `status` 取 `validated` / `rejected` / `skipped`；后者的唯一来源是
    `life_loop_budget` 降级（规划被跳过，不报错、不落库）。
    """

    status: str
    plan: GoalPlanRecord | None = None
    rejection_reason: str | None = None
    steps: list[SubGoalSpec] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)

    @property
    def validated(self) -> bool:
        """是否产出合法计划（`validated` 即七道闸全过）。"""
        return self.status == PLAN_STATUS_VALIDATED


@dataclass(frozen=True)
class _Draft:
    """单次生成的判定上下文（目标 / 上下文 / 触发源 / 尝试次数 / 时刻）。"""

    goal: GoalRecord
    ctx: PlanContext
    trigger: str
    attempts: int
    now: datetime


class PlanningEngine:
    """七道闸规划引擎（`plan` / `revise` / `enqueue` / `run_jobs` / `register_runtime`）。

    `tool_binding_enabled` 缺省为 on（绑定子闸已随开关体系删除）；`tool_resolvable_gate` /
    `tool_surface_gate` 是闸门 5 / 6 的**独立开关**（Task Detail §8 Step 4.4 要求二者可分别
    关闭并单独验证）。两者仅在绑定子闸开启时生效。
    """

    def __init__(
        self,
        *,
        tool_binding_enabled: bool | None = None,
        tool_resolvable_gate: bool = True,
        tool_surface_gate: bool = True,
    ) -> None:
        self._tool_binding_enabled = tool_binding_enabled
        self._tool_resolvable_gate = tool_resolvable_gate
        self._tool_surface_gate = tool_surface_gate

    async def plan(
        self, goal: GoalRecord, ctx: PlanContext, *, trigger: str
    ) -> PlanOutcome:
        """首次生成：七道闸全过即落一条 `validated` 计划（激活属 PLAN-005）。"""
        return await self._generate(goal, ctx, trigger=trigger, kept=[])

    async def revise(
        self, plan: GoalPlanRecord, ctx: PlanContext, *, reason: str
    ) -> PlanOutcome:
        """修订（Task Detail §4.1.5）：版本 +1、旧版置 `superseded`、已完成步骤不重做。

        达 `plan_revision_budget` 即终止：计划置 `rejected`、目标转
        `failed(failure_reason="plan_exhausted")`（不吞写面抛出的 `ValueError`）。
        """
        settings = get_settings()
        attempts = goal_repository.count_plans(plan.goal_id)
        if attempts >= settings.plan_revision_budget:
            return self._exhaust(plan, ctx, reason)
        kept = [spec for spec in plan.sub_goals if spec.status == PLAN_STATUS_DONE]
        outcome = await self._generate(
            ctx.goal, ctx, trigger=goal_planning.TRIGGER_REPLAN, kept=kept
        )
        if outcome.validated and plan.status == PLAN_STATUS_ACTIVE:
            goal_repository.set_plan_status(plan.id, "superseded")
        _record_run_step(
            ctx,
            PLAN_STEP_REVISE,
            {
                "reason": reason,
                "from_version": plan.version,
                "kept_steps": [spec.index for spec in kept],
                "status": outcome.status,
            },
        )
        return outcome

    def enqueue(
        self, user_id: str, goal_id: str, trigger: str, *, ctx: PlanContext | None = None
    ) -> bool:
        """入队规划 job（幂等）：`job_type` 仍为既有 `goal_planning`，键含 trigger。

        装配在 job 执行期发生，故 `ctx` 可缺省；提供时其世界源作为 job 载荷的事实包
        （`world_facts`），使执行期规划的 prompt 与本轮装配同源。
        """
        world_facts = None if ctx is None else dict(ctx.world)
        return goal_planning.enqueue_planning(user_id, goal_id, trigger, world_facts)

    def run_jobs(self) -> int:
        """处理本类型 running 载荷（委托既有 `goal_planning.run_planning_jobs`）。"""
        return goal_planning.run_planning_jobs()

    def register_runtime(self) -> None:
        """注册 job handler（委托既有 `goal_planning.register_runtime`）。"""
        goal_planning.register_runtime()

    async def _generate(
        self,
        goal: GoalRecord,
        ctx: PlanContext,
        *,
        trigger: str,
        kept: list[SubGoalSpec],
    ) -> PlanOutcome:
        settings = get_settings()
        draft = _Draft(
            goal=goal,
            ctx=ctx,
            trigger=trigger,
            attempts=goal_repository.count_plans(goal.id),
            now=timeutil.now(),
        )
        _record_run_step(
            ctx, PLAN_STEP_ASSEMBLE, {"degraded": list(ctx.degraded), "goal_id": goal.id}
        )
        skipped = self._budget_skip(ctx)
        if skipped is not None:
            return skipped
        reason = _pre_llm_gate(draft, settings)
        if reason is not None:
            return self._reject(draft, reason)
        proposal = await _ask_proposal(draft, settings)
        if proposal is None:
            return self._reject(draft, REASON_LLM_FAILED)
        specs, reason = _parse_specs(proposal, settings)
        if specs is None:
            return self._reject(draft, reason or REASON_INVALID_SHAPE)
        reason = self._binding_gate(specs, ctx, settings)
        if reason is not None:
            return self._reject(draft, reason)
        return self._persist(draft, _merge_kept_steps(specs, kept))

    def _budget_skip(self, ctx: PlanContext) -> PlanOutcome | None:
        """日额度熔断时优雅跳过（不报错、不落库、不消耗计划版本号）。"""
        if not life_loop_budget.is_degraded():
            return None
        logger.info("日 LLM 额度降级，本轮规划跳过")
        _record_run_step(
            ctx,
            PLAN_STEP_GENERATE,
            {"status": PLAN_STATUS_SKIPPED, "reason": REASON_BUDGET_DEGRADED},
        )
        return PlanOutcome(
            status=PLAN_STATUS_SKIPPED,
            rejection_reason=REASON_BUDGET_DEGRADED,
            degraded=list(ctx.degraded),
        )

    def _reject(self, draft: _Draft, reason: str) -> PlanOutcome:
        """拒绝路径：落一条 `rejected` 计划（落库失败即容忍）+ 返回理由码，**不抛异常**。"""
        record = self._create_rejection(draft, reason)
        _record_run_step(
            draft.ctx,
            PLAN_STEP_GENERATE,
            {"status": PLAN_STATUS_REJECTED, "reason": reason, "goal_id": draft.goal.id},
        )
        return PlanOutcome(
            status=PLAN_STATUS_REJECTED,
            plan=record,
            rejection_reason=reason,
            degraded=list(draft.ctx.degraded),
        )

    def _persist(self, draft: _Draft, specs: list[SubGoalSpec]) -> PlanOutcome:
        """七道闸全过的落库：经 `goal_repository.create_plan`（单一写面）。

        返回 `PlanOutcome.plan` 用**内存记录**而非 `create_plan` 的返回值：后者只映射既有
        列，会丢掉 PLAN-002 的 4 个扩展字段（`trigger` / `context_digest` / `revision_of` /
        `evidence_refs`，落 `decision_records.input_snapshot`，属 PLAN-011）。两者 `id` /
        `version` / `status` 同源，可交叉校验。
        """
        record = GoalPlanRecord(
            goal_id=draft.goal.id,
            version=draft.attempts + 1,
            status=PLAN_STATUS_VALIDATED,
            sub_goals=list(specs),
            created_at=draft.now,
            updated_at=draft.now,
            trigger=draft.trigger,
            context_digest=context_digest(draft.ctx),
            evidence_refs=tuple(draft.ctx.evidence_refs),
        )
        stored = goal_repository.create_plan(record)
        _record_run_step(
            draft.ctx,
            PLAN_STEP_GENERATE,
            {
                "status": PLAN_STATUS_VALIDATED,
                "goal_id": draft.goal.id,
                "version": stored.version,
                "steps": [spec.index for spec in specs],
                "degraded": list(draft.ctx.degraded),
            },
        )
        return PlanOutcome(
            status=PLAN_STATUS_VALIDATED,
            plan=record,
            steps=list(specs),
            degraded=list(draft.ctx.degraded),
        )

    def _exhaust(self, plan: GoalPlanRecord, ctx: PlanContext, reason: str) -> PlanOutcome:
        """修订预算耗尽：计划置 `rejected` + 目标转 `failed("plan_exhausted")`。"""
        record = goal_repository.set_plan_rejection(plan.id, REASON_REVISION_EXHAUSTED)
        goal_repository.fail_goal(plan.goal_id, PLANNING_FAILURE_REASON_PLAN_EXHAUSTED)
        _record_run_step(
            ctx,
            PLAN_STEP_REVISE,
            {
                "reason": reason,
                "status": PLAN_STATUS_REJECTED,
                "exhausted": True,
                "version": plan.version,
            },
        )
        return PlanOutcome(
            status=PLAN_STATUS_REJECTED,
            plan=record,
            rejection_reason=REASON_REVISION_EXHAUSTED,
            degraded=list(ctx.degraded),
        )

    def _binding_gate(
        self, specs: list[SubGoalSpec], ctx: PlanContext, settings
    ) -> str | None:
        """闸门 5 / 6：工具可解析（声明面）与工具在面上（运行时面），受绑定子闸门控。

        两个判定各自委托模块级纯函数（§6.1 冻结签名），故「闸门 5 过、闸门 6 拒」
        可单列验证（Task Detail §9.1 U4）：两道闸门按序独立判定，前一道不通过即短路。
        """
        enabled = (
            True if self._tool_binding_enabled is None else self._tool_binding_enabled
        )
        if not enabled:
            return None
        if self._tool_resolvable_gate and (
            _evaluate_tool_resolvable(specs, get_tool_registry()) is not None
        ):
            return REASON_TOOL_UNRESOLVABLE
        if self._tool_surface_gate and (
            _evaluate_tool_on_surface(specs, ctx.tool_surface) is not None
        ):
            return REASON_TOOL_OFF_SURFACE
        return None

    @staticmethod
    def _create_rejection(draft: _Draft, reason: str) -> GoalPlanRecord | None:
        try:
            return goal_repository.create_plan(
                GoalPlanRecord(
                    goal_id=draft.goal.id,
                    version=draft.attempts + 1,
                    status=PLAN_STATUS_REJECTED,
                    rejection_reason=reason[:200],
                    created_at=draft.now,
                    updated_at=draft.now,
                )
            )
        except Exception:
            logger.exception("rejected 计划落库失败（goal=%s）", draft.goal.id)
            return None


_ENGINE = PlanningEngine()


def get_planning_engine() -> PlanningEngine:
    """默认引擎实例（生活环挂载与后续任务共用同一开关面；引擎无状态，进程内单例）。"""
    return _ENGINE


def _evaluate_tool_resolvable(
    specs: list[SubGoalSpec], registry: ToolRegistry | None
) -> str | None:
    """闸门 5 判定（Task Detail §6.1）：任一 `kind="tool"` 且 `tool_id` 非空的步骤
    不可经 `ToolRegistry.resolve` 解析，即返回该 `tool_id`；全通过返回 `None`。

    只读消费（D1）：本函数零注册表改动，唯一触达面是 `resolve`——不注册 / 不禁用 /
    不熔断任何工具，也不读健康度与生命周期（快照前后逐层一致）。
    `registry is None`（工具系统总闸 off）时 **fail-closed**：无法解析即判不可解析
    （宁可不规划，也不让「不知道存不存在」的工具进计划）。
    """
    for spec in specs:
        if not _is_tool_step(spec):
            continue
        if registry is None or registry.resolve(spec.tool_id) is None:
            return str(spec.tool_id)
    return None


def _evaluate_tool_on_surface(
    specs: list[SubGoalSpec], surface: ToolSurface | None
) -> str | None:
    """闸门 6 判定（Task Detail §6.1）：任一 `kind="tool"` 且 `tool_id` 非空的步骤
    不在 `surface.tool_ids` 上，即返回该 `tool_id`；全通过返回 `None`。

    **零面重算**（D2）：只读调用方提供的面，不自行调用 `ToolSurfaceResolver`
    （面属装配期产物，本模块零面解析）；`surface is None` 时视为空面（全部不在面上）。
    """
    on_surface = set(() if surface is None else surface.tool_ids)
    for spec in specs:
        if not _is_tool_step(spec):
            continue
        if str(spec.tool_id) not in on_surface:
            return str(spec.tool_id)
    return None


def _is_tool_step(spec: SubGoalSpec) -> bool:
    """闸门 5/6 的判定对象：`kind="tool"` 且 `tool_id` 非空（Task Detail §8 Step 1.1）。

    父步（`composite`）与纯观测步（`observe`）不是工具步：其绑定合法性属 PLAN-004 的
    形状 / 绑定闸，本模块不越界。
    """
    return bool(spec.tool_id) and spec.kind == STEP_KIND_TOOL


def _unresolvable_tool(specs: list[SubGoalSpec]) -> str | None:
    """PLAN-003 既有探针名（`test_plan003_engine.py` 按此名调用）：委托闸门 5 正体。

    保留该名字是**契约兼容**而非第二套实现：PLAN-003 的单测把它当闸门 5 的只读探针用，
    改名属既有测试的契约变更；正体已是 `_evaluate_tool_resolvable`（§6.1 冻结签名）。
    """
    return _evaluate_tool_resolvable(specs, get_tool_registry())


async def _ask_proposal(
    draft: _Draft, settings
) -> "goal_planning.PlanningProposal | None":
    """规划提案：复用既有 prompt 与重试语义（不重复实现 LLM 调用）；失败返回 None。

    PLAN-010 §8 Step 5：`ctx.evidence_refs`（本轮 Run 携带的反思 / 记忆证据 id）进 prompt，
    使新轮次看得见「上次这么做没成」。**空证据时沿用既有三参调用形态**（prompt 与
    调用面都逐字节不变）。
    """
    try:
        return await asyncio.to_thread(
            goal_planning.propose_plan,
            draft.goal,
            dict(draft.ctx.world),
            _llm_settings(settings),
            *_proposal_evidence(draft),
        )
    except Exception as exc:
        logger.warning("规划 LLM 调用失败：%s", exc.__class__.__name__)
        return None


def _proposal_evidence(draft: _Draft) -> tuple:
    """提案的证据引用实参：`()`（无证据，既有形态）或 `(evidence_refs,)`（PLAN-010 扩源）。"""
    refs = tuple(draft.ctx.evidence_refs)
    return (refs,) if refs else ()


def _llm_settings(settings):
    """`plan_llm_profile` 非空时覆盖既有规划 profile（空 = 沿用既有配置）。"""
    profile = str(getattr(settings, "plan_llm_profile", "") or "")
    if not profile:
        return settings
    return settings.model_copy(update={"autonomy_planning_llm_profile": profile})


def _pre_llm_gate(draft: _Draft, settings) -> str | None:
    """闸门 1：尝试次数封顶（`failure_replan` 的既有单次放行语义不变）。"""
    failure_replan = (
        draft.trigger == goal_planning.TRIGGER_REPLAN and draft.goal.status == "failed"
    )
    max_attempts = settings.autonomy_planning_max_attempts
    if draft.attempts > max_attempts or (
        draft.attempts >= max_attempts and not failure_replan
    ):
        return REASON_ATTEMPT_CAP
    return None


def _parse_specs(proposal, settings) -> tuple[list[SubGoalSpec] | None, str | None]:
    """闸门 3 → 闸门 2 → 闸门 4：解析（形状）→ 步数 → 能力对齐。

    返回 `(specs, None)` 即三道闸全过；返回 `(None, 理由码)` 即拒绝。步数必须在解析之后
    才可数，故实现序为形状 → 步数 → 能力（与既有 AUT-002 实现一致，见模块文档裁决 1）。
    """
    try:
        specs = validate_sub_goals(
            proposal.sub_goals,
            max_depth=min(
                settings.autonomy_subgoal_max_depth, settings.plan_max_depth
            ),
        )
    except ValueError:
        return None, REASON_INVALID_SHAPE
    if len(specs) > min(
        settings.plan_max_steps, settings.autonomy_subgoal_max_count
    ):
        return None, REASON_COUNT_EXCEEDED
    unaligned = next(
        (spec.capability for spec in specs if spec.capability not in ACTION_TYPES), None
    )
    if unaligned is not None:
        return None, REASON_CAPABILITY_UNALIGNED
    return specs, None


def _merge_kept_steps(
    generated: list[SubGoalSpec], kept: list[SubGoalSpec]
) -> list[SubGoalSpec]:
    """已终态（`done`）步骤不重做（Task Detail §4.1.5）：同 `index` 复用既有步骤。"""
    if not kept:
        return generated
    by_index = {spec.index: spec for spec in kept}
    merged = [by_index.get(spec.index, spec) for spec in generated]
    known = {spec.index for spec in generated}
    merged.extend(spec for spec in kept if spec.index not in known)
    return sorted(merged, key=lambda spec: spec.index)


def _record_run_step(ctx: PlanContext, step: str, detail: dict) -> None:
    """计划阶段以子步骤记入 `loop_runs.steps`（`ctx.run` 带 run_id 时）；失败即忽略。"""
    run_id = str((ctx.run or {}).get("run_id") or "")
    if not run_id:
        return
    try:
        loop_run_repository.mark_step(run_id, {"step": step, **detail})
    except Exception:
        logger.exception("计划子步骤记账失败，已忽略：%s", step)
