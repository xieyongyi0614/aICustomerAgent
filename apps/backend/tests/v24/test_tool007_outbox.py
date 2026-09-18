"""TOOL-007 §6.2 / §6.3：工具产出的世界效果走 outbox 唯一写路径（E7、E8、E9）。

验证要点：工具（经 `run_action_planning` 的工具执行路径）产出的 `deferred_world_op`
只有经 `save_record_with_outbox` → `outbox_consumer._apply_world_op` → `world_engine`
才落库；消费器**零新增消费逻辑**，未知 op / 世界不可用进重试，重放不产生第二条事件。
"""

import pytest

from datetime import timedelta

from app.application import outbox_consumer, world_engine
from app.application.action_engine import run_action_planning
from app.models.action import ActionIntent
from app.repositories import action_repository, outbox_repository
from app.services.tool import registry as tool_registry
from tests.v24.tool007_support import (
    NOW,
    USER,
    object_location,
    seed_all,
    seed_object,
    seed_world,
    world_event_titles,
)

MOVE_OBJECT = "move_object"
CREATE_REMINDER = "create_reminder"


def _intent(action_type: str, **params) -> ActionIntent:
    return ActionIntent(
        action_type=action_type,
        confidence="confident",
        params=params,
        dedupe_key=f"tool007:{action_type}",
    )


@pytest.fixture(autouse=True)
def _tool_path_env(override_settings, monkeypatch):
    """总闸 + outbox 双开；自动播种关闭（库存夹具确定）。"""
    monkeypatch.setattr(tool_registry, "_registry", None)
    override_settings(
        world_enabled="true",
        action_enabled="true",
        action_outbox_enabled="true",
        world_household_autoseed_enabled="false",
        observability_persist_enabled="false",
    )
    yield
    monkeypatch.setattr(tool_registry, "_registry", None)


def _outbox_row(record_id: str):
    return outbox_repository.get(record_id)


def _caller_recording_engine(monkeypatch) -> list[tuple[str, str]]:
    """记录世界写函数的调用方模块（验证唯一写路径）。"""
    import inspect

    calls: list[tuple[str, str]] = []
    for name in ("move_object", "create_event", "create_object", "apply_object_action"):
        original = getattr(world_engine, name)

        def wrapper(*args, _name: str = name, _original=original, **kwargs):
            caller = next(
                frame.frame.f_globals.get("__name__", "")
                for frame in inspect.stack()
                if frame.frame.f_globals.get("__name__", "") != __name__
            )
            calls.append((_name, caller))
            return _original(*args, **kwargs)

        monkeypatch.setattr(world_engine, name, wrapper)
    return calls


# --- 唯一写路径：工具只投递，消费器才落库 ------------------------------------


@pytest.mark.asyncio
async def test_tool_world_effect_lands_only_after_consume(db_session_factory, monkeypatch):
    seed_all()
    seed_object(USER, "牛奶")
    calls = _caller_recording_engine(monkeypatch)
    assert object_location(USER, "牛奶") == "home.living_room"

    record = await run_action_planning(
        USER,
        _intent(MOVE_OBJECT, object="牛奶", location="厨房"),
        session_id="s-tool007",
    )
    assert record is not None and record.status == "succeeded"
    assert record.steps[0]["tool_id"] == "world.object.move"
    assert calls == []
    assert object_location(USER, "牛奶") == "home.living_room"

    row = _outbox_row(record.id)
    assert row is not None and row.status == "pending"
    assert [op["op"] for op in row.payload["world_ops"]] == ["move_object"]
    assert row.payload["world_ops"][0]["args"][0] == USER

    stats = outbox_consumer.consume_pending(now=NOW)
    assert stats["consumed"] == 1
    assert object_location(USER, "牛奶") == "home.kitchen"
    assert [caller for _, caller in calls] == ["app.application.outbox_consumer"]
    assert _outbox_row(record.id).status == "consumed"


@pytest.mark.asyncio
async def test_tool_path_never_imports_world_repository(db_session_factory):
    """工具层零仓储依赖：工具产出仅含 op 名与参数（结构化投递，非落库对象）。"""
    seed_all()
    record = await run_action_planning(
        USER, _intent(MOVE_OBJECT, object="苹果", location="厨房"), session_id="s-tool007-2"
    )
    row = _outbox_row(record.id)
    op = row.payload["world_ops"][0]
    assert set(op) == {"op", "args"}
    assert isinstance(op["args"], list)


# --- E7：未知 op → 重试 / 死信（既有行为） -----------------------------------


def _insert_row(key: str, ops: list[dict], record_payload: dict) -> None:
    outbox_repository.insert(
        {
            "action_id": key,
            "user_id": USER,
            "record": record_payload,
            "world_ops": ops,
        },
        idempotency_key=key,
        now=NOW,
    )


@pytest.mark.asyncio
async def test_e7_unknown_op_goes_to_retry(db_session_factory, override_settings):
    override_settings(life_loop_outbox_max_attempts="3")
    seed_all()
    key = "act-tool007-e7"
    _insert_row(key, [{"op": "explode_world", "args": [USER]}], _record_payload())

    stats = outbox_consumer.consume_pending(now=NOW)
    assert stats["retried"] == 1 and stats["dead_lettered"] == 0
    row = outbox_repository.get(key)
    assert row.status == "pending" and row.attempts == 1
    assert "未知 world op" in (row.last_error or "")
    assert object_location(USER, "苹果") == "home.living_room"


@pytest.mark.asyncio
async def test_e7_unknown_op_dead_letters_after_backoff(db_session_factory, override_settings):
    override_settings(life_loop_outbox_max_attempts="3")
    seed_all()
    key = "act-tool007-e7-dl"
    _insert_row(key, [{"op": "explode_world", "args": [USER]}], _record_payload())
    for attempt in range(4):
        outbox_consumer.consume_pending(now=NOW + timedelta(hours=attempt))
    row = outbox_repository.get(key)
    assert row.status == "failed" and row.attempts == 3


def _record_payload() -> dict:
    """outbox 行内的 `record`（消费器关系段用）；工具路径产出的真实记录同构。"""
    from app.models.action import ActionRecord

    return ActionRecord(
        id="act-tool007-row",
        user_id=USER,
        action_type=MOVE_OBJECT,
        intent={"action_type": MOVE_OBJECT, "confidence": "confident", "params": {}},
        dedupe_key="tool007:row",
        params={},
        status="succeeded",
        created_at=NOW,
        updated_at=NOW,
    ).model_dump(mode="json")


# --- E8：世界不可用（返回 None）→ 重试；投递失败不回滚执行 --------------------


@pytest.mark.asyncio
async def test_e8_op_returning_none_goes_to_retry_without_rollback(
    db_session_factory, monkeypatch
):
    seed_all()
    record = await run_action_planning(
        USER, _intent(MOVE_OBJECT, object="苹果", location="厨房"), session_id="s-tool007-5"
    )
    assert record.status == "succeeded"

    monkeypatch.setattr(world_engine, "move_object", lambda *args, **kwargs: None)
    stats = outbox_consumer.consume_pending(now=NOW)
    assert stats["retried"] == 1
    row = _outbox_row(record.id)
    assert row.status == "pending" and row.attempts == 1
    assert "落库失败" in (row.last_error or "")

    saved = action_repository.get_record(record.id)
    assert saved.status == "succeeded"
    assert object_location(USER, "苹果") == "home.living_room"


@pytest.mark.asyncio
async def test_e8_world_write_failure_never_rolls_back_action(
    db_session_factory, monkeypatch, override_settings
):
    """投递失败不回滚执行（V9 纪律）：连续失败至死信，行动终态仍为 succeeded。"""
    override_settings(life_loop_outbox_max_attempts="3")
    seed_all()
    monkeypatch.setattr(world_engine, "move_object", lambda *args, **kwargs: None)
    record = await run_action_planning(
        USER, _intent(MOVE_OBJECT, object="苹果", location="厨房"), session_id="s-tool007-6"
    )
    assert record.status == "succeeded"
    for attempt in range(4):
        outbox_consumer.consume_pending(now=NOW + timedelta(hours=attempt))
    row = _outbox_row(record.id)
    assert row.status == "failed" and row.attempts == 3
    assert action_repository.get_record(record.id).status == "succeeded"
    assert object_location(USER, "苹果") == "home.living_room"


# --- E9：重放幂等（create_event 指纹） ---------------------------------------


@pytest.mark.asyncio
async def test_e9_replay_does_not_duplicate_world_event(db_session_factory):
    seed_world()
    record = await run_action_planning(
        USER,
        _intent(CREATE_REMINDER, content="复查", due_at=(NOW.replace(year=2027)).isoformat()),
        session_id="s-tool007-7",
    )
    assert record.status == "succeeded"
    assert record.steps[0]["tool_id"] == "builtin.reminder.create"
    assert world_event_titles(USER) == []

    outbox_consumer.consume_pending(now=NOW)
    assert world_event_titles(USER) == ["复查"]

    from app.core.db import OutboxEventRow

    with outbox_repository.SessionLocal() as session:
        session.query(OutboxEventRow).filter(
            OutboxEventRow.idempotency_key == record.id
        ).update({"status": "pending", "attempts": 0})
        session.commit()
    outbox_consumer.consume_pending(now=NOW)
    assert world_event_titles(USER) == ["复查"]


# --- 总闸 off：工具路径不接管，V9 直写路径保留（行为不变） --------------------


@pytest.mark.asyncio
async def test_flag_off_uses_v9_direct_path(db_session_factory, override_settings):
    seed_all()
    override_settings(action_outbox_enabled="false")
    record = await run_action_planning(
        USER,
        _intent(CREATE_REMINDER, content="复查", due_at=(NOW.replace(year=2027)).isoformat()),
        session_id="s-tool007-8",
    )
    assert record.status == "succeeded"
    assert "tool_id" not in record.steps[0]
    assert _outbox_row(record.id) is None
    assert "复查" in world_event_titles(USER)
