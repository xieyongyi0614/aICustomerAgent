"""V7-001：Autonomy 域模型校验（autonomy-model.md / action-model.md）。"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.autonomy import (
    TERMINAL_STATUSES,
    AutonomyVerdict,
    ProactiveAction,
    PROACTIVE_INTENTION_MAP,
    TriggerSignal,
)
from app.models.intention import IntentionType


def _signal(**overrides):
    payload = {
        "type": "conversation_inactivity",
        "user_id": "u1",
        "detected_at": datetime(2026, 8, 30, 14, 0),
        "context": {"idle_minutes": 35},
        "dedupe_key": "inactivity:u1:42",
    }
    payload.update(overrides)
    return TriggerSignal(**payload)


def test_trigger_signal_roundtrip():
    signal = _signal()
    assert signal.context["idle_minutes"] == 35
    assert "inactivity" in signal.dedupe_key


def test_trigger_signal_rejects_unknown_type():
    with pytest.raises(ValidationError):
        _signal(type="world_event")


def test_action_defaults_and_status_set():
    now = datetime(2026, 8, 30, 14, 0)
    action = ProactiveAction(
        id="a1",
        user_id="u1",
        session_id="s1",
        trigger_type="conversation_inactivity",
        dedupe_key="inactivity:u1:42",
        intention="check_in",
        created_at=now,
        updated_at=now,
    )
    assert action.type == "send_message"
    assert action.status == "candidate"
    assert action.attempt == 0
    assert action.payload_text is None
    with pytest.raises(ValidationError):
        ProactiveAction(
            id="a2",
            user_id="u1",
            session_id="s1",
            trigger_type="conversation_inactivity",
            dedupe_key="k",
            intention="check_in",
            status="shipping",
            created_at=now,
            updated_at=now,
        )


def test_verdict_reason_truncated_and_optional_fields():
    verdict = AutonomyVerdict(decision="wait", reason="冷却中")
    assert verdict.trigger is None
    assert verdict.goal_id is None
    with pytest.raises(ValidationError):
        AutonomyVerdict(decision="maybe")


def test_proactive_intention_whitelist():
    assert PROACTIVE_INTENTION_MAP == {
        "user_care": "check_in",
        "relationship": "repair_rapport",
    }


def test_check_in_registered_in_intention_type():
    from typing import get_args

    assert "check_in" in get_args(IntentionType)


def test_terminal_statuses():
    assert TERMINAL_STATUSES == frozenset({"acked", "discarded", "failed", "expired"})
