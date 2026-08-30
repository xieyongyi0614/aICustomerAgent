"""V8-002 WorldEngine：生命周期、手动通道、降级契约。"""

from app.application import world_engine
from app.character.asuna.world import OBJECT_STATE_MACHINES
from app.models.world import object_initial_state


def test_ensure_world_creates_default_home(db_session_factory):
    world = world_engine.ensure_world("default-user")
    assert world is not None
    assert world.current_location == "home.living_room"
    assert world.environment.weather is None
    assert world_engine.get_world("default-user").world_id == world.world_id


def test_create_object_uses_category_initial_state(db_session_factory):
    obj = world_engine.create_object(
        "default-user", name="西瓜", category="food", location_id="home.kitchen.fridge", aliases=["瓜"]
    )
    assert obj is not None
    assert obj.state == object_initial_state(OBJECT_STATE_MACHINES, "food")
    assert obj.world_id == "home:default-user"
    assert obj.location_id == "home.kitchen.fridge"
    placed_here = world_engine.create_object("default-user", name="书", category="misc")
    assert placed_here.location_id == "home.living_room"


def test_set_environment_merges_and_keeps_manual_marker(db_session_factory):
    world_engine.set_environment("default-user", weather="rain", temperature_c=18.0)
    world = world_engine.get_world("default-user")
    assert world.environment.weather == "rain"
    assert world.environment.temperature_c == 18.0
    assert world.environment.updated_by == "manual"
    world_engine.set_environment("default-user", weather=None, lighting="dark")
    env = world_engine.get_world("default-user").environment
    assert env.weather == "rain"
    assert env.lighting == "dark"


def test_set_location_rejects_unknown(db_session_factory):
    assert world_engine.set_location("default-user", "home.kitchen").current_location == "home.kitchen"
    assert world_engine.set_location("default-user", "mars") is None
    assert world_engine.get_world("default-user").current_location == "home.kitchen"


def test_snapshot_captures_full_state(db_session_factory):
    world_engine.create_object("default-user", name="西瓜", category="food")
    snapshot = world_engine.snapshot("default-user", label="test")
    assert snapshot is not None
    assert snapshot.label == "test"
    assert snapshot.state["current_location"] == "home.living_room"
    assert len(snapshot.state["entities"]) == 1
    full = world_engine.get_full_state("default-user")
    assert len(full["snapshots"]) == 1
    assert {obj["name"] for obj in full["entities"]} == {"西瓜"}
