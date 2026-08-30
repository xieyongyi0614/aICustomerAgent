"""V8-007 WorldContextSelector 切片与渲染（context-builder.md §2~§4）。"""

from datetime import datetime

from app.models.world import (
    EventImportance,
    EventStatus,
    TimeContext,
    World,
    WorldEnvironment,
    WorldEvent,
    WorldObject,
    WorldTimeMode,
)
from app.services.world.context_selector import build_world_context, render_world_section

NOW = datetime(2026, 9, 1, 22, 40)


def _time():
    return TimeContext(now=NOW, weekday="周二", part_of_day="late_night", time_mode=WorldTimeMode.REAL_SYNC)


def _world(**env):
    return World(
        world_id="home:default-user",
        user_id="default-user",
        current_location="home.kitchen",
        environment=WorldEnvironment(**env),
    )


def _object(name="西瓜", location="home.kitchen.fridge", state="cut", quantity=0.4):
    return WorldObject(
        id="watermelon_001",
        world_id="home:default-user",
        name=name,
        category="food",
        location_id=location,
        state=state,
        quantity=quantity,
    )


def _event(**overrides):
    defaults = {
        "id": "evt_1",
        "world_id": "home:default-user",
        "type": "interview",
        "title": "用户的面试",
        "importance": EventImportance.HIGH,
        "status": EventStatus.SCHEDULED,
        "due_at": datetime(2026, 9, 2, 10, 0),
    }
    defaults.update(overrides)
    return WorldEvent(**defaults)


def _build(world=None, entities=None, events=None):
    return build_world_context(
        world or _world(),
        entities if entities is not None else [_object()],
        events if events is not None else [_event()],
        _time(),
    )


def test_selection_includes_nearby_due_events_and_env():
    context = _build(_world(weather="rain", temperature_c=18.0))
    assert [obj.name for obj in context.nearby_objects] == ["西瓜"]
    assert context.salient_events[0].title == "用户的面试"
    assert context.environment.weather == "rain"
    assert context.location.current_name == "厨房"


def test_selection_excludes_far_objects_and_stale_events():
    context = _build(
        _world(),
        entities=[_object(name="旧箱子", location="home.attic")],
        events=[_event(event_id="evt_old", status=EventStatus.COMPLETED)],
    )
    assert context.nearby_objects == []
    assert context.salient_events == []


def test_render_none_when_no_world():
    assert render_world_section(None) is None


def test_render_contains_time_location_objects_events():
    text = render_world_section(_build(_world(weather="rain", temperature_c=18.0)))
    assert text.startswith("【当前世界】")
    assert "22:40" in text
    assert "家·厨房" in text
    assert "西瓜" in text
    assert "面试" in text
    assert "下着雨" in text


def test_render_empty_world_still_has_head():
    context = build_world_context(_world(), [], [], _time())
    text = render_world_section(context)
    assert text is not None
    assert "22:40" in text
    assert "家·厨房" in text


def test_render_respects_budget():
    context = _build(
        _world(weather="rain", temperature_c=18.0),
        events=[_event(event_id=f"evt_{i}", due_at=datetime(2026, 9, 2, 10, 0)) for i in range(3)],
    )
    text = render_world_section(context, budget=120)
    assert text is not None
    assert len(text) <= 120
    assert "22:40" in text
