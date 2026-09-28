"""V9-009 Autonomy Integration（autonomy-integration.md §2~§5，H-A5/H-A6）。

覆盖：due_action 触发器 poll_due_actions、mark_action_reported 幂等置位、
PolicySnapshot.action_facts 注入（A1/A2 在 test_action_maintenance 细测）、
自治产行动分支零路径与开启路径。
"""

from datetime import datetime, timedelta

import pytest

from app.application import world_engine
from app.application.autonomy_engine import (
    _autonomy_action_today,
    _produce_autonomy_action,
)
from app.models.autonomy import AutonomyVerdict, TriggerSignal
from app.models.world import EventStatus
from app.repositories import action_repository, world_repository
from app.services import trigger_evaluator

NOW = datetime(2026, 9, 3, 14, 0, 0)
USER = "auto-action-user"


def _seed_due_reminder(user_id: str, due: datetime, title: str = "开会"):
    world = world_engine.ensure_world(user_id)
    event = world_engine.create_event(
        user_id, "reminder", title=title, due_at=due
    )
    event.status = EventStatus.ACTIVE
    event.due_at = due
    world_repository.save_event(event)
    return event


def _verdict(intention="check_in") -> AutonomyVerdict:
    return AutonomyVerdict(
        decision="act",
        reason="触发检查，存在 check_in 目标",
        trigger=TriggerSignal(
            type="conversation_inactivity",
            user_id=USER,
            detected_at=NOW,
            dedupe_key="d1",
        ),
        goal_id="goal-1",
        intention=intention,
    )


@pytest.mark.asyncio
async def test_poll_due_actions_disabled_empty(override_settings, db_session_factory):
    override_settings()
    assert trigger_evaluator.poll_due_actions(USER, NOW) is None


@pytest.mark.asyncio
async def test_poll_due_actions_hits_due_reminder(override_settings, db_session_factory):
    override_settings()
    _seed_due_reminder(USER, due=NOW - timedelta(minutes=1))
    signal = trigger_evaluator.poll_due_actions(USER, NOW)
    assert signal is not None
    assert signal.type == "action_due"
    assert signal.dedupe_key.startswith("action_due:")
    assert signal.context["title"] == "开会"


@pytest.mark.asyncio
async def test_poll_due_actions_ignores_future(override_settings, db_session_factory):
    override_settings()
    _seed_due_reminder(USER, due=NOW + timedelta(hours=2))
    assert trigger_evaluator.poll_due_actions(USER, NOW) is None


@pytest.mark.asyncio
async def test_mark_action_reported_idempotent(override_settings, db_session_factory):
    override_settings()
    event = _seed_due_reminder(USER, due=NOW - timedelta(minutes=1))
    assert trigger_evaluator.poll_due_actions(USER, NOW) is not None
    trigger_evaluator.mark_action_reported(USER, event.id)
    assert trigger_evaluator.poll_due_actions(USER, NOW) is None


@pytest.mark.asyncio
async def test_produce_autonomy_action_disabled_zero_path(
    override_settings, db_session_factory
):
    override_settings(autonomy_action_enabled=False)
    produced = await _produce_autonomy_action(
        _verdict(), USER, session_id="s1", now=NOW
    )
    assert produced is False
    assert action_repository.list_records(USER) == []


@pytest.mark.asyncio
async def test_produce_autonomy_action_enabled_creates_record(
    override_settings, db_session_factory
):
    override_settings(
        autonomy_action_enabled=True
    )
    produced = await _produce_autonomy_action(
        _verdict(), USER, session_id="s1", now=NOW
    )
    assert produced is True
    records = [r for r in action_repository.list_records(USER) if r.source == "autonomy"]
    assert len(records) == 1
    assert records[0].action_type == "create_reminder"


@pytest.mark.asyncio
async def test_autonomy_action_daily_limit(override_settings, db_session_factory):
    override_settings(
        autonomy_action_enabled=True,
        autonomy_action_daily_limit=1,
    )
    assert await _produce_autonomy_action(_verdict(), USER, "s1", NOW) is True
    # 当日第二条被额度拦下
    assert await _produce_autonomy_action(_verdict(), USER, "s1", NOW) is False
    assert _autonomy_action_today(USER, NOW) >= 1