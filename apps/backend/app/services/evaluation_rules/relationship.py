"""V8.5 Relationship 评估护栏（evolution-engine.md §7）+ REL-004 叙事审计规则。

确定性规则，零 LLM；叙事两条 subjects 含 offline_batch（离线场景集复用），
narrative 切片缺席（None）时静默跳过——向后兼容既有 turn 评估。
"""

import json

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
_NARRATIVE_PREFIX = "narrative:"
_NARRATIVE_LEDGER_TABLES = ("relationship_events", "relationship_milestones")


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


class NarrativeFactProvenanceRule(EvaluationRule):
    """relationship_fact/milestone_event 记忆必须有账本 source_ref（E-REL-01）。"""

    code = IssueCode.RELATIONSHIP_NARRATIVE_ORPHAN
    dimension = EvaluationDimension.RELATIONSHIP
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.narrative is None:
            return None
        for fact in ctx.narrative.facts:
            ref = fact.source_ref or {}
            if (
                ref.get("table") in _NARRATIVE_LEDGER_TABLES
                and ref.get("id")
            ):
                continue
            return build_issue(
                self.code,
                evidence_quote=(
                    f"memory={fact.id} type={fact.type} 缺少账本 source_ref"
                ),
            )
        return None


class NarrativeMilestoneProvenanceRule(EvaluationRule):
    """叙事里程碑必须白名单内且 meta 溯源到存在行（E-REL-04）。"""

    code = IssueCode.RELATIONSHIP_MILESTONE_UNPROVENANCED
    dimension = EvaluationDimension.RELATIONSHIP
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.narrative is None:
            return None
        whitelist = _narrative_whitelist_keys()
        for milestone in ctx.narrative.narrative_milestones:
            if not milestone.milestone_key.startswith(_NARRATIVE_PREFIX):
                continue
            meta = milestone.meta or {}
            if meta.get("source") != "insight" or not meta.get("insight_id"):
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"milestone={milestone.milestone_key} 缺少 insight 溯源"
                    ),
                )
            if meta.get("insight_id") not in ctx.narrative.insight_ids:
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"milestone={milestone.milestone_key} "
                        f"悬空 insight_id={meta.get('insight_id')}"
                    ),
                )
            if milestone.milestone_key not in whitelist:
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"milestone={milestone.milestone_key} 白名单外"
                    ),
                )
        return None


def _narrative_whitelist_keys() -> set[str]:
    try:
        raw = get_settings().relationship_narrative_whitelist_json
        table = json.loads(raw)
        return set(table) if isinstance(table, dict) else set()
    except Exception:
        return set()


RELATIONSHIP_JUMP = RelationshipJumpRule()
LEDGER_RECONCILIATION = LedgerReconciliationRule()
RATE_COMPLIANCE = RateComplianceRule()
SIGNAL_ACCOUNTING = SignalAccountingRule()
NARRATIVE_FACT_PROVENANCE = NarrativeFactProvenanceRule()
NARRATIVE_MILESTONE_PROVENANCE = NarrativeMilestoneProvenanceRule()

RULES = [
    RELATIONSHIP_JUMP,
    LEDGER_RECONCILIATION,
    RATE_COMPLIANCE,
    SIGNAL_ACCOUNTING,
    NARRATIVE_FACT_PROVENANCE,
    NARRATIVE_MILESTONE_PROVENANCE,
]