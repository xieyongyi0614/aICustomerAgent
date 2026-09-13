"""V2.3.0 EventImpactRules（architecture.md §5.4）：世界事件 → 影响裁决。

纯函数无 IO 无 LLM；输出契约（EventImpact/GoalHint）冻结，供
WS-013（自治素材）与 WS-014（timing/goal 机会）消费；未知事件回中性值。
"""

from dataclasses import dataclass
from datetime import datetime

URGENCY_NONE = "none"
URGENCY_LOW = "low"
URGENCY_MEDIUM = "medium"
URGENCY_HIGH = "high"

_URGENCY_ORDER = (URGENCY_NONE, URGENCY_LOW, URGENCY_MEDIUM, URGENCY_HIGH)

_SIGNIFICANT_WEATHER = ("rain", "snow", "windy")


@dataclass
class GoalHint:
    domain: str
    type: str
    hint: str
    layer: str = "short_term"


@dataclass
class EventImpact:
    event_id: str | None
    event_type: str
    urgency: str
    care_relevance: float
    topic_value: float
    goal_opportunity: GoalHint | None = None

    def to_dict(self) -> dict:
        goal = None
        if self.goal_opportunity is not None:
            goal = {
                "domain": self.goal_opportunity.domain,
                "type": self.goal_opportunity.type,
                "hint": self.goal_opportunity.hint,
                "layer": self.goal_opportunity.layer,
            }
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "urgency": self.urgency,
            "care_relevance": self.care_relevance,
            "topic_value": self.topic_value,
            "goal_opportunity": goal,
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _demote(urgency: str) -> str:
    index = _URGENCY_ORDER.index(urgency)
    return _URGENCY_ORDER[max(0, index - 1)]


def _base_rules(event_type: str, importance: str, payload: dict):
    if event_type == "weather_change":
        next_weather = payload.get("next") or ""
        changed = bool(payload.get("changed"))
        if next_weather in _SIGNIFICANT_WEATHER and changed:
            care = 0.7 if next_weather in ("rain", "snow") else 0.5
            hint = None
            if next_weather in ("rain", "snow"):
                hint = GoalHint("user_care", "remind_weather", "提醒用户注意天气")
            return (URGENCY_LOW, care, 0.4, hint)
        return (URGENCY_NONE, 0.1, 0.2, None)
    if event_type == "user_condition":
        kind = payload.get("kind", "detected")
        intensity = int(payload.get("intensity") or 3)
        if kind != "detected":
            return (URGENCY_NONE, 0.3, 0.5, None)
        urgency = URGENCY_HIGH if intensity >= 4 else URGENCY_MEDIUM
        dimension = payload.get("dimension", "")
        hint = GoalHint("user_care", f"care_{dimension}", f"关心用户：{payload.get('summary', '')[:20]}")
        return (urgency, 0.9, 0.6, hint)
    if event_type == "calendar_event":
        return (URGENCY_LOW, 0.5, 0.8, GoalHint("scene", "celebrate", "节日问候"))
    if event_type == "time_marker":
        return (URGENCY_NONE, 0.1, 0.3, None)
    if event_type == "life_event":
        kind = payload.get("kind", "")
        if kind == "activity_done" and payload.get("variability_source") == "user_influenced":
            return (URGENCY_NONE, 0.3, 0.6, None)
        if kind == "location_change":
            return (URGENCY_NONE, 0.1, 0.4, None)
        return (URGENCY_NONE, 0.1, 0.3, None)
    if event_type == "goal_completed":
        outcome = payload.get("outcome", "completed")
        return (URGENCY_NONE, 0.2, 0.7 if outcome == "completed" else 0.3, None)
    if event_type == "interest_emerged":
        return (URGENCY_NONE, 0.2, 0.6, None)
    if event_type in ("reminder", "appointment", "interview", "exam", "birthday", "meeting", "trip"):
        return (URGENCY_HIGH, 0.5, 0.3, None)
    return (URGENCY_NONE, 0.5, 0.5, None)


def evaluate(event, context: dict | None = None) -> EventImpact:
    """event: WorldEvent 兼容对象（type/importance/payload/id）；context 可空。"""
    context = context or {}
    payload = getattr(event, "payload", None) or {}
    event_type = getattr(event, "type", "")
    importance = str(getattr(event, "importance", "low"))
    urgency, care, topic, goal = _base_rules(event_type, importance, payload)

    part = context.get("part_of_day")
    if part == "late_night" and urgency not in (URGENCY_NONE, URGENCY_HIGH):
        urgency = _demote(urgency)
        if context.get("care_relevance_floor") is None and care < 0.7:
            care = _clamp01(care * 0.5)

    block = context.get("current_block") or {}
    activity = str(block.get("activity") or "")
    if activity and urgency in (URGENCY_NONE, URGENCY_LOW) and care < 0.7:
        topic = _clamp01(topic - 0.2)

    active_dimensions = {
        item.get("dimension") for item in context.get("active_situations", []) or []
    }
    if event_type == "user_condition" and payload.get("dimension") in active_dimensions:
        urgency = _demote(urgency)

    return EventImpact(
        event_id=getattr(event, "id", None),
        event_type=event_type,
        urgency=urgency,
        care_relevance=_clamp01(care),
        topic_value=_clamp01(topic),
        goal_opportunity=goal,
    )


def evaluate_batch(events, context: dict | None = None) -> list[EventImpact]:
    impacts = [evaluate(event, context) for event in events or []]
    impacts.sort(
        key=lambda item: _URGENCY_ORDER.index(item.urgency),
        reverse=True,
    )
    return impacts
