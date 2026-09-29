"""V7-010：scheduled_followup（Memory Trigger，trigger-model.md §4 / Scenario 4）。"""

from datetime import datetime, timedelta

from app.services import trigger_evaluator
from app.services.autonomy_policy import PolicySnapshot, evaluate

NOW = datetime(2026, 8, 30, 14, 0)
CONFIG = __import__("app.core.settings", fromlist=["get_settings"]).get_settings()


def test_find_followup_event_keywords():
    assert trigger_evaluator.find_followup_event("明天有面试") == "面试"
    assert trigger_evaluator.find_followup_event("记得今天下午的会议") == "会议"
    assert trigger_evaluator.find_followup_event("今天天气不错") is None


def test_register_and_poll_due(monkeypatch):
    trigger_evaluator._followup_registry.clear()
    due = NOW + timedelta(hours=2)
    trigger_evaluator.register_followup("u1", due, "面试近况跟进")

    assert trigger_evaluator.poll_due_followup("u1", NOW) is None
    signal = trigger_evaluator.poll_due_followup("u1", due + timedelta(minutes=1))
    assert signal is not None
    assert signal.type == "scheduled_followup"
    assert signal.dedupe_key.startswith("followup:")
    assert signal.context["summary"] == "面试近况跟进"
    assert trigger_evaluator.poll_due_followup("u1", due + timedelta(minutes=2)) is None
    trigger_evaluator._followup_registry.clear()


def test_poll_isolated_per_user():
    trigger_evaluator._followup_registry.clear()
    trigger_evaluator.register_followup("u1", NOW, "面试")
    assert trigger_evaluator.poll_due_followup("u2", NOW + timedelta(hours=1)) is None
    trigger_evaluator._followup_registry.clear()


def test_followup_signal_acts_when_policy_passes():
    trigger_evaluator._followup_registry.clear()
    due = NOW
    trigger_evaluator.register_followup("u1", due, "面试近况跟进")
    signal = trigger_evaluator.poll_due_followup("u1", due)
    verdict = evaluate(
        signal,
        PolicySnapshot(intimacy=0.62, selected_goal_type="user_care"),
        CONFIG,
        NOW,
    )
    assert verdict.decision == "act"
    assert verdict.intention == "check_in"
    trigger_evaluator._followup_registry.clear()


def test_followup_not_exempt_from_quiet_hours():
    """设计要求：MVP followup 静音不豁免（quiet-hours.md §4）。"""
    trigger_evaluator._followup_registry.clear()
    due = NOW.replace(hour=23, minute=30)
    trigger_evaluator.register_followup("u1", due, "面试近况跟进")
    signal = trigger_evaluator.poll_due_followup("u1", due)
    verdict = evaluate(
        signal,
        PolicySnapshot(intimacy=0.62, selected_goal_type="user_care"),
        CONFIG,
        due,
    )
    assert verdict.decision == "ignore"
    assert verdict.reason == "静音时段"
    trigger_evaluator._followup_registry.clear()
