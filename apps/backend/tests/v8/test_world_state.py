"""V8 World State Test：状态保存、开关短路、降级契约（testing.md §2）。"""

import pytest

from app.application import world_engine
from app.repositories import world_repository


def test_world_state_persists_across_sessions(db_session_factory):
    world_engine.create_object("default-user", name="西瓜", category="food", location_id="home.kitchen.fridge")
    world_engine.set_environment("default-user", weather="rain")

    fresh_view = world_engine.get_full_state("default-user")
    assert fresh_view["world"]["environment"]["weather"] == "rain"
    assert [obj["name"] for obj in fresh_view["entities"]] == ["西瓜"]


def test_world_enabled_false_short_circuits(db_session_factory, override_settings):
    override_settings(world_enabled=False)
    assert world_engine.ensure_world("default-user") is not None
    assert world_engine.build_context("default-user") is None
    assert world_engine.collect_facts("default-user") == {}
    assert world_engine.run_turn_update("default-user", "给我拿个西瓜") == 0


def test_world_degrades_on_repository_failure(db_session_factory, monkeypatch):
    world_engine.ensure_world("default-user")

    def _explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(world_engine, "ensure_world", _explode)
    assert world_engine.build_context("default-user") is None
    monkeypatch.setattr(world_engine, "get_world", _explode)
    assert world_engine.collect_facts("default-user") == {}
