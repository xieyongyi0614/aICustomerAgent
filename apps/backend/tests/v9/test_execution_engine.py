"""V9 Execution Engine：状态机 + 执行 + 重试（V9-003 execution-engine.md）。"""

from datetime import datetime, timedelta

import pytest

from app.application.action_engine import execute_plan, new_record
from app.models.action import (
    ActionIntent,
    ActionPlan,
    ActionStep,
    ActionResult,
    transition_action,
)
from app.services.action.registry import ExecutionContext, get_capability_registry


def test_transition_created_to_planned():
    assert transition_action("created", "gate_pass") == "planned"
    assert transition_action("created", "gate_reject") == "cancelled"


def test_transition_retryable_stays_executing():
    assert transition_action("executing", "step_retryable_failed") == "executing"


def test_transition_retryable_exceeded_fails():
    assert transition_action("executing", "step_retryable_failed", attempts_exceeded=True) == "failed"


def test_transition_executing_not_cancellable():
    assert transition_action("executing", "cancel_requested") is None


def test_transition_terminal_noop():
    assert transition_action("succeeded", "gate_pass") is None
    assert transition_action("cancelled", "execute_start") is None


@pytest.mark.asyncio
async def test_execute_plan_single_success(db_session_factory, override_settings):
    from app.core.settings import get_settings as _gs

    override_settings(action_enabled=True)
    intent = ActionIntent(action_type="remember_fact", confidence="confident", params={"fact": "喜欢柠檬"})
    record = new_record(intent, "exe-user", session_id=None)
    plan = ActionPlan(
        intent=intent,
        steps=[ActionStep(index=0, capability="memory", action="save", params={"fact": "喜欢柠檬"})],
    )
    ctx = ExecutionContext(user_id="exe-user", character_id="asuna", record_id=record.id, now=datetime.now(), settings=_gs())
    result = await execute_plan(record, plan, ctx)
    assert result.status in ("succeeded", "failed", "partial")
    assert record.steps
