"""V9-002 六闸门 + 计划装配单测（planner.md §2~§3）。"""

from datetime import datetime

import pytest

from app.character.asuna.action import ACTION_CAPABILITY_MAP
from app.models.action import ActionIntent
from app.services.action.planner import GateSnapshot, assemble_plan, evaluate_gates
from app.services.action.registry import CapabilityRegistry
from app.services.action import capabilities

NOW = datetime(2026, 9, 3, 14, 0, 0)


def make_intent(**overrides) -> ActionIntent:
    base = dict(
        action_type="create_reminder",
        confidence="confident",
        params={"content": "开会", "due_at": "2026-09-04T08:00:00"},
        dedupe_key="k001",
    )
    base.update(overrides)
    return ActionIntent(**base)


def make_snapshot(override_settings=None, **overrides) -> GateSnapshot:
    from app.core.settings import get_settings

    registry = CapabilityRegistry()
    capabilities.register_builtin(registry)
    snap = GateSnapshot(settings=get_settings(), registry=registry, world_available=True, now=NOW)
    for key, value in overrides.items():
        setattr(snap, key, value)
    return snap


@pytest.fixture
def snapshot(override_settings):
    override_settings(action_enabled=True)
    return make_snapshot()


def test_all_action_types_mapped():
    for action_type, (capability, action) in ACTION_CAPABILITY_MAP.items():
        assert capability and action


def test_g2_ambiguous_rejected(snapshot):
    decision = evaluate_gates(make_intent(confidence="ambiguous"), snapshot)
    assert not decision.allowed and decision.reason == "ambiguous_params"


def test_g3_capability_unavailable(snapshot):
    snapshot.registry = CapabilityRegistry()
    decision = evaluate_gates(make_intent(), snapshot)
    assert not decision.allowed and decision.reason == "capability_unavailable"


def test_g3_world_unavailable(snapshot):
    snapshot.world_available = False
    decision = evaluate_gates(make_intent(), snapshot)
    assert not decision.allowed and decision.reason == "capability_unavailable"


def test_g4_duplicate_rejected(snapshot):
    snapshot.records = [{"dedupe_key": "k001", "status": "succeeded", "created_at": NOW}]
    decision = evaluate_gates(make_intent(), snapshot)
    assert not decision.allowed and decision.reason == "duplicate"


def test_g4_failed_record_does_not_block(snapshot):
    snapshot.records = [{"dedupe_key": "k001", "status": "failed", "created_at": NOW}]
    assert evaluate_gates(make_intent(), snapshot).allowed


def test_g4_outside_window(snapshot):
    from datetime import timedelta

    old = NOW - timedelta(hours=snapshot.settings.action_dedupe_window_hours + 1)
    snapshot.records = [{"dedupe_key": "k001", "status": "succeeded", "created_at": old}]
    assert evaluate_gates(make_intent(), snapshot).allowed


def test_g5_quota_exceeded(snapshot):
    snapshot.active_count = snapshot.settings.action_max_active_per_user
    decision = evaluate_gates(make_intent(), snapshot)
    assert not decision.allowed and decision.reason == "quota_exceeded"


def test_g6_create_object_already_satisfied(snapshot):
    snapshot.world_available = True
    intent = make_intent(action_type="create_object", params={"object": "牛奶"}, dedupe_key="k2")
    snapshot.active_object_names = ["牛奶"]
    decision = evaluate_gates(intent, snapshot)
    assert not decision.allowed and decision.reason == "effect_already_satisfied"


def test_g6_cancel_target_not_found(snapshot):
    intent = make_intent(action_type="cancel_reminder", params={"target": "开会"}, dedupe_key="k3")
    snapshot.active_reminder_titles = ["买牛奶"]
    decision = evaluate_gates(intent, snapshot)
    assert not decision.allowed and decision.reason == "target_not_found"


def test_g6_cancel_target_found(snapshot):
    intent = make_intent(action_type="cancel_reminder", params={"target": "开会"}, dedupe_key="k3")
    snapshot.active_reminder_titles = ["开会提醒"]
    assert evaluate_gates(intent, snapshot).allowed


def test_assemble_plan(snapshot):
    plan = assemble_plan(make_intent(), snapshot, NOW, goal_id="g1")
    assert plan is not None
    assert plan.steps[0].capability == "reminder"
    assert plan.steps[0].action == "create"
    assert plan.goal_id == "g1"
    assert plan.expires_at > NOW


def test_assemble_plan_invalid_params(snapshot):
    intent = make_intent(params={"content": "开会"})
    assert assemble_plan(intent, snapshot, NOW) is None
