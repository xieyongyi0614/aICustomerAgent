"""V9-003 能力执行单测（capability-system.md §4）。"""

from datetime import datetime

import pytest

from app.core import timeutil
from app.application import world_engine
from app.repositories import memory_repository, world_repository
from app.services.action.capabilities import register_builtin
from app.services.action.registry import CapabilityRegistry, ExecutionContext

NOW = timeutil.ensure_aware(datetime(2026, 9, 3, 14, 0, 0))
USER = "u-action"


@pytest.fixture
def registry():
    reg = CapabilityRegistry()
    register_builtin(reg)
    return reg


@pytest.fixture
def ctx(registry):
    return ExecutionContext(user_id=USER, record_id="act_test", now=NOW)


@pytest.mark.asyncio
async def test_reminder_create_world_event(ctx, override_settings):
    override_settings()
    reminder = world_engine  # noqa: F841
    from app.services.action.capabilities.reminder import ReminderCapability

    result = await ReminderCapability().execute(
        "create", {"content": "开会", "due_at": "2026-09-04T08:00:00"}, ctx
    )
    assert result.status == "succeeded"
    world = world_engine.ensure_world(USER)
    event = world_repository.get_event(world.world_id, result.payload["world_event_id"])
    assert event is not None
    assert event.type == "reminder"
    assert event.title == "开会"
    assert event.due_at == timeutil.ensure_aware(
        datetime.fromisoformat("2026-09-04T08:00:00")
    )
    assert event.source.value == "autonomy"
    assert event.status.value == "scheduled"


@pytest.mark.asyncio
async def test_reminder_cancel(ctx, override_settings):
    override_settings()
    from app.services.action.capabilities.reminder import ReminderCapability

    cap = ReminderCapability()
    await cap.execute("create", {"content": "开会", "due_at": "2026-09-04T08:00:00"}, ctx)
    result = await cap.execute("cancel", {"target": "开会"}, ctx)
    assert result.status == "succeeded"
    assert result.payload["cancelled"] >= 1


@pytest.mark.asyncio
async def test_reminder_cancel_no_target_fails(ctx, override_settings):
    override_settings()
    from app.services.action.capabilities.reminder import ReminderCapability

    result = await ReminderCapability().execute("cancel", {"target": "不存在"}, ctx)
    assert result.status == "failed"
    assert result.payload["failure_kind"] == "permanent"


@pytest.mark.asyncio
async def test_memory_save_user_stated(ctx, override_settings):
    override_settings()
    from app.services.action.capabilities.memory import MemoryCapability

    result = await MemoryCapability().execute("save", {"fact": "我生日是7月30日"}, ctx)
    assert result.status == "succeeded"
    memory = memory_repository.get_memory(result.payload["memory_id"])
    assert memory is not None
    assert memory.source == "user_stated"
    assert "7月30日" in memory.content


@pytest.mark.asyncio
async def test_world_action_create_and_use(ctx, override_settings):
    override_settings()
    from app.services.action.capabilities.world_action import WorldActionCapability

    cap = WorldActionCapability()
    created = await cap.execute("create", {"object": "面包"}, ctx)
    assert created.status == "succeeded"
    assert created.payload["name"] == "面包"

    cut = await cap.execute("use", {"object": "面包", "action": "cut"}, ctx)
    assert cut.status == "succeeded"
    used = await cap.execute("use", {"object": "面包", "action": "eat"}, ctx)
    assert used.status == "succeeded"
    assert used.payload["quantity"] < 5


@pytest.mark.asyncio
async def test_world_action_move(ctx, override_settings):
    override_settings()
    from app.services.action.capabilities.world_action import WorldActionCapability

    cap = WorldActionCapability()
    await cap.execute("create", {"object": "牛奶"}, ctx)
    moved = await cap.execute("move", {"object": "牛奶", "location": "厨房"}, ctx)
    assert moved.status == "succeeded"
    assert "kitchen" in moved.payload["location_id"]


@pytest.mark.asyncio
async def test_world_action_move_unknown_location(ctx, override_settings):
    override_settings()
    from app.services.action.capabilities.world_action import WorldActionCapability

    await WorldActionCapability().execute("create", {"object": "牛奶"}, ctx)
    moved = await WorldActionCapability().execute("move", {"object": "牛奶", "location": "火星"}, ctx)
    assert moved.status == "failed"


@pytest.mark.asyncio
async def test_environment_query_readonly(ctx, override_settings):
    override_settings()
    from app.services.action.capabilities.environment_query import EnvironmentQueryCapability

    world_engine.set_environment(USER, weather="晴", temperature_c=26.0)
    before = world_engine.get_world(USER).model_copy(deep=True)
    result = await EnvironmentQueryCapability().execute("query", {}, ctx)
    assert result.status == "succeeded"
    assert result.payload["weather"] == "晴"
    assert result.payload["simulated"] is True
    after = world_engine.get_world(USER)
    assert after.environment.weather == before.environment.weather
    assert after.updated_at == before.updated_at


async def test_search_unavailable_and_notification_wired(ctx):
    """检索无可用来源（明确降级）；通知能力已接线（V2.4.0 起不再整体 unavailable）。"""
    from app.services.action.capabilities.notification import NotificationCapability
    from app.services.action.capabilities.search import SearchCapability

    search = await SearchCapability().execute("query", {"query": "x"}, ctx)
    assert search.status == "unavailable"
    assert search.payload["reason_kind"] == "source_not_configured"
    assert (await NotificationCapability().execute("send", {"content": "x"}, ctx)).status == (
        "succeeded"
    )
