"""V8-004 位置迁移集成：context 反映迁移；与 scene_state 零耦合。"""

import logging
from datetime import datetime

from app.application import world_engine
from app.repositories import scene_state_repository, world_repository
from app.services.world import movement
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


def test_move_back_to_same_location_in_same_part_dedupes_event(
    db_session_factory, caplog
):
    user = "move-dedupe-user"
    world = world_engine.ensure_world(user)
    now = datetime(2026, 9, 27, 22, 0)

    with caplog.at_level(logging.INFO):
        away = movement.apply(
            user, "home.kitchen", source=movement.SOURCE_SCHEDULE, now=now
        )
        back = movement.apply(
            user, "home.living_room", source=movement.SOURCE_SCHEDULE, now=now
        )
        away_again = movement.apply(
            user, "home.kitchen", source=movement.SOURCE_SCHEDULE, now=now
        )

    assert (away.applied, back.applied, away_again.applied) == (True, True, True)
    assert world_engine.get_world(user).current_location == "home.kitchen"
    moves = [
        event
        for event in world_repository.list_events(world.world_id, types=["life_event"])
        if (event.payload or {}).get("kind") == "location_change"
    ]
    assert {event.payload["to"] for event in moves} == {"home.kitchen", "home.living_room"}
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
