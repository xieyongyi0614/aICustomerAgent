"""V8 场景套件 runner：声明式世界场景（testing.md §4）。

JSON 场景 = 初始世界 + 消息/时间步进序列 + 期望（实体/事件/环境/渲染片段）。
全确定性：story 时间冻结、无真实 LLM、每场景独立用户世界。
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.application import world_engine
from app.repositories import memory_repository, world_repository

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios" / "world_scenarios.json"


def load_scenarios():
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def _run_step(db_session_factory, user_id, step):
    if "advance_days" in step:
        world_engine.advance_time(user_id, timedelta(days=step["advance_days"]))
    if "message" in step:
        world_engine.run_turn_update(user_id, step["message"])


def _expect_object(user_id, spec):
    obj = world_engine.find_object_by_name(user_id, spec["name"])
    assert obj is not None, f"实体缺失: {spec}"
    for key, value in spec.items():
        actual = getattr(obj, key)
        if key == "quantity":
            assert actual == pytest.approx(value), f"{key}: {actual} != {value}"
        else:
            assert actual == value, f"{key}: {actual} != {value}"


def _expect_event(user_id, spec):
    world = world_engine.get_world(user_id)
    events = world_repository.list_events(
        world.world_id, statuses=["scheduled", "active", "completed"]
    )
    matched = [event for event in events if event.type == spec["type"]]
    assert matched, f"事件缺失: {spec}"
    for key, value in spec.items():
        if key == "type":
            continue
        actual = getattr(matched[0], key)
        assert actual.value == value if hasattr(actual, "value") else actual == value


def _expect_environment(user_id, spec):
    environment = world_engine.get_world(user_id).environment
    for key, value in spec.items():
        assert getattr(environment, key) == value, f"{key}: {getattr(environment, key)} != {value}"


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda s: s["name"])
def test_world_scenario(db_session_factory, override_settings, scenario):
    override_settings(world_time_mode=scenario.get("time_mode", "story"))
    user_id = f"scenario-{scenario['name']}"

    setup = scenario.get("setup", {})
    for spec in setup.get("entities", []):
        assert (
            world_engine.create_object(
                user_id,
                name=spec["name"],
                category=spec["category"],
                location_id=spec["location_id"],
                aliases=spec.get("aliases", []),
                quantity=spec.get("quantity", 1.0),
                **spec.get("properties", {}),
            )
            is not None
        )

    for step in scenario["steps"]:
        _run_step(db_session_factory, user_id, step)
        expect = step.get("expect", {})
        if "object" in expect:
            _expect_object(user_id, expect["object"])
        if "event" in expect:
            _expect_event(user_id, expect["event"])
        if "environment" in expect:
            _expect_environment(user_id, expect["environment"])
        if "memory_contains" in expect:
            memories = memory_repository.list_by_user(user_id, limit=20)
            assert any(expect["memory_contains"] in memory.content for memory in memories)

    render_checks = [
        step["render_contains"] for step in scenario["steps"] if "render_contains" in step
    ]
    if render_checks:
        context = world_engine.build_context(user_id)
        from app.services.world.context_selector import render_world_section

        text = render_world_section(context) or ""
        for fragment in render_checks:
            assert fragment in text
