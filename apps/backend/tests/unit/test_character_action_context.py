"""ACTION-005 最近世界变化派生与渲染（纯函数，无 IO）。"""

from datetime import datetime

from app.models.world import (
    EventImportance,
    EventSource,
    EventStatus,
    TimeContext,
    World,
    WorldEnvironment,
    WorldEvent,
    WorldObject,
    WorldTimeMode,
)
from app.services.world.context_selector import (
    build_world_context,
    recent_world_changes_from_events,
    render_world_section,
)

NOW = datetime(2026, 9, 1, 22, 40)


def _time():
    return TimeContext(now=NOW, weekday="周二", part_of_day="late_night", time_mode=WorldTimeMode.REAL_SYNC)


def _world():
    return World(
        world_id="home:default-user",
        user_id="default-user",
        current_location="home.kitchen",
        environment=WorldEnvironment(),
    )


def _object(name="鸡蛋", location="home.kitchen.fridge", quantity=6.0):
    return WorldObject(
        id=f"obj_{name}",
        world_id="home:default-user",
        name=name,
        category="food",
        location_id=location,
        state="intact",
        quantity=quantity,
    )


def _change_event(created_at, title, dedupe_key="", event_type="character_action"):
    return WorldEvent(
        id=f"evt_{created_at.timestamp()}",
        world_id="home:default-user",
        type=event_type,
        title=title,
        importance=EventImportance.LOW,
        status=EventStatus.COMPLETED,
        payload={"dedupe_key": dedupe_key} if dedupe_key else {},
        source=EventSource.CHARACTER,
        created_at=created_at,
    )


def test_derivation_filters_and_orders_by_newest_first():
    events = [
        _change_event(datetime(2026, 9, 1, 10), "消耗牛奶 ×1", "a"),
        _change_event(datetime(2026, 9, 1, 12), "做出面", "b"),
        _change_event(datetime(2026, 9, 1, 11), "旧箱子移到阁楼", "c", event_type="manual"),
    ]
    assert recent_world_changes_from_events(events) == ["做出面", "消耗牛奶 ×1"]


def test_derivation_dedupes_by_key_keeping_newest():
    events = [
        _change_event(datetime(2026, 9, 1, 10), "消耗鸡蛋 ×1", "dup"),
        _change_event(datetime(2026, 9, 1, 11), "消耗鸡蛋 ×2", "dup"),
    ]
    assert recent_world_changes_from_events(events) == ["消耗鸡蛋 ×2"]


def test_derivation_respects_limit_and_skips_empty_titles():
    events = [
        _change_event(datetime(2026, 9, 1, 10), "消耗鸡蛋 ×1", "a"),
        _change_event(datetime(2026, 9, 1, 11), "", "b"),
        _change_event(datetime(2026, 9, 1, 12), "做出面", "c"),
    ]
    assert recent_world_changes_from_events(events, limit=1) == ["做出面"]
    assert recent_world_changes_from_events(events, limit=2) == ["做出面", "消耗鸡蛋 ×1"]


def test_derivation_empty_input():
    assert recent_world_changes_from_events([]) == []


def test_build_world_context_default_is_empty():
    context = build_world_context(_world(), [_object()], [], _time())
    assert context.recent_world_changes == []


def test_build_world_context_with_change_events():
    change = _change_event(datetime(2026, 9, 1, 12), "消耗鸡蛋 ×2", "dup")
    context = build_world_context(
        _world(), [_object()], [], _time(), change_events=[change], changes_limit=3
    )
    assert context.recent_world_changes == ["消耗鸡蛋 ×2"]


def test_render_inserts_block_between_inventory_and_events():
    change = _change_event(datetime(2026, 9, 1, 12), "消耗鸡蛋 ×2", "dup")
    context = build_world_context(
        _world(), [_object()], [], _time(), change_events=[change], changes_limit=3
    )
    text = render_world_section(context)
    assert "最近世界变化：" in text
    assert "  - 消耗鸡蛋 ×2" in text
    assert "　" not in text
    assert text.index("鸡蛋 × 6") < text.index("最近世界变化：")
    assert "【当前世界】" == text.split("\n")[0]


def test_render_dedupes_recent_and_notes_prefer_recent():
    change = _change_event(datetime(2026, 9, 1, 12), "消耗鸡蛋 ×2", "dup")
    context = build_world_context(
        _world(),
        [_object()],
        [],
        _time(),
        change_events=[change],
        changes_limit=3,
    )
    context.notes = ["消耗鸡蛋 ×2", "鸡蛋已从冰箱取出"]
    text = render_world_section(context)
    assert text.count("消耗鸡蛋 ×2") == 1
    assert text.index("  - 消耗鸡蛋 ×2") < text.index("鸡蛋已从冰箱取出")


def test_render_respects_budget_keeping_guide_and_inventory():
    changes = [
        _change_event(datetime(2026, 9, 1, 12 - i), f"动作_{i}", f"k{i}")
        for i in range(5)
    ]
    context = build_world_context(
        _world(), [_object()], [], _time(), change_events=changes, changes_limit=5
    )
    text = render_world_section(context, budget=120)
    assert text is not None
    assert len(text) <= 120
    assert "家里的物品、数量、位置与可消耗状态" in text
    assert "鸡蛋" in text


def test_render_gate_off_byte_identical():
    baseline = build_world_context(_world(), [_object()], [], _time())
    gated = build_world_context(
        _world(), [_object()], [], _time(), change_events=[], changes_limit=3
    )
    assert render_world_section(baseline) == render_world_section(gated)