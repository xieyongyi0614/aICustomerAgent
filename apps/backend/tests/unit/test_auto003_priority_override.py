"""AUTO-003 动机与优先级覆盖测试（architecture.md §8/§14，Gap G8）。

P0（scheduled_followup）/P1（action_due）覆盖普通冷却；P2/P3 不覆盖；
静音时段铁律优先——P0 默认仍拦截（QUIET_HOURS_EXEMPT_TYPES 为空）。
"""

from datetime import datetime, timedelta

from app.models.autonomy import TriggerSignal
from app.services.autonomy_policy import (
    PolicySnapshot,
    evaluate,
    trigger_priority,
)

NOW = datetime(2026, 8, 30, 14, 0)
CONFIG_QUIET = ("23:00", "08:00")


def _signal(trigger_type: str, **overrides) -> TriggerSignal:
    payload = {
        "type": trigger_type,
        "user_id": "u1",
        "detected_at": NOW,
        "context": {},
        "dedupe_key": f"{trigger_type}:u1:1",
    }
    payload.update(overrides)
    return TriggerSignal(**payload)


def _snapshot(**overrides) -> PolicySnapshot:
    payload = {
        "generating": False,
        "has_active_action": False,
        "last_proactive_at": NOW - timedelta(minutes=10),
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


def _config():
    from app.core.settings import get_settings

    return get_settings()


def test_priority_mapping():
    assert trigger_priority(_signal("scheduled_followup")) == "P0"
    assert trigger_priority(_signal("action_due")) == "P1"
    assert trigger_priority(_signal("conversation_inactivity")) == "P3"


def test_p0_followup_overrides_cooldown():
    verdict = evaluate(_signal("scheduled_followup"), _snapshot(), _config(), NOW)
    assert verdict.decision == "act"
    assert "覆盖冷却" in verdict.reason


def test_p1_action_due_overrides_cooldown():
    verdict = evaluate(_signal("action_due"), _snapshot(), _config(), NOW)
    assert verdict.decision == "act"
    assert "覆盖冷却" in verdict.reason


def test_p3_inactivity_does_not_override_cooldown():
    verdict = evaluate(
        _signal("conversation_inactivity"), _snapshot(), _config(), NOW
    )
    assert verdict.decision == "wait"
    assert "冷却中" in verdict.reason


def test_p0_no_override_note_when_cooldown_passed():
    snapshot = _snapshot(last_proactive_at=NOW - timedelta(hours=5))
    verdict = evaluate(_signal("scheduled_followup"), snapshot, _config(), NOW)
    assert verdict.decision == "act"
    assert "覆盖冷却" not in verdict.reason


def test_quiet_hours_still_blocks_p0():
    now = datetime(2026, 8, 30, 23, 30)
    verdict = evaluate(_signal("scheduled_followup"), _snapshot(), _config(), now)
    assert verdict.decision == "ignore"
    assert "静音时段" in verdict.reason


def test_p0_episode_limit_still_applies():
    snapshot = _snapshot(attempt_count=2)
    verdict = evaluate(_signal("scheduled_followup"), snapshot, _config(), NOW)
    assert verdict.decision == "ignore"
    assert "集期已达上限" in verdict.reason
