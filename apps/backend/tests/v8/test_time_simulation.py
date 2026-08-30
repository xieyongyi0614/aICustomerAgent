"""V8 Time Test（tests/v8 版本级）：时间推进与 due 联动。"""

from datetime import datetime, timedelta

from app.application import world_engine
from app.models.world import EventStatus, ObjectStatus
from app.repositories import world_repository


def test_time_advance_drives_event_and_expiry(db_session_factory, override_settings):
    override_settings(world_time_mode="story")
    world_engine.ensure_world("default-user")
    world_engine.create_event(
        "default-user",
        event_type="interview",
        title="用户的面试",
        importance="high",
        due_at=datetime.now() + timedelta(hours=2),
        source="manual",
    )
    world_engine.create_object(
        "default-user",
        name="西瓜",
        category="food",
        location_id="home.living_room",
        expiry_at=(datetime.now() + timedelta(hours=1)).isoformat(),
    )

    world_engine.advance_time("default-user", timedelta(days=2))
    world_engine.run_turn_update("default-user", "今天怎么样")

    events = world_repository.list_events(
        world_repository.world_id_for("default-user")
    )
    assert any(event.status is EventStatus.ACTIVE for event in events)
    obj = world_engine.find_object_by_name("default-user", "西瓜")
    assert obj.status is ObjectStatus.ACTIVE
    assert obj.state == "expired"
