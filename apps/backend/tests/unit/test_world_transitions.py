"""V8-001 物品状态机纯函数（object-system.md §3）与角色资产健全性。"""

import pytest

from app.character.asuna.world import (
    EVENT_TYPE_ALIASES,
    HOME_LOCATIONS,
    LOCATION_ALIASES,
    OBJECT_STATE_MACHINES,
    WORLD_WEATHER_VALUES,
    WEATHER_ALIASES,
)
from app.models.world import apply_object_action, object_default_portions, object_initial_state


def test_food_machine_whole_cut_eaten_chain():
    assert object_initial_state(OBJECT_STATE_MACHINES, "food") == "whole"
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "food", "whole", "cut") == "cut"
    )
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "food", "cut", "eat") == "eaten"
    )
    assert apply_object_action(OBJECT_STATE_MACHINES, "food", "whole", "eat") is None
    assert apply_object_action(OBJECT_STATE_MACHINES, "food", "eaten", "cut") is None


def test_expire_and_discard_use_wildcard():
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "food", "whole", "expire")
        == "expired"
    )
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "food", "cut", "expire")
        == "expired"
    )
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "food", "cut", "discard")
        == "empty"
    )
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "food", "expired", "cut") is None
    )


def test_unknown_category_falls_back_to_generic():
    assert (
        object_initial_state(OBJECT_STATE_MACHINES, "misc") == "intact"
    )
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "misc", "intact", "damage")
        == "damaged"
    )
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "misc", "intact", "eat") is None
    )
    assert object_default_portions(OBJECT_STATE_MACHINES, "food") == 5
    assert object_default_portions(OBJECT_STATE_MACHINES, "misc") == 1
    assert (
        apply_object_action(OBJECT_STATE_MACHINES, "nonexistent", "intact", "open")
        == "open"
    )


def test_device_open_close_cycle():
    assert apply_object_action(OBJECT_STATE_MACHINES, "device", "off", "open") == "on"
    assert apply_object_action(OBJECT_STATE_MACHINES, "device", "on", "close") == "off"
    assert apply_object_action(OBJECT_STATE_MACHINES, "device", "off", "close") is None


def test_asset_locations_hierarchy_and_aliases():
    for location_id, definition in HOME_LOCATIONS.items():
        parent = definition["parent_id"]
        assert parent is None or parent in HOME_LOCATIONS
        assert definition["name"]
        assert isinstance(definition["available_actions"], list)
    assert HOME_LOCATIONS["home.kitchen.fridge"]["traits"][-1] == "food_related"
    for alias, target in LOCATION_ALIASES.items():
        assert target in HOME_LOCATIONS


def test_asset_lexicons_consistent():
    for weather in WEATHER_ALIASES.values():
        assert weather in WORLD_WEATHER_VALUES
    assert "interview" in set(EVENT_TYPE_ALIASES.values())
