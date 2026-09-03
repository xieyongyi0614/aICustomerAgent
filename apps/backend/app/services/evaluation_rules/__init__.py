"""V7.5 评估规则引擎（rule-engine.md）。

确定性判定层：纯函数、零 LLM、每轮必跑、逐条异常隔离；
主体过滤在注册表（subjects），维度开关与扣分推导走 settings。
各维规则模块导出规则对象列表，由本包汇编 RULES。
"""

import logging

from app.core.settings import Settings, get_settings
from app.models.evaluation import (
    DimensionScore,
    EvaluationDimension,
    Issue,
    IssueCode,
    IssueSeverity,
    clamp_score,
)
from app.services.evaluation_context import EvaluationContext

logger = logging.getLogger(__name__)


class EvaluationRule:
    """规则基类：一条规则对应一个 IssueCode；子类实现 evaluate(ctx)。"""

    code: IssueCode
    dimension: EvaluationDimension
    subjects: tuple[str, ...] = ("turn", "proactive_action")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        raise NotImplementedError


def rule_active(rule: EvaluationRule, context: EvaluationContext, settings: Settings) -> bool:
    if context.subject not in rule.subjects:
        return False
    return bool(getattr(settings, f"evaluation_{rule.dimension.value}_enabled", True))


def run_rules(context: EvaluationContext, settings: Settings | None = None) -> list[Issue]:
    settings = settings or get_settings()
    issues: list[Issue] = []
    for rule in RULES:
        if not rule_active(rule, context, settings):
            continue
        try:
            issue = rule.evaluate(context)
        except Exception:
            logger.exception("评估规则异常，跳过：%s", getattr(rule, "code", rule))
            continue
        if issue is not None:
            issues.append(issue)
    return issues


def eligible_dimensions(
    subject: str, settings: Settings | None = None
) -> list[EvaluationDimension]:
    settings = settings or get_settings()
    seen: list[EvaluationDimension] = []
    for rule in RULES:
        if subject not in rule.subjects:
            continue
        if not _dimension_enabled(rule.dimension, settings):
            continue
        if rule.dimension not in seen:
            seen.append(rule.dimension)
    return seen


def _dimension_enabled(dimension: EvaluationDimension, settings: Settings) -> bool:
    return bool(getattr(settings, f"evaluation_{dimension.value}_enabled", True))


def penalty_for(severity: IssueSeverity, settings: Settings) -> float:
    return {
        IssueSeverity.CRITICAL: settings.evaluation_penalty_critical,
        IssueSeverity.WARNING: settings.evaluation_penalty_warning,
        IssueSeverity.INFO: settings.evaluation_penalty_info,
    }[severity]


def compute_rule_scores(
    issues: list[Issue],
    eligible: list[EvaluationDimension],
    settings: Settings,
) -> dict[EvaluationDimension, float]:
    """维度 rule_score = clamp(1 - Σ扣分)；无命中的合格维度 = 1.0；空规则集维度缺席。"""
    penalties: dict[EvaluationDimension, float] = {}
    for issue in issues:
        penalties[issue.dimension] = penalties.get(issue.dimension, 0.0) + penalty_for(
            issue.severity, settings
        )
    return {
        dimension: clamp_score(1.0 - penalties.get(dimension, 0.0))
        for dimension in eligible
    }


def to_dimension_scores(
    rule_scores: dict[EvaluationDimension, float],
) -> dict[EvaluationDimension, DimensionScore]:
    return {
        dimension: DimensionScore(dimension=dimension, score=score, rule_score=score)
        for dimension, score in rule_scores.items()
    }


from app.services.evaluation_rules import action as _action  # noqa: E402
from app.services.evaluation_rules import autonomy as _autonomy  # noqa: E402
from app.services.evaluation_rules import behavior as _behavior  # noqa: E402
from app.services.evaluation_rules import emotion as _emotion  # noqa: E402
from app.services.evaluation_rules import memory as _memory  # noqa: E402
from app.services.evaluation_rules import persona as _persona  # noqa: E402
from app.services.evaluation_rules import relationship as _relationship  # noqa: E402

RULES: list[EvaluationRule] = [
    *_behavior.RULES,
    *_persona.RULES,
    *_emotion.RULES,
    *_memory.RULES,
    *_autonomy.RULES,
    *_relationship.RULES,
    *_action.RULES,
]

__all__ = [
    "EvaluationRule",
    "RULES",
    "compute_rule_scores",
    "eligible_dimensions",
    "penalty_for",
    "rule_active",
    "run_rules",
    "to_dimension_scores",
]
