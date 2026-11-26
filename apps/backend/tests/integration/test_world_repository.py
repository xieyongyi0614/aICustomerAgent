from datetime import datetime, timedelta

from app.core import timeutil
from app.models.world import (
    EventImportance,
    EventSource,
    EventStatus,
    StateSnapshot,
    WorldEvent,
    WorldObject,
)
from app.repositories import world_repository

USER = "default-user"


def _object(object_id="watermelon_001", location="home.kitchen.fridge", status="active"):
    return WorldObject(
        id=object_id,
        world_id=world_repository.ensure_world(USER).world_id,
        name="西瓜",
        aliases=["瓜"],
        category="food",
        location_id=location,
        state="whole",
        quantity=1.0,
        status=object_status(status),
        last_action_at=timeutil.now(),
    )


def object_status(status):
    from app.models.world import ObjectStatus

    return ObjectStatus(status)


def _event(event_id="evt_1", status="scheduled", due_at=None):
    return WorldEvent(
        id=event_id,
        world_id=world_repository.ensure_world(USER).world_id,
        type="interview",
        title="用户的面试",
        importance=EventImportance.HIGH,
        status=EventStatus(status),
        due_at=due_at,
        source=EventSource.USER_MENTION,
    )


def test_ensure_world_idempotent_and_isolated(db_session_factory):
    first = world_repository.ensure_world(USER)
    second = world_repository.ensure_world(USER)
    assert first.world_id == second.world_id and first.world_id.isdigit()
    assert first.current_location == "home.living_room"
    other = world_repository.ensure_world("someone-else")
    assert other.world_id != first.world_id and other.world_id.isdigit()
    assert world_repository.get_world(USER).world_id == first.world_id


def test_object_save_get_and_location_query(db_session_factory):
    world_repository.ensure_world(USER)
    world_repository.save_object(_object())
    loaded = world_repository.get_object(world_repository.ensure_world(USER).world_id, "watermelon_001")
    assert loaded is not None
    assert loaded.name == "西瓜"
    assert loaded.aliases == ["瓜"]
    assert loaded.status.value == "active"

    same_spot = world_repository.list_objects_at(
        world_repository.ensure_world(USER).world_id, "home.kitchen.fridge"
    )
    assert [obj.id for obj in same_spot] == ["watermelon_001"]
    assert world_repository.list_objects_at(world_repository.ensure_world(USER).world_id, "home.bedroom") == []

    world_repository.save_object(_object(status="destroyed"))
    assert world_repository.list_objects(world_repository.ensure_world(USER).world_id) == []
    assert world_repository.count_active_objects(world_repository.ensure_world(USER).world_id) == 0


def test_event_save_list_and_due_query(db_session_factory):
    world_repository.ensure_world(USER)
    now = timeutil.now()
    world_repository.save_event(_event("evt_due", due_at=now - timedelta(hours=1)))
    world_repository.save_event(_event("evt_future", status="scheduled", due_at=now + timedelta(days=1)))
    world_repository.save_event(_event("evt_done", status="completed"))

    due = world_repository.list_due_events(world_repository.ensure_world(USER).world_id, now)
    assert [event.id for event in due] == ["evt_due"]

    scheduled = world_repository.list_events(
        world_repository.ensure_world(USER).world_id, statuses=["scheduled"]
    )
    assert {event.id for event in scheduled} == {"evt_due", "evt_future"}
    assert world_repository.count_active_events(world_repository.ensure_world(USER).world_id) == 2
    assert world_repository.get_event(world_repository.ensure_world(USER).world_id, "evt_due") is not None


def test_snapshot_save_and_list(db_session_factory):
    world_repository.ensure_world(USER)
    snapshot = StateSnapshot(
        id=world_repository.new_snapshot_id(),
        world_id=world_repository.ensure_world(USER).world_id,
        label="before_dinner",
        state={"entities": []},
        created_at=timeutil.now(),
    )
    world_repository.save_snapshot(snapshot)
    rows = world_repository.list_snapshots(world_repository.ensure_world(USER).world_id)
    assert [item.label for item in rows] == ["before_dinner"]
    loaded = world_repository.get_snapshot(world_repository.ensure_world(USER).world_id, snapshot.id)
    assert loaded.state == {"entities": []}
    assert world_repository.get_snapshot(world_repository.ensure_world(USER).world_id, "missing") is None
