"""V8.5 Relationship 评估护栏（evolution-engine.md §7）：四条确定性规则，零 LLM。"""

from app.core.constants import RELATIONSHIP_DIMENSIONS_V85
from app.core.settings import get_settings
from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule

_TOLERANCE = 1e-6
_SYSTEM_SOURCE = "system"


class RelationshipJumpRule(EvaluationRule):
    """任意维单轮 |Δ| ≤ rel_max_turn_delta（实际生效值，限速兜底验证）。"""

    code = IssueCode.RELATIONSHIP_JUMP
    dimension = EvaluationDimension.RELATIONSHIP
    subjects = ("turn",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        rel = ctx.relationship
        if rel is None or rel.after is None or rel.before is None:
            return None
        settings = get_settings()
        for dim in RELATIONSHIP_DIMENSIONS_V85:
            delta = abs(rel.after[dim] - rel.before[dim])
            if delta > settings.rel_max_turn_delta + _TOLERANCE:
                return build_issue(
                    self.code,
                    evidence_quote=f"{dim} 单轮变化 {delta:.3f} > "
                    f"{settings.rel_max_turn_delta}",
                )
        return None


class LedgerReconciliationRule(EvaluationRule):
    """状态变化 − 账本 impact 之和 − comfort 漂移 = 漂移容差内（无因不变量）。"""

    code = IssueCode.RELATIONSHIP_UNCAUSED_CHANGE
    dimension = EvaluationDimension.RELATIONSHIP
    subjects = ("turn",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        rel = ctx.relationship
        if rel is None or rel.after is None or rel.before is None:
            return None
        ledger: dict[str, float] = {dim: 0.0 for dim in RELATIONSHIP_DIMENSIONS_V85}
        for event in rel.events:
            for dim in RELATIONSHIP_DIMENSIONS_V85:
                ledger[dim] += float(getattr(event.impact, dim, 0.0))
        for dim in RELATIONSHIP_DIMENSIONS_V85:
            observed = rel.after[dim] - rel.before[dim]
            explained = ledger[dim]
            tolerance = _TOLERANCE
            if dim == "comfort":
                tolerance = max(_TOLERANCE, abs(rel.comfort_drift) + _TOLERANCE)
            if abs(observed - explained) > tolerance:
                return build_issue(
                    self.code,
                    evidence_quote=f"{dim} 变化 {observed:.4f} vs 账本 "
                    f"{explained:.4f}（容差 {tolerance:.4f}）",
                )
        return None


class RateComplianceRule(EvaluationRule):
    """当日每维累计 ≤ rel_max_day_delta（限速兜底验证，防御未来代码绕过）。"""

    code = IssueCode.RELATIONSHIP_RATE_VIOLATION
    dimension = EvaluationDimension.RELATIONSHIP
    subjects = ("turn",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        rel = ctx.relationship
        if rel is None:
            return None
        settings = get_settings()
        for label in ("day_positive", "day_negative"):
            totals = getattr(rel, label) or {}
            for dim, value in totals.items():
                if abs(value) > settings.rel_max_day_delta + _TOLERANCE:
                    return build_issue(
                        self.code,
                        evidence_quote=f"{label}.{dim} 当日累计 {value:.3f} > "
                        f"{settings.rel_max_day_delta}",
                    )
        return None


class SignalAccountingRule(EvaluationRule):
    """每条 conversation 账本行 cause 能对应信号 / LLM 事件（无因变化检测）。"""

    code = IssueCode.RELATIONSHIP_UNCAUSED_CHANGE
    dimension = EvaluationDimension.RELATIONSHIP
    subjects = ("turn",)

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        rel = ctx.relationship
        if rel is None:
            return None
        for event in rel.events:
            if getattr(event, "source", "conversation") == _SYSTEM_SOURCE:
                continue
            cause = (getattr(event, "cause", "") or "").strip()
            if cause:
                continue
            if rel.signal_present:
                continue
            return build_issue(
                self.code,
                evidence_quote=f"事件 {getattr(event, 'type', '?')} 无 cause 且无信号",
            )
        return None


RELATIONSHIP_JUMP = RelationshipJumpRule()
LEDGER_RECONCILIATION = LedgerReconciliationRule()
RATE_COMPLIANCE = RateComplianceRule()
SIGNAL_ACCOUNTING = SignalAccountingRule()

RULES = [RELATIONSHIP_JUMP, LEDGER_RECONCILIATION, RATE_COMPLIANCE, SIGNAL_ACCOUNTING]