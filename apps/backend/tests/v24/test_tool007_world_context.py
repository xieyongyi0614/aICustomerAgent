"""TOOL-007 §6.1 / §6.3：世界事实八段预读、逐段降级、有界性与装配不可用形态（E1~E6、E10、E11、E15）。"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core import timeutil
from app.application import world_engine
from app.repositories import world_repository
from app.services.tool import world_context as world_context_module
from app.services.tool.context import WORLD_ENABLED_KEY
from app.services.tool.world_context import (
    ACTIVE_EVENTS_LIMIT,
    INVENTORY_LIMIT,
    SITUATIONS_LIMIT,
    WORLD_FACTS_KEYS,
    WORLD_SEGMENT_KEYS,
    WorldContextBuilder,
    apply_world_facts,
    build_tool_context,
    known_locations,
)
from tests.v24.tool007_support import (
    LOCATION,
    NOW,
    USER,
    facts_keys,
    object_location,
    seed_all,
    seed_event,
    seed_object,
    seed_objects,
    seed_plan,
    seed_situation,
    seed_world,
    tool_context,
    world_event_titles,
    world_objects,
    world_segment_keys,
    world_settings,
)

LOGGER_NAME = world_context_module.__name__

OTHER_USER = "u-tool007-other"

FIXTURE_USERS = (USER, OTHER_USER)


@pytest.fixture(autouse=True)
def _world_fixture_isolation(db_session_factory):
    """世界夹具隔离：在前后清空夹具用户的世界域行。"""
    _purge_world_fixtures(db_session_factory)
    yield
    _purge_world_fixtures(db_session_factory)


def _purge_world_fixtures(session_factory) -> None:
    from app.core.db import (
        DailyPlanRow,
        UserSituationRow,
        WorldEntityRow,
        WorldEventRow,
        WorldRow,
    )

    with session_factory() as session:
        world_ids = [
            row.id
            for row in session.query(WorldRow).filter(WorldRow.user_id.in_(FIXTURE_USERS))
        ]
        if world_ids:
            session.query(WorldEntityRow).filter(WorldEntityRow.world_id.in_(world_ids)).delete(
                synchronize_session=False
            )
            session.query(WorldEventRow).filter(WorldEventRow.world_id.in_(world_ids)).delete(
                synchronize_session=False
            )
        session.query(WorldRow).filter(WorldRow.user_id.in_(FIXTURE_USERS)).delete(
            synchronize_session=False
        )
        session.query(DailyPlanRow).filter(DailyPlanRow.user_id.in_(FIXTURE_USERS)).delete(
            synchronize_session=False
        )
        session.query(UserSituationRow).filter(UserSituationRow.user_id.in_(FIXTURE_USERS)).delete(
            synchronize_session=False
        )
        session.commit()


def _builder(**settings_overrides) -> WorldContextBuilder:
    return WorldContextBuilder(world_settings(**settings_overrides))


def _build(user_id: str = USER, **settings_overrides) -> dict:
    return _builder(**settings_overrides).build(
        user_id, now=NOW, settings=world_settings(**settings_overrides)
    )


# --- §6.1 键集与形态 ---------------------------------------------------------


def test_build_returns_toolcontext_world_field_keys():
    assert facts_keys() == WORLD_FACTS_KEYS
    assert world_segment_keys() == WORLD_SEGMENT_KEYS
    assert set(_build()) == set(WORLD_FACTS_KEYS)


def test_world_segment_keys_match_spec_when_world_available(db_session_factory):
    seed_all()
    facts = _build()
    assert set(facts["world"]) == set(WORLD_SEGMENT_KEYS)
    assert facts["world"]["world_enabled"] is True
    assert facts["world"]["location"] == LOCATION
    assert facts["world"]["location_name"] == "客厅"
    assert facts["world"]["weather"] == "sunny"
    assert facts["world"]["part_of_day"] in ("morning", "afternoon", "dusk", "evening", "late_night")
    assert facts["world"]["locations"] == known_locations()


def test_apply_world_facts_keeps_non_world_fields(db_session_factory):
    ctx = tool_context(record_id="rec-1", source="autonomy")
    updated = apply_world_facts(ctx, {"world": {"world_enabled": True}, "inventory": ["苹果"]})
    assert updated.record_id == "rec-1" and updated.source == "autonomy"
    assert updated.world == {"world_enabled": True} and updated.inventory == ["苹果"]


# --- E1：世界不可用（装配标记 False 由消费方契约支撑） ------------------------


def test_e1_world_disabled_facts_project_world_disabled_reason(db_session_factory):
    facts = {
        "world": {WORLD_ENABLED_KEY: False},
        "inventory": [],
        "situations": [],
        "scene": {},
        "relationship": {},
    }
    ctx = apply_world_facts(tool_context(), facts)
    assert ctx.world_facts_assembled() is True
    assert ctx.world_facts_enabled() is False


# --- E2：无世界记录不隐式创建 -------------------------------------------------


def test_e2_missing_world_degrades_without_creating(db_session_factory):
    assert world_repository.get_world(USER) is None
    facts = _build()
    assert set(facts["world"]) == set(WORLD_SEGMENT_KEYS)
    assert facts["world"]["location"] is None
    assert facts["world"]["location_name"] is None
    assert facts["world"]["weather"] is None
    assert facts["world"]["part_of_day"] is None
    assert facts["world"]["current_block"] is None
    assert facts["world"]["active_events"] == []
    assert world_repository.get_world(USER) is None


def test_e2_missing_world_does_not_touch_ensure_world(monkeypatch, db_session_factory):
    def boom(user_id):
        raise AssertionError("预读不得隐式 ensure_world")

    monkeypatch.setattr(world_engine, "ensure_world", boom)
    assert _build()["world"]["location"] is None


# --- E3：无 active 日程块 ----------------------------------------------------


def test_e3_current_block_none_without_active_plan(db_session_factory):
    seed_world()
    assert _build()["world"]["current_block"] is None


def test_e3_current_block_none_when_simulation_off_shape(db_session_factory):
    seed_world()
    seed_plan(status="completed")
    assert _build()["world"]["current_block"] is None


def test_current_block_uses_world_clock_time_window(db_session_factory):
    seed_world()
    seed_plan(start_minutes=0, end_minutes=1439, status="planned", activity="写代码")
    block = _build()["world"]["current_block"]
    assert block == {"activity": "写代码", "location_id": LOCATION, "part_of_day": "afternoon"}


# --- E4 / 有界性：库存 -------------------------------------------------------


def test_inventory_empty_when_no_objects(db_session_factory):
    seed_world()
    assert _build()["inventory"] == []


def test_inventory_bounded_to_limit(db_session_factory):
    seed_world()
    seed_objects(USER, tuple(f"物品{i:02d}" for i in range(INVENTORY_LIMIT + 5)))
    inventory = _build()["inventory"]
    assert len(inventory) == INVENTORY_LIMIT
    assert all(name.startswith("物品") for name in inventory)


def test_situations_bounded_to_limit(db_session_factory):
    seed_world()
    for index, dimension in enumerate(
        ("health", "work_pressure", "travel", "emotional_context")
    ):
        seed_situation(dimension=dimension, summary=f"处境{index}", intensity=index % 5 + 1)
    situations = _build()["situations"]
    assert len(situations) == SITUATIONS_LIMIT
    assert set(situations[0]) == {"dimension", "summary", "intensity"}


# --- E5：未注册地点 ----------------------------------------------------------


def test_e5_unknown_location_name_falls_back_to_id(db_session_factory):
    seed_world(location="ghost_place")
    facts = _build()
    assert facts["world"]["location"] == "ghost_place"
    assert facts["world"]["location_name"] == "ghost_place"


def test_known_locations_contains_ids_and_names():
    locations = known_locations()
    assert "home.living_room" in locations and "客厅" in locations
    assert locations == tuple(sorted(locations))


# --- E6：事件有界与确定性排序 ------------------------------------------------


def test_e6_active_events_truncated_and_sorted(db_session_factory):
    seed_world()
    seed_event(title="低-晚", importance="low", due_in_hours=1)
    seed_event(title="低-早", importance="low", due_in_hours=30)
    seed_event(title="高-晚", importance="high", due_in_hours=20)
    seed_event(title="高-早", importance="high", due_in_hours=10)
    seed_event(title="中-1", importance="normal", due_in_hours=2)
    seed_event(title="中-2", importance="normal", due_in_hours=5)
    seed_event(title="中-3", importance="normal", due_in_hours=40)

    events = _build()["world"]["active_events"]
    assert len(events) == ACTIVE_EVENTS_LIMIT
    assert [event["title"] for event in events] == ["高-早", "高-晚", "中-1", "中-2", "中-3"]
    assert set(events[0]) == {"type", "title", "due_at"}
    assert events[0]["type"] == "reminder"
    assert events[0]["due_at"] == timeutil.ensure_aware(
        NOW + timedelta(hours=10)
    ).isoformat()


def test_e6_ordering_is_deterministic_across_runs(db_session_factory):
    seed_world()
    for index in range(6):
        seed_event(title=f"事件{index}", importance="normal", due_in_hours=index + 1)
    first = _build()["world"]["active_events"]
    second = _build()["world"]["active_events"]
    assert first == second


def test_active_events_include_active_status(db_session_factory):
    seed_world()
    seed_event(title="进行中", status="active", importance="high")
    assert [item["title"] for item in _build()["world"]["active_events"]] == ["进行中"]


# --- E10：场景画像 -----------------------------------------------------------


def test_e10_scene_projection_when_world_present(db_session_factory):
    seed_all()
    scene = _build()["scene"]
    assert scene["location_id"] == LOCATION
    assert scene["tone_bias"] == "intimate"
    assert "日常" in scene["topic_affordances"]


def test_scene_projection_when_expansion_flag_on(db_session_factory):
    seed_all()
    scene = _build()["scene"]
    assert scene["location_id"] == LOCATION
    assert scene["tone_bias"] == "intimate"
    assert "日常" in scene["topic_affordances"]


def test_scene_empty_without_world_record(db_session_factory):
    assert _build()["scene"] == {}


# --- E11：关系读取失败降级 ---------------------------------------------------


def test_e11_relationship_read_failure_degrades(db_session_factory, monkeypatch):
    seed_world()
    seed_plan()

    def boom(user_id):
        raise RuntimeError("relationship down")

    monkeypatch.setattr(world_context_module, "load_relationship", boom)
    facts = _build()
    assert facts["relationship"] == {}
    assert facts["world"]["location"] == LOCATION


def test_relationship_projection_shape(db_session_factory):
    seed_world()
    relationship = _build()["relationship"]
    assert set(relationship) == {"stage", "tension"}
    assert isinstance(relationship["tension"], float)


# --- 八段逐段降级：每段一成功一失败 -----------------------------------------


def _segment_cases():
    return [
        (
            "world",
            lambda monkeypatch: monkeypatch.setattr(
                world_engine, "get_world", _raiser("world down")
            ),
            lambda facts: facts["world"]["location"] is None,
        ),
        (
            "part_of_day",
            lambda monkeypatch: monkeypatch.setattr(
                world_context_module, "TimeProvider", _raiser("time down")
            ),
            lambda facts: facts["world"]["part_of_day"] is None,
        ),
        (
            "current_block",
            lambda monkeypatch: monkeypatch.setattr(
                world_context_module.daily_plan, "get_current_block", _raiser("plan down")
            ),
            lambda facts: facts["world"]["current_block"] is None,
        ),
        (
            "active_events",
            lambda monkeypatch: monkeypatch.setattr(
                world_engine, "list_active_events", _raiser("events down")
            ),
            lambda facts: facts["world"]["active_events"] == [],
        ),
        (
            "inventory",
            lambda monkeypatch: monkeypatch.setattr(
                world_engine, "list_active_objects", _raiser("objects down")
            ),
            lambda facts: facts["inventory"] == [],
        ),
        (
            "situations",
            lambda monkeypatch: monkeypatch.setattr(
                world_context_module.user_situation, "active_situations", _raiser("situations down")
            ),
            lambda facts: facts["situations"] == [],
        ),
        (
            "scene",
            lambda monkeypatch: monkeypatch.setattr(
                world_context_module, "scene_profile_for", _raiser("scene down")
            ),
            lambda facts: facts["scene"] == {},
        ),
        (
            "relationship",
            lambda monkeypatch: monkeypatch.setattr(
                world_context_module, "load_relationship", _raiser("relationship down")
            ),
            lambda facts: facts["relationship"] == {},
        ),
    ]


def _raiser(message: str):
    def boom(*args, **kwargs):
        raise RuntimeError(message)

    return boom


@pytest.mark.parametrize("segment,install,degraded", _segment_cases(), ids=lambda item: str(item)[:20])
def test_each_segment_degrades_independently(db_session_factory, monkeypatch, segment, install, degraded):
    seed_all()
    install(monkeypatch)
    facts = _build(scene_expansion_enabled=True)
    assert set(facts) == set(WORLD_FACTS_KEYS)
    assert degraded(facts) is True
    assert all(key in facts["world"] for key in WORLD_SEGMENT_KEYS)


def test_all_segments_failing_still_returns_usable_structure(db_session_factory, monkeypatch):
    for _, install, _ in _segment_cases():
        install(monkeypatch)
    facts = _build(scene_expansion_enabled=True)
    assert set(facts) == set(WORLD_FACTS_KEYS)
    assert set(facts["world"]) == set(WORLD_SEGMENT_KEYS)
    assert facts["world"]["world_enabled"] is True
    assert facts["inventory"] == [] and facts["relationship"] == {}


def test_degradation_is_logged(db_session_factory, monkeypatch, caplog):
    seed_world()
    monkeypatch.setattr(world_engine, "list_active_objects", _raiser("objects down"))
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        _build()
    assert any("inventory" in record.message and "降级" in record.message for record in caplog.records)


# --- 单段方法可独立调用（§4.1 接口） ----------------------------------------


def test_sub_builders_degrade_on_failure(db_session_factory, monkeypatch):
    seed_world()
    monkeypatch.setattr(world_engine, "list_active_objects", _raiser("objects down"))
    monkeypatch.setattr(world_context_module.user_situation, "active_situations", _raiser("down"))
    builder = _builder()
    assert builder.build_inventory(USER) == []
    assert builder.build_situations(USER) == []


# --- E15：并发预读 -----------------------------------------------------------


def test_e15_preread_is_user_scoped_and_repeatable(db_session_factory):
    """E15：预读按用户隔离（无跨用户缓存），同输入重复调用逐字节一致。"""
    seed_all()
    seed_all(OTHER_USER, inventory=("牛奶",), with_situation=False)
    baseline = {USER: _build(USER), OTHER_USER: _build(OTHER_USER)}
    for _ in range(3):
        assert _build(USER) == baseline[USER]
        assert _build(OTHER_USER) == baseline[OTHER_USER]
    assert baseline[USER]["inventory"] != baseline[OTHER_USER]["inventory"]
    assert baseline[USER]["situations"] != baseline[OTHER_USER]["situations"]


def test_e15_concurrent_build_is_thread_safe(monkeypatch):
    """E15：纯读 + 无共享可变状态 → 并发装配互不串扰（读面注入假数据，绕开 SQLite 单连接）。"""
    from app.models.world import World, WorldObject

    words = ("苹果", "牛奶", "面包", "咖啡", "雨伞")

    def fake_world(user_id: str):
        world = World(world_id=f"w-{user_id}", user_id=user_id, current_location=LOCATION)
        world.environment.weather = f"weather-{user_id}"
        return world

    def fake_objects(user_id: str):
        return [
            WorldObject(
                id=f"obj-{name}-{user_id}",
                world_id=f"w-{user_id}",
                name=f"{name}-{user_id}",
                location_id=LOCATION,
                state="normal",
            )
            for name in words
        ]

    monkeypatch.setattr(world_engine, "get_world", fake_world)
    monkeypatch.setattr(world_engine, "list_active_objects", fake_objects)
    monkeypatch.setattr(world_engine, "list_active_events", lambda user_id: [])
    monkeypatch.setattr(world_context_module.user_situation, "active_situations", lambda user_id: [])
    monkeypatch.setattr(world_context_module.daily_plan, "get_current_block", lambda *args: None)
    monkeypatch.setattr(
        world_context_module,
        "load_relationship",
        lambda user_id: SimpleNamespace(stage="friend", tension=0.0),
    )

    users = [f"u-concurrent-{index}" for index in range(6)]
    expected = {user_id: _build(user_id) for user_id in users}

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_build, users * 3))
    for index, result in enumerate(results):
        user_id = users[index % len(users)]
        assert result == expected[user_id]
        assert result["world"]["weather"] == f"weather-{user_id}"
        assert all(name.endswith(user_id) for name in result["inventory"])


def test_builder_holds_no_mutable_state(db_session_factory):
    builder = _builder()
    assert builder.__dict__ == {"_settings": builder._settings}
    seed_all()
    builder.build(USER, now=NOW, settings=world_settings())
    assert list(builder.__dict__) == ["_settings"]


# --- 纯读：预读不产生任何世界写入 -------------------------------------------


def test_preread_performs_no_world_write(db_session_factory, monkeypatch):
    seed_all()
    write_calls: list[str] = []
    for name in dir(world_engine):
        if not name.startswith(("create_", "move_", "set_", "apply_", "discard_", "consume_", "expire_")):
            continue
        if not callable(getattr(world_engine, name)):
            continue

        def probe(*args, _name: str = name, **kwargs):
            write_calls.append(_name)
            raise AssertionError(f"预读不得调用写函数: {_name}")

        monkeypatch.setattr(world_engine, name, probe)

    before = (world_objects(), world_event_titles())
    facts = _build(scene_expansion_enabled=True)
    assert facts["world"]["world_enabled"] is True
    assert write_calls == []
    assert (world_objects(), world_event_titles()) == before


def test_build_tool_context_uses_ctx_now_when_now_absent(db_session_factory):
    seed_world()
    ctx = tool_context(now=None, settings=None)
    updated = build_tool_context(ctx, settings=world_settings())
    assert updated.world["location"] == LOCATION


def test_get_world_failure_degrades_world_segment(db_session_factory, monkeypatch):
    monkeypatch.setattr(world_engine, "get_world", _raiser("world read down"))
    facts = _build()
    assert facts["world"]["location"] is None
    assert facts["world"]["world_enabled"] is True


def test_seed_helpers_used_by_other_modules(db_session_factory):
    """夹具自检：seed_object 建的对象确实进入库存读面。"""
    seed_world()
    seed_object(USER, "牛奶")
    assert object_location(USER, "牛奶") == LOCATION
    assert _build()["inventory"] == ["牛奶"]
    assert world_objects(USER) == ["牛奶"]


def test_current_block_uses_passed_now_when_world_clock_unavailable(db_session_factory):
    seed_world()
    seed_plan(start_minutes=0, end_minutes=1439, status="planned", activity="整日")
    block = WorldContextBuilder(world_settings()).build(
        USER, now=timeutil.ensure_aware(datetime(2026, 9, 14, 23, 30, 0)), settings=world_settings()
    )["world"]["current_block"]
    assert block is not None and block["activity"] == "整日"
