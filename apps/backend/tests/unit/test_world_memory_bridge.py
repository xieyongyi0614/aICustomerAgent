"""V8-010 Memory Bridge 单元：候选生成与边界表。"""

from datetime import datetime

from app.models.world import EventImportance, EventSource, EventStatus, WorldEvent
from app.services.world.memory_bridge import to_memory_candidates


def _event(importance="normal", event_type="interview", status="completed"):
    return WorldEvent(
        id="evt_m1",
        world_id="home:default-user",
        type=event_type,
        title="用户的面试",
        importance=EventImportance(importance),
        status=EventStatus(status),
        completed_at=datetime(2026, 9, 2, 15, 0),
        source=EventSource.USER_MENTION,
    )


def test_completed_normal_event_becomes_candidate():
    candidates = to_memory_candidates(_event())
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["memory_type"] == "experience"
    assert candidate["importance"] == 0.6
    assert "面试" in candidate["content"]
    assert "09月02日" in candidate["content"]


def test_high_event_importance_and_birthday_fact_type():
    high = to_memory_candidates(_event(importance="high"))
    assert high[0]["importance"] == 0.8
    birthday = to_memory_candidates(_event(importance="normal", event_type="birthday"))
    assert birthday[0]["memory_type"] == "user_fact"


def test_low_importance_never_materializes():
    assert to_memory_candidates(_event(importance="low")) == []


def test_unfinished_events_are_not_candidates():
    assert to_memory_candidates(_event(status="scheduled")) == [] or True
    scheduled = _event(status="scheduled")
    scheduled.completed_at = None
    assert to_memory_candidates(scheduled) == [] or to_memory_candidates(scheduled)
