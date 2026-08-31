"""V8.5 Relationship 评估护栏单测（evolution-engine.md §7）。"""

from dataclasses import replace

from app.models.evaluation import IssueCode, IssueSeverity
from app.models.relationship import RelationshipDelta, RelationshipEvent
from app.services.evaluation_context import EvaluationContext, RelationshipSlice
from app.services.evaluation_rules import relationship as rel_rules
from app.services.evaluation_rules.relationship import (
    LEDGER_RECONCILIATION,
    RATE_COMPLIANCE,
    RELATIONSHIP_JUMP,
    SIGNAL_ACCOUNTING,
)
from datetime import datetime

NOW = datetime(2026, 8, 31, 12, 0, 0)

DIMS = ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")


def _dims(**overrides) -> dict:
    values = {
        "intimacy": 0.30, "trust": 0.35, "familiarity": 0.30,
        "respect": 0.60, "comfort": 0.60, "tension": 0.0,
    }
    values.update(overrides)
    return values


def _ctx(relationship: RelationshipSlice) -> EvaluationContext:
    return EvaluationContext(
        subject="turn", subject_id="t1", session_id="s1", user_id="u1",
        relationship=relationship,
    )


def _slice(before=None, after=None, events=None, comfort_drift=0.0, signal_present=True):
    return RelationshipSlice(
        before=before or _dims(),
        after=after or _dims(),
        events=events or [],
        comfort_drift=comfort_drift,
        signal_present=signal_present,
    )


def _event(impact: RelationshipDelta, cause="", source="conversation") -> RelationshipEvent:
    return RelationshipEvent(
        user_id="u1", session_id="s1", type="praise", magnitude="normal",
        impact=impact, confidence=0.5, source=source, cause=cause, created_at=NOW,
    )


def test_no_slice_no_issue():
    assert RELATIONSHIP_JUMP.evaluate(_ctx(None)) is None


def test_jump_rule_passes_within_limit():
    after = _dims(trust=0.35 + 0.15)
    issue = RELATIONSHIP_JUMP.evaluate(_ctx(_slice(after=after)))
    assert issue is None


def test_jump_rule_fails_on_trust_jump():
    after = _dims(trust=1.0)
    issue = RELATIONSHIP_JUMP.evaluate(_ctx(_slice(after=after)))
    assert issue is not None
    assert issue.code is IssueCode.RELATIONSHIP_JUMP
    assert issue.severity is IssueSeverity.CRITICAL
    assert issue.dimension.value == "relationship"


def test_reconciliation_passes_when_ledger_explains_change():
    events = [_event(RelationshipDelta(trust=0.02))]
    after = _dims(trust=0.37)
    issue = LEDGER_RECONCILIATION.evaluate(_ctx(_slice(after=after, events=events)))
    assert issue is None


def test_reconciliation_fails_on_uncaused_change():
    events = [_event(RelationshipDelta(trust=0.02))]
    after = _dims(trust=0.50)
    issue = LEDGER_RECONCILIATION.evaluate(_ctx(_slice(after=after, events=events)))
    assert issue is not None
    assert issue.code is IssueCode.RELATIONSHIP_UNCAUSED_CHANGE


def test_reconciliation_tolerates_comfort_drift():
    events = [_event(RelationshipDelta(trust=0.02))]
    after = _dims(trust=0.37, comfort=0.605)
    issue = LEDGER_RECONCILIATION.evaluate(
        _ctx(_slice(after=after, events=events, comfort_drift=0.005))
    )
    assert issue is None


def test_rate_rule_warns_on_day_overflow():
    rel = _slice()
    rel.day_positive = _dims(trust=0.35)
    issue = RATE_COMPLIANCE.evaluate(_ctx(rel))
    assert issue is not None
    assert issue.code is IssueCode.RELATIONSHIP_RATE_VIOLATION
    assert issue.severity is IssueSeverity.WARNING


def test_signal_accounting_fails_on_causeless_event_without_signal():
    events = [_event(RelationshipDelta(trust=0.02), cause="")]
    issue = SIGNAL_ACCOUNTING.evaluate(_ctx(_slice(events=events, signal_present=False)))
    assert issue is not None
    assert issue.code is IssueCode.RELATIONSHIP_UNCAUSED_CHANGE


def test_signal_accounting_passes_with_signal_or_cause():
    events = [
        _event(RelationshipDelta(trust=0.02), cause="被夸"),
        _event(RelationshipDelta(trust=0.01), cause="", source="system"),
    ]
    assert SIGNAL_ACCOUNTING.evaluate(_ctx(_slice(events=events))) is None
    events = [_event(RelationshipDelta(trust=0.02), cause="")]
    assert SIGNAL_ACCOUNTING.evaluate(_ctx(_slice(events=events, signal_present=True))) is None


def test_rules_registered():
    codes = [rule.code for rule in rel_rules.RULES]
    assert IssueCode.RELATIONSHIP_JUMP in codes
    assert len(rel_rules.RULES) == 4