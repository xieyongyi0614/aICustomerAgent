"""V7.5 Behavior 维规则集（behavior-evaluation.md）：预算 / 接触 / 单调 / 表达浓度。

接近 100% 规则可判，无 LLM；观测口径复用 V6.5 observe_budget。
"""

from app.core.settings import get_settings
from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services import behavior_engine
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule, lexicons

_CONTACT_ORDER = ("none", "light", "moderate")


class BudgetExceededRule(EvaluationRule):
    code = IssueCode.BEHAVIOR_BUDGET_EXCEEDED
    dimension = EvaluationDimension.BEHAVIOR

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.behavior is None:
            return None
        if ctx.behavior.observed_action_count <= ctx.behavior.max_action_desc:
            return None
        actions = behavior_engine.ACTION_DESC_PATTERN.findall(ctx.reply)
        return build_issue(self.code, evidence_quote="".join(actions)[:60])


class ContactViolationRule(EvaluationRule):
    code = IssueCode.BEHAVIOR_CONTACT_VIOLATION
    dimension = EvaluationDimension.BEHAVIOR

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.behavior is None:
            return None
        observed = _CONTACT_ORDER.index(ctx.behavior.observed_contact_level)
        allowed = _CONTACT_ORDER.index(ctx.behavior.physical_contact)
        if observed <= allowed:
            return None
        word = _matched_contact_word(ctx.reply)
        return build_issue(
            self.code,
            evidence_quote=f"{word}（允许 {ctx.behavior.physical_contact}）",
        )


class ActionMonotonyRule(EvaluationRule):
    code = IssueCode.BEHAVIOR_ACTION_MONOTONY
    dimension = EvaluationDimension.BEHAVIOR

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        settings = get_settings()
        if not ctx.behavior_history:
            return None
        window = ctx.behavior_history[-settings.evaluation_behavior_monotony_window :]
        if not window:
            return None
        current = window[-1]
        for category in set(current):
            total = sum(turn.count(category) for turn in window)
            if total >= settings.evaluation_behavior_monotony_threshold:
                sequence = [c for turn in window for c in turn]
                return build_issue(
                    self.code,
                    evidence_quote=f"{category}×{total}：{'、'.join(sequence)[:50]}",
                )
        return None


class ExpressionMismatchRule(EvaluationRule):
    code = IssueCode.BEHAVIOR_EXPRESSION_MISMATCH
    dimension = EvaluationDimension.BEHAVIOR

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        settings = get_settings()
        if ctx.behavior is None:
            return None
        density = lexicons.expression_density(ctx.reply)
        level = ctx.behavior.emotion_expression
        if level == "subtle" and density > settings.evaluation_expression_density_high:
            return build_issue(self.code, evidence_quote=f"subtle 档密度 {density:.2f}")
        if level == "rich" and density < settings.evaluation_expression_density_low:
            return build_issue(self.code, evidence_quote=f"rich 档密度 {density:.2f}")
        return None


def _matched_contact_word(reply: str) -> str:
    for word in behavior_engine.MODERATE_CONTACT_WORDS + behavior_engine.LIGHT_CONTACT_WORDS:
        if word in reply:
            return word
    return ""


BUDGET_EXCEEDED = BudgetExceededRule()
CONTACT_VIOLATION = ContactViolationRule()
ACTION_MONOTONY = ActionMonotonyRule()
EXPRESSION_MISMATCH = ExpressionMismatchRule()

RULES = [BUDGET_EXCEEDED, CONTACT_VIOLATION, ACTION_MONOTONY, EXPRESSION_MISMATCH]
