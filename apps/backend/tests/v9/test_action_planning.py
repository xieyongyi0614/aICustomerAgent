"""V9 Action Planning：post_process 第 9 步编排 + 六闸门 + 装配（V9-002/003）。"""

from datetime import datetime, timedelta

import pytest

from app.application.action_engine import run_action_planning, new_record
from app.models.action import ActionIntent
from app.services.action.planner import (
    GateDecision,
    GateSnapshot,
    assemble_plan,
    evaluate_gates,
)
from app.services.action.registry import get_capability_registry
from app.core.settings import get_settings

USER = "plan-user"


def _intent(action_type="create_reminder", **params):
    return ActionIntent(
        action_type=action_type,
        confidence="confident",
        params=params,
        dedupe_key="",
    )


@pytest.mark.asyncio
async def test_action_planning_records_created(override_settings, db_session_factory):
    override_settings()
    record = await run_action_planning(USER, _intent(content="喝水", due_at="20:00"))
    assert record is not None
    assert record.action_type == "create_reminder"
    assert record.status in ("succeeded", "failed", "cancelled", "executing")


def test_duplicate_gate_rejects(override_settings, db_session_factory):
    override_settings()
    gsaf = get_settings()
    snapshot = GateSnapshot(settings=gsaf, registry=get_capability_registry(), now=datetime.now())
    snapshot.records = [
        {"dedupe_key": "abc123", "status": "succeeded", "created_at": datetime.now()}
    ]
    snapshot.active_count = 0
    snapshot.world_available = True
    intent = _intent(note="重复")
    intent.dedupe_key = "abc123"
    decision: GateDecision = evaluate_gates(intent, snapshot)
    assert not decision.allowed
    assert decision.reason == "duplicate"


def test_ambiguous_params_gate_rejects(override_settings, db_session_factory):
    override_settings()
    snapshot = GateSnapshot(settings=get_settings(), registry=get_capability_registry(), now=datetime.now())
    intent = ActionIntent(
        action_type="create_reminder",
        confidence="ambiguous",
        missing_params=["due_at"],
        dedupe_key="",
    )
    decision: GateDecision = evaluate_gates(intent, snapshot)
    assert not decision.allowed
    assert decision.reason == "ambiguous_params"


def test_assemble_plan_single_step(db_session_factory):
    settings = get_settings()
    snapshot = GateSnapshot(settings=settings, registry=get_capability_registry(), now=datetime.now())
    intent = _intent(content="吃早餐", due_at="08:00")
    intent.dedupe_key = "key-1"
    plan = assemble_plan(intent, snapshot, datetime.now())
    assert plan is not None
    assert plan.steps
    assert plan.steps[0].capability == "reminder"
    assert plan.steps[0].action == "create"
    assert plan.intent.dedupe_key == "key-1"


@pytest.mark.asyncio
async def test_action_planning_e2e_makes_world_event(override_settings, db_session_factory):
    from app.application import world_engine

    override_settings()
    due = (datetime.now() + timedelta(hours=1)).isoformat()
    record = await run_action_planning(USER, _intent(content="吃药", due_at=due))
    assert record is not None
    if record.status == "cancelled":
        return
    events = world_engine.list_active_events(USER)
    assert any(e.title == "吃药" and e.type == "reminder" for e in events)
