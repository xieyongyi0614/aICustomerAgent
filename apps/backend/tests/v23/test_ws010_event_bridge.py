"""WS-010：CharacterEventBridge 测试（goal 终态桥 / interest listener / outbox 转译）。"""

from datetime import datetime

import pytest

from app.application import outbox_consumer
from app.core.settings import get_settings
from app.models.world import EventSource
from app.repositories import goal_repository, outbox_repository, world_repository
from app.services.goal import arbitration as goal_arbitration
from app.services.goal import observation as goal_observation
from app.services.world import event_bridge

pytestmark = pytest.mark.xdist_group("ws010")


@pytest.fixture
def bridge_flags(monkeypatch):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_goal(user_id: str, description: str = "整理书架"):
    from app.models.goal import GoalRecord

    now = datetime.now()
    record = GoalRecord(
        user_id=user_id,
        type="user_care",
        description=description,
        created_at=now,
        updated_at=now,
    )
    return goal_repository.create_goal(record)


def test_register_goal_event_always_writes_outbox(db_session_factory):
    assert event_bridge.register_goal_event("u-off", "g1", "整理书架", "completed") is True
    assert outbox_repository.list_pending(limit=10) != []


def test_goal_completion_bridges_to_world_event(db_session_factory, bridge_flags):
    user = "ws010-goal"
    goal = _seed_goal(user)
    result = goal_observation._complete(goal)
    assert result["outcome"] == "completed"

    stats = outbox_consumer.consume_pending()
    assert stats["consumed"] >= 1
    world = world_repository.get_world(user)
    events = world_repository.list_events(world.world_id, limit=10)
    goals_done = [e for e in events if e.type == "goal_completed"]
    assert goals_done
    assert goals_done[0].source.value == EventSource.CHARACTER.value
    assert goals_done[0].payload["goal_id"] == goal.id
    assert goals_done[0].payload["outcome"] == "completed"


def test_goal_abandoned_bridges_low_importance(db_session_factory, bridge_flags):
    event_bridge.register_goal_event("ws010-abandon", "g9", "学吉他", "abandoned")
    outbox_consumer.consume_pending()
    world = world_repository.get_world("ws010-abandon")
    events = [e for e in world_repository.list_events(world.world_id, limit=10) if e.type == "goal_completed"]
    assert events and events[0].importance.value == "low"
    assert events[0].payload["outcome"] == "abandoned"


def test_interest_listener_threshold(db_session_factory, bridge_flags):
    user = "ws010-interest"
    created = [
        {"insight_id": "ins-high", "scope": "self", "confidence": 0.9, "summary": "胶片摄影"},
        {"insight_id": "ins-low", "scope": "self", "confidence": 0.4, "summary": "钓鱼"},
        {"insight_id": "ins-rel", "scope": "relationship", "confidence": 0.95, "summary": "无关"},
    ]
    event_bridge.on_insight_created(user, created)
    outbox_consumer.consume_pending()
    world = world_repository.get_world(user)
    events = [e for e in world_repository.list_events(world.world_id, limit=10) if e.type == "interest_emerged"]
    assert len(events) == 1
    assert events[0].payload["insight_id"] == "ins-high"
    assert events[0].payload["topic"] == "胶片摄影"


def test_outbox_idempotent_redelivery(db_session_factory, bridge_flags):
    event_bridge.register_goal_event("ws010-idem", "g-one", "整理书架", "completed")
    first = outbox_consumer.consume_pending()
    assert first["consumed"] == 1
    event_bridge.register_goal_event("ws010-idem", "g-one", "整理书架", "completed")
    assert outbox_repository.list_pending(limit=10) == []
    world = world_repository.get_world("ws010-idem")
    events = [e for e in world_repository.list_events(world.world_id, limit=10) if e.type == "goal_completed"]
    assert len(events) == 1


def test_listener_registration_always_registers():
    from app.services.reflection import lifecycle as reflection_lifecycle

    reflection_lifecycle.reset_insight_created_listeners()
    before = len(reflection_lifecycle._insight_created_listeners)
    event_bridge.register_character_event_listeners()
    assert len(reflection_lifecycle._insight_created_listeners) == before + 1
    reflection_lifecycle.reset_insight_created_listeners()
