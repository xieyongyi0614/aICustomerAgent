"""V8-013 快照与恢复：整包回滚、恢复前留存、Character 状态不回滚语义。"""

from app.application import world_engine
from app.repositories import world_repository


def test_restore_rolls_world_back(db_session_factory):
    world_engine.ensure_world("default-user")
    world_engine.create_object("default-user", name="西瓜", category="food", location_id="home.living_room")
    baseline = world_engine.snapshot("default-user", label="baseline")
    assert baseline is not None
    baseline_entities = {obj["name"] for obj in baseline.state["entities"]}
    assert "西瓜" in baseline_entities
    baseline_count = len(baseline_entities)

    world_engine.create_object("default-user", name="蛋糕", category="food", location_id="home.living_room")
    world_engine.set_location("default-user", "home.bedroom")
    world_engine.set_environment("default-user", weather="rain")
    after_names = {
        obj["name"] for obj in world_engine.get_full_state("default-user")["entities"]
    }
    assert "蛋糕" in after_names
    assert len(after_names) == baseline_count + 1

    restored = world_engine.restore_snapshot("default-user", baseline.id)
    assert restored is not None
    assert restored.current_location == "home.living_room"
    assert restored.environment.weather is None
    restored_names = {
        obj["name"] for obj in world_engine.get_full_state("default-user")["entities"]
    }
    assert "西瓜" in restored_names
    assert "蛋糕" not in restored_names

    labels = [snap.label for snap in world_repository.list_snapshots(world_repository.world_id_for("default-user"))]
    assert "pre_restore" in labels


def test_restore_missing_snapshot_returns_none(db_session_factory):
    world_engine.ensure_world("default-user")
    assert world_engine.restore_snapshot("default-user", "snap_missing") is None
