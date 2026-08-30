"""V8-004 位置迁移集成：context 反映迁移；与 scene_state 零耦合。"""

from app.application import world_engine
from app.repositories import scene_state_repository
from app.services.world.locations import build_location_context


def test_move_reflects_in_context_and_never_touches_scene(db_session_factory):
    scene_state_repository.SessionLocal  # 确认夹具已替换（与 world 共用同一测试库）
    world_engine.ensure_world("default-user")
    moved = world_engine.set_location("default-user", "home.bedroom")
    assert moved.current_location == "home.bedroom"
    context = world_engine.get_location_context("default-user")
    assert context.current == "home.bedroom"
    assert context.path == ["家", "卧室"]
    assert "睡觉" in context.available_actions

    with scene_state_repository.SessionLocal() as session:
        from app.core.db import SceneStateRow

        assert session.query(SceneStateRow).count() == 0
