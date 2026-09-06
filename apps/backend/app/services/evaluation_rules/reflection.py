"""Phase 2 Reflection 维规则集（REF-006）：Insight 证据引用 + 注入新鲜度 + 校准复核。

纯函数、逐条异常隔离；subjects 含 offline_batch（离线场景集复用）。
reflections 切片缺席（None）时全部规则静默跳过——向后兼容既有 turn 评估。
"""

from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule


class NoEvidenceLinkRule(EvaluationRule):
    """active Insight 无任何 evidence_links → CRITICAL（无证据不出 Insight 的复核闸）。"""

    code = IssueCode.REFLECTION_NO_EVIDENCE_LINK
    dimension = EvaluationDimension.REFLECTION
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.reflection is None:
            return None
        for insight in ctx.reflection.insights:
            if insight.status != "active" or insight.evidence_count > 0:
                continue
            return build_issue(
                self.code, evidence_quote=f"insight={insight.id}：{insight.statement[:40]}"
            )
        return None


class StaleInjectedRule(EvaluationRule):
    """prompt insight 段出现非 active Insight → CRITICAL（REF-007 即时退出的复核闸）。"""

    code = IssueCode.REFLECTION_STALE_INJECTED
    dimension = EvaluationDimension.REFLECTION
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.reflection is None:
            return None
        by_id = {insight.id: insight for insight in ctx.reflection.insights}
        for insight_id in ctx.reflection.injected_insight_ids:
            insight = by_id.get(insight_id)
            if insight is not None and insight.status != "active":
                return build_issue(
                    self.code,
                    evidence_quote=f"insight={insight_id} status={insight.status}",
                )
        return None


class ConfidenceOverCalibratedRule(EvaluationRule):
    """confidence 高于按证据数折算上限 → WARNING（校准被绕过的信号）。"""

    code = IssueCode.REFLECTION_CONFIDENCE_OVER_CALIBRATED
    dimension = EvaluationDimension.REFLECTION
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.reflection is None:
            return None
        from app.services.reflection.reflector import confidence_ceiling

        for insight in ctx.reflection.insights:
            if insight.status != "active" or insight.evidence_count <= 0:
                continue
            ceiling = confidence_ceiling(insight.evidence_count)
            if insight.confidence > ceiling:
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"insight={insight.id} confidence={insight.confidence:.2f}"
                        f" > ceiling={ceiling:.2f}（evidence_count={insight.evidence_count}）"
                    ),
                )
        return None


NO_EVIDENCE_LINK = NoEvidenceLinkRule()
STALE_INJECTED = StaleInjectedRule()
CONFIDENCE_OVER_CALIBRATED = ConfidenceOverCalibratedRule()

RULES = [NO_EVIDENCE_LINK, STALE_INJECTED, CONFIDENCE_OVER_CALIBRATED]
