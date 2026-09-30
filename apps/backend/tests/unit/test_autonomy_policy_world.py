"""V8-011 policy 消费 world_facts（autonomy-integration.md §3）。"""

from datetime import datetime, timedelta

from app.models.autonomy import TriggerSignal
from app.engines.autonomy import PolicySnapshot, evaluate

NOW = datetime(2026, 9, 1, 14, 0)
USER = "default-user"


def _signal():
    return TriggerSignal(
        type="conversation_inactivity",
        user_id=USER,
        detected_at=NOW,
        context={},
        dedupe_key="inactivity:default-user:1",
    )


def _snapshot(**overrides):
    defaults = {
        "intimacy": 0.6,
        "selected_goal_type": "user_care",
        "extra_flags": {"goal_id": "goal-1"},
        "last_proactive_at": None,
        "attempt_count": 0,
    }
    defaults.update(overrides)
    return PolicySnapshot(**defaults)


def test_act_without_world_facts_unchanged():
    verdict = evaluate(_signal(), _snapshot(), now=NOW)
    assert verdict.decision == "act"
    assert "明天" not in verdict.reason
    assert "雨天" not in verdict.reason


def test_world_facts_enrich_act_reason():
    snapshot = _snapshot(
        world_facts={
            "weather": "rain",
            "part_of_day": "afternoon",
            "salient_events": [
                {
                    "id": "evt_1",
                    "type": "interview",
                    "title": "用户的面试",
                    "importance": "high",
                    "status": "scheduled",
                    "due_in_hours": 11.0,
                }
            ],
        }
    )
    verdict = evaluate(_signal(), snapshot, now=NOW)
    assert verdict.decision == "act"
    assert "雨天" in verdict.reason
    assert "面试" in verdict.reason
    assert verdict.intention is not None


def test_world_cannot_unlock_gates():
    snapshot = _snapshot(
        world_facts={"weather": "rain", "salient_events": []},
        intimacy=0.1,
        selected_goal_type="conversation",
    )
    verdict = evaluate(_signal(), snapshot, now=NOW)
    assert verdict.decision == "ignore"
    assert verdict.reason == "关系尚浅，不主动打扰"


def test_quiet_hours_still_ignored_with_world_facts():
    late_night = NOW.replace(hour=23, minute=30)
    snapshot = _snapshot(world_facts={"weather": "rain", "part_of_day": "late_night"})
    verdict = evaluate(_signal(), snapshot, now=late_night)
    assert verdict.decision == "ignore"
    assert verdict.reason == "静音时段"


def test_low_importance_or_far_events_no_note():
    snapshot = _snapshot(
        world_facts={
            "salient_events": [
                {
                    "id": "evt_2",
                    "type": "interview",
                    "title": "用户的面试",
                    "importance": "normal",
                    "status": "scheduled",
                    "due_in_hours": 72.0,
                }
            ]
        }
    )
    verdict = evaluate(_signal(), snapshot, now=NOW)
    assert verdict.decision == "act"
    assert "面试" not in verdict.reason
