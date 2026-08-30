import pytest

from app.core.settings import get_settings
from app.models.evaluation import EvaluationDimension, IssueCode
from app.services.evaluation_context import (
    BehaviorSlice,
    EvaluationContext,
)
from app.services.evaluation_rules import behavior as behavior_rules
from app.services.evaluation_rules.lexicons import classify_actions, expression_density


def make_ctx(
    behavior: BehaviorSlice | None = None,
    history: list[list[str]] | None = None,
    reply: str = "好的。",
) -> EvaluationContext:
    return EvaluationContext(
        subject="turn",
        subject_id="1",
        session_id="c",
        user_id="u",
        reply=reply,
        behavior=behavior,
        behavior_history=history or [],
    )


def make_behavior(
    max_action_desc: int = 1,
    physical_contact: str = "none",
    emotion_expression: str = "natural",
    observed_action_count: int = 0,
    observed_contact_level: str = "none",
) -> BehaviorSlice:
    return BehaviorSlice(
        max_action_desc=max_action_desc,
        physical_contact=physical_contact,
        emotion_expression=emotion_expression,
        observed_action_count=observed_action_count,
        observed_contact_level=observed_contact_level,
    )


def test_budget_exceeded_hits_and_boundary():
    rule = behavior_rules.BUDGET_EXCEEDED
    hit = rule.evaluate(
        make_ctx(
            behavior=make_behavior(max_action_desc=1, observed_action_count=2),
            reply="*摸头* *握手*",
        )
    )
    assert hit is not None and hit.code == IssueCode.BEHAVIOR_BUDGET_EXCEEDED
    assert hit.severity == "warning"
    assert hit.evidence_quote

    boundary = rule.evaluate(
        make_ctx(behavior=make_behavior(max_action_desc=1, observed_action_count=1))
    )
    assert boundary is None


def test_budget_exceeded_tolerates_missing_behavior():
    assert behavior_rules.BUDGET_EXCEEDED.evaluate(make_ctx()) is None


def test_contact_violation_levels():
    rule = behavior_rules.CONTACT_VIOLATION
    hit = rule.evaluate(
        make_ctx(
            behavior=make_behavior(physical_contact="none", observed_contact_level="light"),
            reply="*递上一杯热茶* 晚安",
        )
    )
    assert hit is not None
    assert hit.code == IssueCode.BEHAVIOR_CONTACT_VIOLATION
    assert "递上" in hit.evidence_quote

    allowed = rule.evaluate(
        make_ctx(
            behavior=make_behavior(physical_contact="light", observed_contact_level="light"),
            reply="*递上一杯热茶* 晚安",
        )
    )
    assert allowed is None


def test_action_monotony_window():
    rule = behavior_rules.ACTION_MONOTONY
    hit = rule.evaluate(
        make_ctx(history=[["contact"], ["contact"], ["expression"], ["contact"]])
    )
    assert hit is not None
    assert hit.code == IssueCode.BEHAVIOR_ACTION_MONOTONY
    assert "contact" in hit.evidence_quote

    below = rule.evaluate(make_ctx(history=[["contact"], ["expression"], ["contact"]]))
    assert below is None

    stale = rule.evaluate(
        make_ctx(history=[["contact"], ["contact"], ["contact"], ["expression"]])
    )
    assert stale is None

    empty = rule.evaluate(make_ctx(history=[]))
    assert empty is None


def test_expression_mismatch_density():
    rule = behavior_rules.EXPRESSION_MISMATCH
    rich_reply = "太好了！我超开心！哈哈！这简直太棒啦！"
    subtle_reply = "嗯，知道了。"

    subtle_hit = rule.evaluate(
        make_ctx(
            behavior=make_behavior(emotion_expression="subtle"),
            reply=rich_reply,
        )
    )
    assert subtle_hit is not None
    assert subtle_hit.code == IssueCode.BEHAVIOR_EXPRESSION_MISMATCH
    assert subtle_hit.severity == "info"

    rich_hit = rule.evaluate(
        make_ctx(
            behavior=make_behavior(emotion_expression="rich"),
            reply=subtle_reply,
        )
    )
    assert rich_hit is not None

    natural = rule.evaluate(
        make_ctx(
            behavior=make_behavior(emotion_expression="natural"),
            reply=rich_reply,
        )
    )
    assert natural is None


def test_expression_density_and_classify():
    assert expression_density("") == 0.0
    assert expression_density("太好了，好开心！") > 0
    assert classify_actions("*摸了摸头*，然后*转身离开*") == ["contact", "movement"]
    assert classify_actions("*做了一个无法归类的动作*") == []
    assert classify_actions("") == []


def test_rules_registered_in_engine():
    from app.services import evaluation_rules

    codes = {rule.code for rule in evaluation_rules.RULES}
    assert {
        IssueCode.BEHAVIOR_BUDGET_EXCEEDED,
        IssueCode.BEHAVIOR_CONTACT_VIOLATION,
        IssueCode.BEHAVIOR_ACTION_MONOTONY,
        IssueCode.BEHAVIOR_EXPRESSION_MISMATCH,
    } <= codes
    dimensions = {rule.dimension for rule in evaluation_rules.RULES}
    assert EvaluationDimension.BEHAVIOR in dimensions


def test_monotony_settings_respected(monkeypatch):
    monkeypatch.setenv("EVALUATION_BEHAVIOR_MONOTONY_THRESHOLD", "5")
    get_settings.cache_clear()
    try:
        rule = behavior_rules.ACTION_MONOTONY
        hit = rule.evaluate(
            make_ctx(history=[["contact"], ["contact"], ["contact"]])
        )
        assert hit is None
    finally:
        get_settings.cache_clear()
