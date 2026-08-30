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
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule


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


TIMING_VIOLATION = TimingViolationRule()

RULES = [TIMING_VIOLATION]
