"""V7-003：AutonomyPolicy 八步裁决流水（testing.md Case 4~7 + 修正表）。"""

from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.autonomy import TriggerSignal
from app.engines.autonomy import (
    PolicySnapshot,
    effective_interval_minutes,
    evaluate,
    in_quiet_hours,
)

NOW = datetime(2026, 8, 30, 14, 0)
CONFIG = get_settings()


def _signal(**overrides) -> TriggerSignal:
    payload = {
        "type": "conversation_inactivity",
        "user_id": "u1",
        "detected_at": NOW,
        "context": {},
        "dedupe_key": "inactivity:u1:42",
    }
    payload.update(overrides)
    return TriggerSignal(**payload)


def _snapshot(**overrides) -> PolicySnapshot:
    payload = {
        "generating": False,
        "has_active_action": False,
        "last_proactive_at": None,
        "attempt_count": 0,
        "intimacy": 0.62,
        "tension": 0.0,
        "mood": "calm",
        "current_activity": None,
        "selected_goal_type": "user_care",
        "goal_degraded": False,
    }
    payload.update(overrides)
    return PolicySnapshot(**payload)


def test_case4_all_conditions_pass_act():
    verdict = evaluate(_signal(), _snapshot(), CONFIG, NOW)
    assert verdict.decision == "act"
    assert verdict.intention == "check_in"
    assert verdict.trigger is not None


def test_case4_act_reason_contains_goal_type():
    verdict = evaluate(_signal(), _snapshot(), CONFIG, NOW)
    assert "user_care" in verdict.reason


def test_step1_generating_waits():
    verdict = evaluate(_signal(), _snapshot(generating=True), CONFIG, NOW)
    assert verdict.decision == "wait"
    assert "对话" in verdict.reason


def test_case6_quiet_hours_ignore_and_boundary():
    late_night = NOW.replace(hour=23, minute=30)
    verdict = evaluate(_signal(), _snapshot(), CONFIG, late_night)
    assert verdict.decision == "ignore"
    assert verdict.reason == "静音时段"

    morning = NOW.replace(hour=8, minute=0)
    assert evaluate(_signal(), _snapshot(), CONFIG, morning).decision == "act"
    just_before = NOW.replace(hour=7, minute=59)
    assert evaluate(_signal(), _snapshot(), CONFIG, just_before).decision == "ignore"


def test_case6_quiet_hours_cross_midnight():
    assert in_quiet_hours(NOW.replace(hour=1, minute=0), "23:00", "08:00") is True
    assert in_quiet_hours(NOW.replace(hour=22, minute=59), "23:00", "08:00") is False


def test_case6_quiet_hours_disabled_when_start_equals_end():
    assert in_quiet_hours(NOW.replace(hour=23), "23:00", "23:00") is False


def test_case5_cooldown_waits():
    snapshot = _snapshot(last_proactive_at=NOW - timedelta(minutes=60))
    assert evaluate(_signal(), snapshot, CONFIG, NOW).decision == "wait"


def test_case5_backoff_multiplies_interval():
    first_done = _snapshot(
        intimacy=0.4, last_proactive_at=NOW - timedelta(minutes=300), attempt_count=1
    )
    assert evaluate(_signal(), first_done, CONFIG, NOW).decision == "act"
    assert effective_interval_minutes(first_done, CONFIG) == 240.0

    second_done = _snapshot(
        intimacy=0.4, last_proactive_at=NOW - timedelta(minutes=300), attempt_count=2
    )
    assert effective_interval_minutes(second_done, CONFIG) == 480.0
    assert evaluate(_signal(), second_done, CONFIG, NOW).decision == "wait"


def test_case5_episode_limit_ignores():
    snapshot = _snapshot(attempt_count=2)
    verdict = evaluate(_signal(), snapshot, CONFIG, NOW)
    assert verdict.decision == "ignore"
    assert "上限" in verdict.reason


def test_queue_depth_one_waits():
    verdict = evaluate(_signal(), _snapshot(has_active_action=True), CONFIG, NOW)
    assert verdict.decision == "wait"
    assert "还未处理" in verdict.reason


def test_case7_intimacy_gate_ignores():
    verdict = evaluate(_signal(), _snapshot(intimacy=0.2), CONFIG, NOW)
    assert verdict.decision == "ignore"
    assert "关系尚浅" in verdict.reason


def test_case7_intimacy_gate_allows_repair_goal():
    verdict = evaluate(
        _signal(),
        _snapshot(intimacy=0.2, selected_goal_type="relationship", tension=0.6),
        CONFIG,
        NOW,
    )
    assert verdict.decision == "act"
    assert verdict.intention == "repair_rapport"


def test_case7_state_corrections_ignore():
    tired = evaluate(_signal(), _snapshot(mood="tired"), CONFIG, NOW)
    assert tired.decision == "ignore"
    busy = evaluate(
        _signal(), _snapshot(current_activity="正在睡觉"), CONFIG, NOW
    )
    assert busy.decision == "ignore"


def test_case7_motivation_gap_ignores():
    verdict = evaluate(
        _signal(), _snapshot(selected_goal_type="conversation"), CONFIG, NOW
    )
    assert verdict.decision == "ignore"
    assert "动机" in verdict.reason


def test_case7_degraded_goal_ignores():
    verdict = evaluate(_signal(), _snapshot(goal_degraded=True), CONFIG, NOW)
    assert verdict.decision == "ignore"


def test_intimacy_modifier_halves_interval_with_floor():
    intimate = _snapshot(intimacy=0.62)
    assert effective_interval_minutes(intimate, CONFIG) == 120.0
    very_intimate = _snapshot(intimacy=0.9, attempt_count=1)
    interval = effective_interval_minutes(very_intimate, CONFIG)
    assert interval == 120.0
    tense_repair = _snapshot(
        tension=0.6, selected_goal_type="relationship", attempt_count=1
    )
    assert effective_interval_minutes(tense_repair, CONFIG) == 120.0


def test_interval_never_below_floor():
    snapshot = _snapshot(intimacy=0.9)
    CONFIG_FLOOR = get_settings()
    assert effective_interval_minutes(snapshot, CONFIG_FLOOR) >= CONFIG_FLOOR.autonomy_min_interval_floor_minutes


def test_policy_always_returns_one_of_three():
    for snapshot in (
        _snapshot(generating=True),
        _snapshot(has_active_action=True),
        _snapshot(goal_degraded=True),
    ):
        assert evaluate(_signal(), snapshot, CONFIG, NOW).decision in ("act", "wait", "ignore")
