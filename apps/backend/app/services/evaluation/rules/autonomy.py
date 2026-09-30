"""V7.5 Autonomy 维规则集（autonomy-evaluation.md §3）：delivered 时点结果审计。

事前拦截归 AutonomyPolicy（V7），本层验证"发出去的"确实满足当时被承诺的条件。
纯函数：时机事实由 collect_proactive_context 切片备齐。
"""

from app.core.settings import get_settings
from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.autonomy_policy import (
    PolicySnapshot,
    effective_interval_minutes,
    in_quiet_hours,
)
from app.services.evaluation.context import EvaluationContext
from app.services.evaluation.rules import EvaluationRule


class TimingViolationRule(EvaluationRule):
    code = IssueCode.AUTONOMY_TIMING_VIOLATION
    dimension = EvaluationDimension.AUTONOMY
    subjects = ("proactive_action",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        proactive = ctx.proactive
        if proactive is None or proactive.delivered_at is None:
            return None
        reason = self._violation_reason(ctx, proactive)
        if reason is None:
            return None
        return build_issue(self.code, evidence_quote=reason)

    def _violation_reason(self, ctx, proactive) -> str | None:
        settings = get_settings()
        delivered_at = proactive.delivered_at
        if in_quiet_hours(
            delivered_at,
            settings.autonomy_quiet_hours_start,
            settings.autonomy_quiet_hours_end,
        ):
            return "delivered 时点位于静音时段"
        if (
            proactive.last_user_message_at is not None
            and (delivered_at - proactive.last_user_message_at).total_seconds() / 60
            < settings.autonomy_min_user_reply_gap_minutes
        ):
            return "用户刚发言即投递（活跃守卫失效）"
        if proactive.previous_delivered_at is not None:
            interval = effective_interval_minutes(
                PolicySnapshot(
                    intimacy=ctx.state.intimacy
                    if ctx.state.intimacy is not None
                    else 0.3,
                    attempt_count=max(proactive.episode_attempts - 1, 0),
                    selected_goal_type=proactive.intention,
                ),
                settings,
            )
            gap_minutes = (
                delivered_at - proactive.previous_delivered_at
            ).total_seconds() / 60
            if gap_minutes < interval:
                return f"距上次主动投递 {gap_minutes:.0f} 分钟 < 冷却 {interval:.0f} 分钟"
        if proactive.episode_attempts > settings.autonomy_max_attempts_per_episode:
            return f"episode 投递 {proactive.episode_attempts} 次超过上限"
        return None


class LifeLoopRunCompletenessRule(EvaluationRule):
    """LIFE-006：done 的用户周期必含 decision 步骤；aborted 必有原因。"""

    code = IssueCode.LIFE_LOOP_RUN_INCOMPLETE
    dimension = EvaluationDimension.AUTONOMY
    subjects = ("life_loop",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        loop = ctx.life_loop
        if loop is None:
            return None
        for run in loop.runs:
            if run.kind != "autonomy":
                continue
            if run.status == "done" and "decision" not in run.step_names:
                return build_issue(
                    self.code,
                    evidence_quote=f"run {run.run_id} done 缺 decision 步骤",
                )
            if run.status == "aborted" and not run.aborted_with_reason:
                return build_issue(
                    self.code,
                    evidence_quote=f"run {run.run_id} aborted 无原因记录",
                )
        return None


class LifeLoopBudgetComplianceRule(EvaluationRule):
    """LIFE-006：degraded 期间禁止 LLM 调用；日总量不超配额。"""

    code = IssueCode.LIFE_LOOP_BUDGET_OVERRUN
    dimension = EvaluationDimension.AUTONOMY
    subjects = ("life_loop",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        loop = ctx.life_loop
        if loop is None:
            return None
        for run in loop.runs:
            if run.budget_degraded and run.llm_call_count > 0:
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"run {run.run_id} 熔断降级期间仍有 "
                        f"{run.llm_call_count} 次 LLM 调用"
                    ),
                )
        if loop.day_llm_call_limit > 0 and loop.day_llm_calls > loop.day_llm_call_limit:
            return build_issue(
                self.code,
                evidence_quote=(
                    f"日 LLM 调用 {loop.day_llm_calls} 超配额 {loop.day_llm_call_limit}"
                ),
            )
        return None


class TriggerLifecycleRule(EvaluationRule):
    """LIFE-006：trigger 滞留 due/fired 超时或 cancelled 无 reason = 孤儿。"""

    code = IssueCode.TRIGGER_REGISTRY_ORPHAN
    dimension = EvaluationDimension.AUTONOMY
    subjects = ("life_loop",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        loop = ctx.life_loop
        if loop is None:
            return None
        for trigger in loop.triggers:
            if trigger.stale:
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"{trigger.trigger_key} 滞留 {trigger.status} 超时未终态"
                    ),
                )
            if trigger.cancelled_without_reason:
                return build_issue(
                    self.code,
                    evidence_quote=f"{trigger.trigger_key} cancelled 无 reason 留痕",
                )
        return None


class TriggerProvenanceRule(EvaluationRule):
    """LIFE-006：delivered 的 proactive 必有 PROACTIVE_AUTONOMY 决策行溯源。"""

    code = IssueCode.AUTONOMY_TRIGGER_UNPROVENANCED
    dimension = EvaluationDimension.AUTONOMY
    subjects = ("life_loop",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        loop = ctx.life_loop
        if loop is None:
            return None
        for proactive in loop.delivered_proactive:
            if not proactive.provenanced:
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"proactive {proactive.action_id} 投递无触发溯源记录"
                    ),
                )
        return None


class StormAndRepeatRule(EvaluationRule):
    """LIFE-006：同用户日投递超风暴阈值（复用 AUTONOMY_REDUNDANT 码）。"""

    code = IssueCode.AUTONOMY_REDUNDANT
    dimension = EvaluationDimension.AUTONOMY
    subjects = ("life_loop",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        loop = ctx.life_loop
        if loop is None:
            return None
        delivered = len(loop.delivered_proactive)
        limit = get_settings().life_loop_storm_daily_limit
        if delivered > limit:
            return build_issue(
                self.code,
                evidence_quote=f"日投递 {delivered} 次超过风暴阈值 {limit}",
            )
        return None


TIMING_VIOLATION = TimingViolationRule()
RUN_COMPLETENESS = LifeLoopRunCompletenessRule()
BUDGET_COMPLIANCE = LifeLoopBudgetComplianceRule()
TRIGGER_LIFECYCLE = TriggerLifecycleRule()
TRIGGER_PROVENANCE = TriggerProvenanceRule()
STORM_AND_REPEAT = StormAndRepeatRule()

RULES = [
    TIMING_VIOLATION,
    RUN_COMPLETENESS,
    BUDGET_COMPLIANCE,
    TRIGGER_LIFECYCLE,
    TRIGGER_PROVENANCE,
    STORM_AND_REPEAT,
]
