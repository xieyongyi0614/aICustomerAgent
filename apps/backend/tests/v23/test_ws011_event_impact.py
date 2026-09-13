"""WS-011：EventImpactRules 纯函数裁决测试（矩阵/修正项/契约冻结）。"""

from dataclasses import dataclass, field
from datetime import datetime

from app.services.world import event_impact


@dataclass
class _Event:
    id: str = "evt-1"
    type: str = "time_marker"
    importance: str = "low"
    payload: dict = field(default_factory=dict)


def test_day_start_neutral():
    impact = event_impact.evaluate(_Event(type="time_marker"))
    assert impact.urgency == "none"
    assert impact.care_relevance == 0.1
    assert impact.goal_opportunity is None


def test_significant_weather_change_care():
    impact = event_impact.evaluate(
        _Event(type="weather_change", payload={"next": "rain", "changed": True})
    )
    assert impact.urgency == "low"
    assert impact.care_relevance == 0.7
    assert impact.goal_opportunity is not None
    assert impact.goal_opportunity.domain == "user_care"


def test_micro_weather_change_neutral():
    impact = event_impact.evaluate(
        _Event(type="weather_change", payload={"next": "sunny", "changed": False})
    )
    assert impact.urgency == "none"
    assert impact.goal_opportunity is None


def test_user_condition_high_intensity():
    impact = event_impact.evaluate(
        _Event(type="user_condition", payload={"kind": "detected", "intensity": 4, "dimension": "health"})
    )
    assert impact.urgency == "high"
    assert impact.care_relevance == 0.9
    assert impact.goal_opportunity.type == "care_health"


def test_user_condition_ended_low_key():
    impact = event_impact.evaluate(
        _Event(type="user_condition", payload={"kind": "ended", "intensity": 3})
    )
    assert impact.urgency == "none"
    assert impact.goal_opportunity is None


def test_calendar_event_topic_value():
    impact = event_impact.evaluate(
        _Event(type="calendar_event", payload={"name": "圣诞节"})
    )
    assert impact.topic_value == 0.8
    assert impact.goal_opportunity.domain == "scene"


def test_goal_completed_outcome_split():
    success = event_impact.evaluate(_Event(type="goal_completed", payload={"outcome": "completed"}))
    failed = event_impact.evaluate(_Event(type="goal_completed", payload={"outcome": "abandoned"}))
    assert success.topic_value == 0.7
    assert failed.topic_value == 0.3


def test_reminder_stays_urgent():
    impact = event_impact.evaluate(_Event(type="reminder", importance="high"))
    assert impact.urgency == "high"


def test_unknown_event_neutral():
    impact = event_impact.evaluate(_Event(type="alien_signal"))
    assert impact.urgency == "none"
    assert impact.care_relevance == 0.5
    assert impact.topic_value == 0.5


def test_night_suppression_downgrades():
    event = _Event(type="user_condition", payload={"kind": "detected", "intensity": 3, "dimension": "work_pressure"})
    day = event_impact.evaluate(event, {"part_of_day": "afternoon"})
    night = event_impact.evaluate(event, {"part_of_day": "late_night"})
    assert day.urgency == "medium"
    assert night.urgency == "low"


def test_night_does_not_suppress_high_care():
    event = _Event(type="user_condition", payload={"kind": "detected", "intensity": 4, "dimension": "health"})
    night = event_impact.evaluate(event, {"part_of_day": "late_night"})
    assert night.urgency == "high"


def test_work_block_lowers_topic_value():
    event = _Event(type="calendar_event", payload={"name": "x"})
    plain = event_impact.evaluate(event)
    during_work = event_impact.evaluate(
        event, {"current_block": {"activity": "工作"}}
    )
    assert during_work.topic_value < plain.topic_value


def test_repeat_situation_downgraded():
    event = _Event(
        type="user_condition",
        payload={"kind": "detected", "intensity": 4, "dimension": "health"},
    )
    context = {"active_situations": [{"dimension": "health"}]}
    impact = event_impact.evaluate(event, context)
    assert impact.urgency == "medium"


def test_evaluate_batch_sorted_by_urgency():
    events = [
        _Event(id="a", type="time_marker"),
        _Event(id="b", type="reminder", importance="high"),
        _Event(id="c", type="user_condition", payload={"kind": "detected", "intensity": 3, "dimension": "travel"}),
    ]
    impacts = event_impact.evaluate_batch(events)
    assert [item.event_id for item in impacts][:2] == ["b", "c"]


def test_to_dict_contract():
    impact = event_impact.evaluate(
        _Event(type="weather_change", payload={"next": "snow", "changed": True})
    )
    data = impact.to_dict()
    assert set(data) == {"event_id", "event_type", "urgency", "care_relevance", "topic_value", "goal_opportunity"}
    assert data["goal_opportunity"]["layer"] == "short_term"


def test_pure_function_no_side_effects():
    event = _Event(type="weather_change", payload={"next": "rain", "changed": True})
    payload_before = dict(event.payload)
    event_impact.evaluate(event, {"part_of_day": "late_night"})
    assert event.payload == payload_before
