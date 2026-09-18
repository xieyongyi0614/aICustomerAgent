"""V2.0.0 Goal 维规则集（AUT-005）：Goal Consistency 六条纯函数规则。

对 GoalSlice（只读审计切片）求值：终态归因完整、完成/失败/放弃语义成立、
仲裁留痕齐备、规划预算封顶、执行周期封顶、供给形状合法。
事实由 collect_goal_slice 备齐；本层零 IO。
"""

from datetime import timedelta

from app.core.settings import get_settings
from app.models.action import ACTION_TYPES
from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule

_TERMINAL_STATUSES = ("completed", "failed", "abandoned", "expired", "cancelled")
_DOMAIN_VALUES = ("personal", "relationship", "world")
_ABANDON_CONFIDENCE_THRESHOLD = 0.6


class GoalConsistencyRule(EvaluationRule):
    """终态必有 lifecycle 归因记录——「目标不无故消失/翻转」的机制断言。"""

    code = IssueCode.GOAL_INCONSISTENT_STATE
    dimension = EvaluationDimension.GOAL
    subjects = ("goal",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        goal_slice = ctx.goal
        if goal_slice is None:
            return None
        attributed = {(ref.goal_id, ref.decision) for ref in goal_slice.lifecycles}
        for goal in goal_slice.goals:
            if goal.status not in _TERMINAL_STATUSES:
                continue
            if (goal.goal_id, goal.status) not in attributed:
                return build_issue(
                    self.code,
                    evidence_quote=f"goal {goal.goal_id} 终态 {goal.status} 无 lifecycle 记录",
                )
        return None


class GoalSemanticRule(EvaluationRule):
    """完成/失败/放弃语义成立：completed 有全 done 计划、failed 有原因、
    abandoned 有置信依据。"""

    code = IssueCode.GOAL_INVALID_TERMINATION
    dimension = EvaluationDimension.GOAL
    subjects = ("goal",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        goal_slice = ctx.goal
        if goal_slice is None:
            return None
        latest_plans: dict[str, object] = {}
        for plan in goal_slice.plans:
            known = latest_plans.get(plan.goal_id)
            if known is None or plan.version > known.version:
                latest_plans[plan.goal_id] = plan
        for goal in goal_slice.goals:
            if goal.status == "completed":
                plan = latest_plans.get(goal.goal_id)
                if plan is None or any(
                    status != "done" for status in plan.sub_goal_statuses
                ):
                    return build_issue(
                        self.code,
                        evidence_quote=f"goal {goal.goal_id} completed 但计划步骤未全 done",
                    )
            elif goal.status == "failed":
                if not goal.failure_reason:
                    return build_issue(
                        self.code,
                        evidence_quote=f"goal {goal.goal_id} failed 缺 failure_reason",
                    )
            elif goal.status == "abandoned":
                state = goal.arbitration_state or {}
                if float(state.get("confidence") or 0) < _ABANDON_CONFIDENCE_THRESHOLD:
                    return build_issue(
                        self.code,
                        evidence_quote=f"goal {goal.goal_id} abandoned 置信依据不足",
                    )
        return None


class GoalArbitrationRule(EvaluationRule):
    """suspended 必有仲裁留痕；同域（layer, domain）顶层 active ≤1。"""

    code = IssueCode.GOAL_ARBITRATION_MISSING
    dimension = EvaluationDimension.GOAL
    subjects = ("goal",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        goal_slice = ctx.goal
        if goal_slice is None:
            return None
        groups: dict[tuple[str, str], int] = {}
        for goal in goal_slice.goals:
            if goal.status == "suspended":
                state = goal.arbitration_state or {}
                if not state.get("conflict_with"):
                    return build_issue(
                        self.code,
                        evidence_quote=f"goal {goal.goal_id} suspended 无仲裁留痕",
                    )
            if goal.status == "active" and goal.parent_goal_id is None:
                key = (goal.layer, goal.domain)
                groups[key] = groups.get(key, 0) + 1
        for (layer, domain), count in groups.items():
            if count > 1:
                return build_issue(
                    self.code,
                    evidence_quote=f"同域 ({layer}, {domain}) 顶层 active 并存 {count} 个",
                )
        return None


class GoalPlanningBudgetRule(EvaluationRule):
    """每 goal 规划版本 ≤ 封顶+1（failed 单次重规划例外）；入库产物能力对齐。"""

    code = IssueCode.GOAL_PLANNING_BUDGET_EXCEEDED
    dimension = EvaluationDimension.GOAL
    subjects = ("goal",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        goal_slice = ctx.goal
        if goal_slice is None:
            return None
        settings = get_settings()
        cap = settings.autonomy_planning_max_attempts + 1
        counts: dict[str, int] = {}
        for plan in goal_slice.plans:
            counts[plan.goal_id] = counts.get(plan.goal_id, 0) + 1
            if plan.status in ("active", "validated"):
                if len(plan.sub_goal_statuses) > settings.autonomy_subgoal_max_count:
                    return build_issue(
                        self.code,
                        evidence_quote=f"goal {plan.goal_id} plan v{plan.version} 步骤数超封顶",
                    )
                unaligned = [c for c in plan.capabilities if c not in ACTION_TYPES]
                if unaligned:
                    return build_issue(
                        self.code,
                        evidence_quote=f"goal {plan.goal_id} 能力未对齐：{unaligned[0]}",
                    )
        for goal_id, count in counts.items():
            if count > cap:
                return build_issue(
                    self.code,
                    evidence_quote=f"goal {goal_id} 规划 {count} 次超封顶 {cap}",
                )
        return None


class GoalExecutionCapRule(EvaluationRule):
    """active goal 的活跃计划执行周期不得超出封顶（超期必已终态化）。"""

    code = IssueCode.GOAL_EXECUTION_CAP_EXCEEDED
    dimension = EvaluationDimension.GOAL
    subjects = ("goal",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        goal_slice = ctx.goal
        if goal_slice is None:
            return None
        settings = get_settings()
        cap = timedelta(hours=settings.autonomy_goal_max_active_hours)
        for plan in goal_slice.plans:
            if plan.status != "active" or plan.updated_at is None:
                continue
            goal = next(
                (g for g in goal_slice.goals if g.goal_id == plan.goal_id), None
            )
            if goal is None or goal.status != "active":
                continue
            reference_now = max(
                (g.updated_at for g in goal_slice.goals if g.updated_at is not None),
                default=plan.updated_at,
            )
            if reference_now - plan.updated_at > cap:
                return build_issue(
                    self.code,
                    evidence_quote=f"goal {plan.goal_id} 执行周期超出 {settings.autonomy_goal_max_active_hours}h 未终态化",
                )
        return None


class GoalSupplyMalformedRule(EvaluationRule):
    """供给形状：long_term 恒 persistent、domain 在三类白名单内。"""

    code = IssueCode.GOAL_SUPPLY_MALFORMED
    dimension = EvaluationDimension.GOAL
    subjects = ("goal",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        goal_slice = ctx.goal
        if goal_slice is None:
            return None
        for goal in goal_slice.goals:
            if goal.layer == "long_term" and goal.horizon != "persistent":
                return build_issue(
                    self.code,
                    evidence_quote=f"goal {goal.goal_id} long_term 非 persistent（Persistence 语义被破坏）",
                )
            if goal.domain not in _DOMAIN_VALUES:
                return build_issue(
                    self.code,
                    evidence_quote=f"goal {goal.goal_id} domain 非白名单：{goal.domain}",
                )
        return None


RULES: list[EvaluationRule] = [
    GoalConsistencyRule(),
    GoalSemanticRule(),
    GoalArbitrationRule(),
    GoalPlanningBudgetRule(),
    GoalExecutionCapRule(),
    GoalSupplyMalformedRule(),
]
