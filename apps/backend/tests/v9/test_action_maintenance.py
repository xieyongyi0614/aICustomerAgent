"""V9 Maintenance Loop & Autonomy action_facts（V9-005, autonomy-integration.md §2）。

验证维护循环门控、过期计划清理、collect_facts 事实包、A1/A2 理由追加。
"""

from datetime import datetime, timedelta

import pytest

from app.application.action_engine import (
    collect_facts,
    _expire_planned,
    _process_due_retries,
)
from app.application.action_engine import new_record
from app.models.action import ActionIntent
from app.repositories import action_repository
from app.services.autonomy_policy import (
    AutonomyVerdict,
    PolicySnapshot,
    _apply_action_adjustments,
)
from app.models.autonomy import TriggerSignal


def _intent(action_type="create_reminder", **params):
    return ActionIntent(action_type=action_type, confidence="confident", params=params, dedupe_key="")


def _verdict():
    return AutonomyVerdict(
        decision="act",
        reason="触发检查，存在 check_in 目标",
        trigger=TriggerSignal(
            user_id="m-user",
            type="conversation_inactivity",
            dedupe_key="d1",
            detected_at=datetime.now(),
            last_user_message_at=datetime.now(),
        ),
    )


@pytest.mark.asyncio
async def test_expire_planned_scheduled_old(override_settings, db_session_factory):
    override_settings()
    record = new_record(_intent(), "m-user", session_id="s1")
    record.status = "planned"
    record.scheduled_at = datetime.now() - timedelta(days=3)
    action_repository.save_record(record)
    _expire_planned()
    got = action_repository.get_record(record.id)
    assert got.status == "cancelled"
    assert got.gate_reason == "expired"


@pytest.mark.asyncio
async def test_expire_planned_recent_kept(override_settings, db_session_factory):
    override_settings()
    record = new_record(_intent(), "m-user", session_id="s1")
    record.status = "planned"
    record.scheduled_at = datetime.now()
    action_repository.save_record(record)
    _expire_planned()
    assert action_repository.get_record(record.id).status == "planned"


def test_collect_facts_active_counts(override_settings, db_session_factory):
    override_settings()
    intent = _intent(content="提醒")
    record = new_record(intent, "m-user", session_id=None)
    record.status = "planned"
    action_repository.save_record(record)
    facts = collect_facts("m-user")
    assert facts.get("active_plans") == 1


def test_action_adjustment_adds_reason(override_settings, db_session_factory):
    override_settings()
    snapshot = PolicySnapshot(
        action_facts={"pending_reminders": [{"title": "吃药", "due_in_hours": 2}], "recent_failures": []}
    )
    verdict = _apply_action_adjustments(_verdict(), snapshot)
    assert "提醒" in verdict.reason


def test_action_adjustment_noop_when_no_facts():
    snapshot = PolicySnapshot(action_facts={})
    verdict = _apply_action_adjustments(_verdict(), snapshot)
    assert "提醒" not in verdict.reason
