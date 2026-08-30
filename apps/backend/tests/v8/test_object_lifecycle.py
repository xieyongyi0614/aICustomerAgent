"""V8 Object Lifecycle Test：物品变化（跨会话持久 + 状态机拒绝造事实）。"""

from datetime import datetime, timedelta

import pytest

from app.application import world_engine
from app.models.world import ObjectStatus


@pytest.mark.asyncio
async def test_object_survives_new_sessions(db_session_factory):
    world_engine.create_object("default-user", name="西瓜", category="food", location_id="home.kitchen.fridge")
    world_engine.run_turn_update("default-user", "给我拿个西瓜")
    world_engine.run_turn_update("default-user", "切一下")
    world_engine.run_turn_update("default-user", "我吃一块")

    obj = world_engine.find_object_by_name("default-user", "西瓜")
    assert obj.location_id == "home.living_room"
    assert obj.state == "eaten"
    assert obj.quantity == pytest.approx(0.8)

    reloaded = world_engine.get_full_state("default-user")
    assert reloaded["entities"][0]["state"] == "eaten"


def test_expired_object_cannot_be_eaten(db_session_factory):
    world_engine.create_object(
        "default-user",
        name="西瓜",
        category="food",
        location_id="home.living_room",
        expiry_at=(datetime.now() - timedelta(hours=1)).isoformat(),
    )
    world_engine.expire_due_objects("default-user")
    obj = world_engine.find_object_by_name("default-user", "西瓜")
    assert obj.state == "expired"
    assert world_engine.apply_object_action("default-user", obj.id, "eat") is None


def test_destroyed_object_gone_from_queries(db_session_factory):
    world_engine.create_object("default-user", name="蛋糕", category="food", location_id="home.living_room")
    obj = world_engine.find_object_by_name("default-user", "蛋糕")
    world_engine.discard_object("default-user", obj.id)
    assert world_engine.find_object_by_name("default-user", "蛋糕") is None
    assert world_repository_status("default-user", obj.id) is not None


def world_repository_status(user_id, object_id):
    from app.repositories import world_repository

    world = world_engine.get_world(user_id)
    row = world_repository.get_object(world.world_id, object_id)
    return row.status if row else None


def test_destroyed_row_kept_as_history(db_session_factory):
    world_engine.create_object("default-user", name="果汁", category="drink", location_id="home.living_room")
    obj = world_engine.find_object_by_name("default-user", "果汁")
    world_engine.discard_object("default-user", obj.id)
    from app.repositories import world_repository

    row = world_repository.get_object(world_engine.get_world("default-user").world_id, obj.id)
    assert row.status is ObjectStatus.DESTROYED
