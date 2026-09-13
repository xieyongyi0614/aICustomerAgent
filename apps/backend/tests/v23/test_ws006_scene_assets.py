"""WS-006：场景资产层测试（地点扩展 / SceneProfile / MovementResolver）。"""

from datetime import datetime

import pytest

from app.character.asuna.scene_profiles import (
    DEFAULT_SCENE_PROFILE,
    cap_expression,
    scene_profile_for,
)
from app.character.asuna.world import (
    HOME_LOCATIONS,
    WORLD_LOCATION_REGISTRY,
    WORLD_LOCATIONS,
)
from app.repositories import world_repository
from app.services.world import movement
from app.services.world.locations import (
    build_location_context,
    is_known_location,
    location_name,
    resolve_location_alias,
)

pytestmark = pytest.mark.xdist_group("ws006")


def test_home_registry_unchanged():
    for location_id, definition in HOME_LOCATIONS.items():
        assert WORLD_LOCATION_REGISTRY[location_id] == definition


def test_new_locations_registered_with_aliases():
    for location_id in WORLD_LOCATIONS:
        assert is_known_location(location_id)
    assert resolve_location_alias("我们去咖啡店坐坐") == "cafe.main"
    assert resolve_location_alias("在学校图书馆看书") == "school.library"
    assert resolve_location_alias("海边度假") == "travel_seaside"
    assert location_name("cafe.main") == "咖啡店堂区"


def test_build_location_context_for_new_location(db_session_factory):
    world = world_repository.ensure_world("ws006-user")
    world.current_location = "cafe.main"
    world_repository.save_world(world)
    context = build_location_context(world)
    assert context is not None
    assert context.current_name == "咖啡店堂区"
    assert context.path == ["咖啡店", "咖啡店堂区"]


def test_scene_profiles_cover_registered_locations():
    for location_id in WORLD_LOCATIONS:
        profile = scene_profile_for(location_id)
        assert profile.tone_bias != ""
        assert profile.expressiveness_cap in ("subtle", "natural", "rich")
    assert scene_profile_for("home.living_room").tone_bias == "intimate"
    assert scene_profile_for("home.kitchen.fridge").tone_bias == "intimate"


def test_unknown_location_falls_back_to_default():
    profile = scene_profile_for("nowhere")
    assert profile == DEFAULT_SCENE_PROFILE.model_copy(update={"location_id": "nowhere"})


def test_cap_expression_only_lowers():
    assert cap_expression("rich", "subtle") == "subtle"
    assert cap_expression("subtle", "rich") == "subtle"
    assert cap_expression("natural", "natural") == "natural"
    assert cap_expression("weird", "rich") == "weird"


def test_movement_requires_known_location(db_session_factory):
    result = movement.apply("ws006-mv", "mars", source=movement.SOURCE_SCHEDULE)
    assert result.applied is False
    assert result.skipped_reason == "unknown_location"


def test_movement_same_location_no_op(db_session_factory):
    world_repository.ensure_world("ws006-mv2")
    result = movement.apply(
        "ws006-mv2", "home.living_room", source=movement.SOURCE_SCHEDULE
    )
    assert result.applied is False
    assert result.skipped_reason == "same_location"


def test_schedule_move_applies_and_emits_event(db_session_factory):
    world_repository.ensure_world("ws006-mv3")
    result = movement.apply(
        "ws006-mv3",
        "cafe.main",
        source=movement.SOURCE_SCHEDULE,
        reason="block:下午咖啡",
        now=datetime(2026, 9, 14, 15, 0),
    )
    assert result.applied is True
    assert world_repository.get_world("ws006-mv3").current_location == "cafe.main"
    events = world_repository.list_events(
        world_repository.world_id_for("ws006-mv3"), statuses=["completed"], limit=10
    )
    moves = [e for e in events if (e.payload or {}).get("kind") == "location_change"]
    assert len(moves) == 1
    assert moves[0].payload["move_source"] == "schedule"
    assert moves[0].payload["from"] == "home.living_room"


def test_narrative_priority_blocks_schedule_move_in_same_part(db_session_factory):
    user = "ws006-mv4"
    world_repository.ensure_world(user)
    narrative = movement.apply(
        user,
        "park.bench",
        source=movement.SOURCE_USER_NARRATIVE,
        reason="interpreter",
        now=datetime(2026, 9, 14, 15, 0),
    )
    assert narrative.applied is True
    schedule = movement.apply(
        user,
        "cafe.main",
        source=movement.SOURCE_SCHEDULE,
        reason="block",
        now=datetime(2026, 9, 14, 15, 30),
    )
    assert schedule.applied is False
    assert schedule.skipped_reason == "narrative_priority"
    assert world_repository.get_world(user).current_location == "park.bench"


def test_narrative_priority_expires_across_parts(db_session_factory):
    user = "ws006-mv5"
    world_repository.ensure_world(user)
    narrative = movement.apply(
        user,
        "park.bench",
        source=movement.SOURCE_USER_NARRATIVE,
        now=datetime(2026, 9, 14, 15, 0),
    )
    assert narrative.applied is True
    schedule = movement.apply(
        user,
        "cafe.main",
        source=movement.SOURCE_SCHEDULE,
        now=datetime(2026, 9, 14, 19, 0),
    )
    assert schedule.applied is True
    assert world_repository.get_world(user).current_location == "cafe.main"


def test_narrative_move_into_new_location(db_session_factory):
    user = "ws006-mv6"
    world_repository.ensure_world(user)
    result = movement.apply(
        user,
        "school.classroom",
        source=movement.SOURCE_USER_NARRATIVE,
        reason="interpreter",
        now=datetime(2026, 9, 14, 9, 0),
    )
    assert result.applied is True
    assert world_repository.get_world(user).current_location == "school.classroom"
    events = world_repository.list_events(
        world_repository.world_id_for(user), statuses=["completed"], limit=10
    )
    moves = [e for e in events if (e.payload or {}).get("kind") == "location_change"]
    assert moves and moves[0].source.value == "user_mention"
