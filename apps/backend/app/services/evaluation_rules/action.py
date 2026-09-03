"""V9 Action 评估护栏（tool-integration.md §5）：三条确定性规则，零 LLM。

ActionOverclaimRule / ActionUnreportedFailureRule / ActionPlanMismatchRule。
上下文切片缺失（action=None）时规则全部跳过。
"""

from app.character.asuna.action import COMPLETION_CLAIM_PATTERNS
from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule


def _contains_claim(reply: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in reply for pattern in patterns)


class ActionOverclaimRule(EvaluationRule):
    """完成时宣称 + 无 succeeded 记录 → action_overclaim（时序契约审计兜底）。"""

    code = IssueCode.ACTION_OVERCLAIM
    dimension = EvaluationDimension.ACTION
    subjects = ("turn",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.action is None:
            return None
        if not _contains_claim(ctx.reply, COMPLETION_CLAIM_PATTERNS):
            return None
        for action_type in ("create_reminder", "cancel_reminder", "remember_fact", "create_object"):
            if ctx.action.has_succeeded(action_type):
                return None
        return build_issue(
            self.code,
            evidence_quote="回复含完成时宣称但没有对应 succeeded ActionRecord",
        )


class ActionUnreportedFailureRule(EvaluationRule):
    """存在近期 failed 且未补救的重要委托行动 → action_failed_unreported（info 提示未闭环）。"""

    code = IssueCode.ACTION_FAILED_UNREPORTED
    dimension = EvaluationDimension.ACTION
    subjects = ("turn",)

    REPAIRABLE = ("create_reminder", "cancel_reminder", "remember_fact", "create_object")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.action is None:
            return None
        failed_types = [
            r.get("action_type")
            for r in ctx.action.records
            if r.get("status") == "failed"
            and r.get("action_type") in self.REPAIRABLE
            and not r.get("gate_reason")
        ]
        if not failed_types:
            return None
        remedial_types = {
            r.get("action_type")
            for r in ctx.action.records
            if r.get("status") in ("succeeded", "executing", "planned", "created")
        }
        unreported = [
            t
            for t in failed_types
            if t in self.REPAIRABLE and t not in remedial_types
        ]
        if not unreported:
            return None
        return build_issue(
            self.code,
            evidence_quote=f"近期失败未补救: {', '.join(unreported)}",
        )


class ActionPlanMismatchRule(EvaluationRule):
    """检出意图与回复语义无关或闸门频繁否决 → action_plan_mismatch。"""

    code = IssueCode.ACTION_PLAN_MISMATCH
    dimension = EvaluationDimension.ACTION
    subjects = ("turn",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.action is None:
            return None
        cancelled = [
            r
            for r in ctx.action.records
            if r.get("status") == "cancelled" and r.get("gate_reason")
        ]
        if len(cancelled) >= 3:
            return build_issue(
                self.code,
                evidence_quote="闸门频繁否决同型意图（词表误报信号）",
            )
        return None


RULES: list[EvaluationRule] = [
    ActionOverclaimRule(),
    ActionUnreportedFailureRule(),
    ActionPlanMismatchRule(),
]
