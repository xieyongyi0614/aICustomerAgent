"""V8-004 地点装配与别名解析（location-system.md §2~§4）。"""

from app.models.world import World, WorldTimeMode
from app.services.world.locations import (
    build_location_context,
    location_name,
    resolve_location_alias,
)


def _world(current="home.living_room"):
    return World(
        world_id="home:default-user", user_id="default-user", current_location=current
    )


def test_location_context_builds_hierarchy_path():
    context = build_location_context(_world("home.kitchen"))
    assert context.current == "home.kitchen"
    assert context.current_name == "厨房"
    assert context.path == ["家", "厨房"]
    assert "拿食物" in context.available_actions
    assert "food_related" in context.traits


def test_location_context_unknown_returns_none():
    assert build_location_context(_world("home.attic")) is None


def test_resolve_location_alias_longest_match():
    assert resolve_location_alias("把西瓜放回冰箱里") == "home.kitchen.fridge"
    assert resolve_location_alias("我们去客厅坐坐") == "home.living_room"
    assert resolve_location_alias("先去厨房再回房间") == "home.kitchen"
    assert resolve_location_alias("今天天气不错") is None


def test_location_name_helper():
    assert location_name("home.bedroom") == "卧室"
    assert location_name("nowhere") is None
