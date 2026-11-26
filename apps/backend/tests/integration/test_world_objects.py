"""V8-005 物品全生命周期：西瓜 Created→Moved→cut→eaten(0.8)→expired→empty。"""

from datetime import datetime, timedelta

from app.core import timeutil
from app.application import world_engine
from app.models.world import ObjectStatus


def _seed():
    world_engine.ensure_world("default-user")
    obj = world_engine.create_object(
        "default-user",
        name="西瓜",
        category="food",
        location_id="home.kitchen.fridge",
        aliases=["瓜"],
        expiry_at="2026-09-01T12:00:00",
    )
    return obj.id


def test_watermelon_full_lifecycle(db_session_factory):
    object_id = _seed()

    taken = world_engine.move_object("default-user", object_id, "home.kitchen")
    assert taken.location_id == "home.kitchen"

    cut = world_engine.apply_object_action("default-user", object_id, "cut")
    assert cut.state == "cut"

    eaten = world_engine.apply_object_action("default-user", object_id, "eat")
    assert eaten.state == "eaten"
    assert eaten.quantity == 0.8

    eaten_again = world_engine.apply_object_action("default-user", object_id, "eat")
    assert eaten_again.quantity == 0.6

    assert world_engine.find_object_by_name("default-user", "瓜").id == object_id


def test_invalid_transition_refuses_without_state_change(db_session_factory):
    object_id = _seed()
    assert world_engine.apply_object_action("default-user", object_id, "eat") is None
    obj = world_engine.find_object_by_name("default-user", "西瓜")
    assert obj.state == "whole"
    assert obj.quantity == 1.0


def test_consume_to_zero_destroys(db_session_factory):
    object_id = _seed()
    world_engine.apply_object_action("default-user", object_id, "cut")
    obj = world_engine.apply_object_action(
        "default-user", object_id, "eat", portions=5
    )
    assert obj.quantity == 0.0
    assert obj.status is ObjectStatus.DESTROYED
    assert world_engine.find_object_by_name("default-user", "西瓜") is None


def test_expiry_time_evolution_idempotent(db_session_factory):
    object_id = _seed()
    world_engine.apply_object_action("default-user", object_id, "cut")
    now = timeutil.ensure_aware(datetime(2026, 9, 1, 13, 0))
    assert world_engine.expire_due_objects("default-user", now=now) == 1
    obj = world_engine.find_object_by_name("default-user", "西瓜")
    assert obj.state == "expired"
    assert world_engine.expire_due_objects("default-user", now=now) == 0


def test_expiry_not_yet_due_untouched(db_session_factory):
    object_id = _seed()
    early = timeutil.ensure_aware(datetime(2026, 8, 31, 12, 0))
    assert world_engine.expire_due_objects("default-user", now=early) == 0
    obj = world_engine.find_object_by_name("default-user", "西瓜")
    assert obj.state == "whole"


def test_discard_destroys(db_session_factory):
    object_id = _seed()
    discarded = world_engine.discard_object("default-user", object_id)
    assert discarded.state == "empty"
    assert discarded.status is ObjectStatus.DESTROYED


def test_move_to_unknown_location_refused(db_session_factory):
    object_id = _seed()
    assert world_engine.move_object("default-user", object_id, "mars") is None


def test_last_action_audit_trail(db_session_factory):
    object_id = _seed()
    created_at = world_engine.find_object_by_name("default-user", "西瓜").last_action_at
    cut = world_engine.apply_object_action("default-user", object_id, "cut")
    assert cut.last_action_at >= created_at
    assert cut.last_action_at <= timeutil.now() + timedelta(seconds=1)
