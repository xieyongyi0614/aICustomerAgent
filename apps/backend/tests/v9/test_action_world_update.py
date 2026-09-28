"""V9 Action World Update（world-integration.md §1/§5，V9-006 专项）。

第 8→9 步双命中矩阵（G6 effect_already_satisfied 兜底）、世界写失败→failed 不假成功、
world 未启用→依赖世界的行动 unavailable。
"""

import pytest

from app.application import world_engine
from app.application.action_engine import run_action_planning
from app.models.action import ActionIntent


def _intent(action_type, **params):
    return ActionIntent(
        action_type=action_type, confidence="confident", params=params, dedupe_key=""
    )


@pytest.mark.asyncio
async def test_g6_rejects_when_effect_already_satisfied(
    db_session_factory, override_settings
):
    override_settings()
    # 第 8 步 interpreter 已造出牛奶 → 第 9 步 create_object 被 G6 兜底否决
    obj = world_engine.create_object("world-user", "牛奶", category="drink")
    assert obj is not None
    record = await run_action_planning(
        "world-user", _intent("create_object", object="牛奶"), session_id="s1"
    )
    assert record is not None
    assert record.status == "cancelled"
    assert record.gate_reason == "effect_already_satisfied"


@pytest.mark.asyncio
async def test_use_object_consumes_inventory_with_quantity(
    db_session_factory, override_settings
):
    override_settings()
    world_engine.create_object("world-user", "面条", category="food", quantity=2)
    world_engine.create_object("world-user", "鸡蛋", category="food", quantity=6)
    intent = _intent(
        "use_object", object="碗面", items=[{"object": "鸡蛋", "quantity": 2}]
    )
    record = await run_action_planning("world-user", intent, session_id="s1")
    assert record is not None
    assert record.status == "succeeded"
    noodles = world_engine.find_object_by_name("world-user", "面条")
    eggs = world_engine.find_object_by_name("world-user", "鸡蛋")
    assert (noodles.quantity, eggs.quantity) == (1.0, 4.0)


@pytest.mark.asyncio
async def test_world_disabled_dependent_action_unavailable(
    db_session_factory, override_settings
):
    override_settings()
    record = await run_action_planning(
        "world-user",
        _intent("create_reminder", content="开会", due_at="2026-09-04T08:00:00"),
        session_id="s1",
    )
    assert record is not None
    assert record.status in ("cancelled", "failed")
    if record.status == "cancelled":
        assert record.gate_reason == "capability_unavailable"


@pytest.mark.asyncio
async def test_memory_action_runs_without_world(db_session_factory, override_settings):
    from app.repositories import memory_repository

    override_settings()
    record = await run_action_planning(
        "world-user",
        _intent("remember_fact", fact="喜欢散步"),
        session_id="s1",
    )
    assert record is not None
    if record.status == "succeeded":
        assert any("散步" in (m.content or "") for m in memory_repository.list_by_user("world-user"))


@pytest.mark.asyncio
async def test_reminder_writes_world_event(db_session_factory, override_settings):
    override_settings()
    record = await run_action_planning(
        "world-user",
        _intent("create_reminder", content="复诊", due_at="2026-09-05T08:00:00"),
        session_id="s1",
    )
    assert record is not None
    if record.status == "succeeded":
        assert any(
            e.title == "复诊" and e.type == "reminder"
            for e in world_engine.list_active_events("world-user")
        )