"""ACTION-004 集成：真实 World Engine 保序落库 + character_action 事件历史。"""

from app.application import world_engine
from app.models.character_action import (
    ActionTransitionEvent,
    TargetRef,
    TurnRef,
    WorldAction,
    WorldActionStatus,
)
from app.models.world import ConsumeError, EventImportance, EventSource, EventStatus
from app.repositories import world_repository
from app.services.character_action.mutator import execute_actions


def _action(action_type: str, name: str, quantity: float | None = 1.0, object_id: str | None = None,
            location_id: str | None = None, dedupe_key: str = "") -> WorldAction:
    action = WorldAction(
        action_type=action_type,
        target=TargetRef(name=name, object_id=object_id, location_id=location_id),
        quantity=quantity,
        turn_ref=TurnRef(session_id="s1", turn_id="t1", ordinal=0),
    )
    action.dedupe_key = dedupe_key
    action.transition(ActionTransitionEvent.VALIDATE_PASS)
    return action


def _character_events(user_id: str):
    world = world_engine.get_world(user_id)
    assert world is not None
    events = world_repository.list_events(world.world_id, statuses=["completed"], limit=100)
    return [e for e in events if e.type == "character_action"]


def test_consume_applied_and_event_recorded(db_session_factory):
    world_engine.create_object("mut-consume", name="鸡蛋", category="food",
                               location_id="home.kitchen.fridge", quantity=6.0)
    results = execute_actions(
        [_action("CONSUME", "鸡蛋", 2.0, dedupe_key="dk-consume")], user_id="mut-consume"
    )
    assert results[0].status == "applied"
    assert results[0].engine_fn == "consume_object"
    assert world_engine.find_object_by_name("mut-consume", "鸡蛋").quantity == 4.0

    events = _character_events("mut-consume")
    assert len(events) == 1
    event = events[0]
    assert event.status == EventStatus.COMPLETED
    assert event.source == EventSource.CHARACTER
    assert event.importance == EventImportance.LOW
    assert event.title.startswith("消耗鸡蛋")
    assert event.payload["action_type"] == "CONSUME"
    assert event.payload["quantity"] == 2.0
    assert event.payload["before"]["quantity"] == 6.0
    assert event.payload["after"]["quantity"] == 4.0
    assert event.payload["dedupe_key"] == "dk-consume"
    assert results[0].world_event_id == event.id


def test_create_then_consume_same_object(db_session_factory):
    create = _action("CREATE", "蛋糕卷", 1.0, dedupe_key="dk-create")
    consume = _action("CONSUME", "蛋糕卷", 1.0, dedupe_key="dk-consume")
    results = execute_actions([create, consume], user_id="mut-order")
    assert [r.status for r in results] == ["applied", "applied"]

    made = world_engine.find_object_by_name("mut-order", "蛋糕卷")
    assert made is not None
    assert made.quantity == 0.0
    events = _character_events("mut-order")
    assert len(events) == 2
    assert [e.payload["action_type"] for e in events] == ["CREATE", "CONSUME"]


def test_failure_no_partial_deduct_and_no_event(db_session_factory):
    world_engine.create_object("mut-fail", name="鸡蛋", category="food",
                               location_id="home.kitchen.fridge", quantity=1.0)
    action = _action("CONSUME", "鸡蛋", 3.0, dedupe_key="dk-over")
    results = execute_actions([action], user_id="mut-fail")
    assert results[0].status == "failed"
    assert results[0].engine_error == ConsumeError.INSUFFICIENT_QUANTITY.value
    assert world_engine.find_object_by_name("mut-fail", "鸡蛋").quantity == 1.0
    assert action.status == WorldActionStatus.FAILED
    assert _character_events("mut-fail") == []


def test_move_applied_with_from_to(db_session_factory):
    box = world_engine.create_object("mut-move", name="牛奶", category="drink",
                                     location_id="home.kitchen.fridge", quantity=1.0)
    results = execute_actions(
        [_action("MOVE", "牛奶", quantity=None, object_id=box.id,
                 location_id="home.kitchen", dedupe_key="dk-move")],
        user_id="mut-move",
    )
    assert results[0].status == "applied"
    moved = world_engine.find_object_by_name("mut-move", "牛奶")
    assert moved.location_id == "home.kitchen"

    event = _character_events("mut-move")[0]
    assert event.payload["location_from"] == "home.kitchen.fridge"
    assert event.payload["location_to"] == "home.kitchen"
    assert event.title == "牛奶移到厨房"


def test_event_dedupe_by_same_key(db_session_factory):
    world_engine.create_object("mut-dup", name="鸡蛋", category="food",
                               location_id="home.kitchen.fridge", quantity=6.0)
    execute_actions([_action("CONSUME", "鸡蛋", 2.0, dedupe_key="dup1")], user_id="mut-dup")
    execute_actions([_action("CONSUME", "鸡蛋", 2.0, dedupe_key="dup1")], user_id="mut-dup")
    assert world_engine.find_object_by_name("mut-dup", "鸡蛋").quantity == 2.0
    assert len(_character_events("mut-dup")) == 1


def test_rejected_action_is_not_executed(db_session_factory):
    world_engine.create_object("mut-rej", name="鸡蛋", category="food",
                               location_id="home.kitchen.fridge", quantity=6.0)
    bad = WorldAction(
        action_type="CONSUME",
        target=TargetRef(name="鸡蛋"),
        quantity=2.0,
        turn_ref=TurnRef(session_id="s1", turn_id="t1", ordinal=0),
    )
    bad.transition(ActionTransitionEvent.VALIDATE_REJECT)
    good = _action("CONSUME", "鸡蛋", 2.0)
    results = execute_actions([bad, good], user_id="mut-rej")
    assert results[0].status == "rejected"
    assert results[1].status == "applied"
    assert world_engine.find_object_by_name("mut-rej", "鸡蛋").quantity == 4.0
    assert len(_character_events("mut-rej")) == 1
