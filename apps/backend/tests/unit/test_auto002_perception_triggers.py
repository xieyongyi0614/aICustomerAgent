"""AUTO-002 感知与 Trigger 求值契约测试（architecture.md §6/§7/§16/§17）。

TriggerSignal 是「机会」不是「行动」：不携带决策语义，Opportunity 摘要由
context 承载；TriggerType 枚举不扩展（world_change 等属 G7 未来版本），
世界变化只作为 reason 补充（W1~W3 已由 test_autonomy_policy_world 覆盖）。
"""

from datetime import datetime, timedelta

from app.core import timeutil
from app.models.autonomy import TriggerSignal
from app.services.autonomy import trigger as trigger_evaluator

NOW = timeutil.ensure_aware(datetime(2026, 9, 7, 12, 0, 0))


def _tail(role: str = "ai") -> trigger_evaluator.SessionTail:
    return trigger_evaluator.SessionTail(
        last_message_at=NOW - timedelta(minutes=45),
        last_message_role=role,
        last_user_message_at=NOW - timedelta(hours=2),
        last_user_message_id="m1",
    )


def test_trigger_signal_carries_opportunity_not_decision():
    assert set(TriggerSignal.model_fields) == {
        "type",
        "user_id",
        "detected_at",
        "context",
        "dedupe_key",
    }


def test_trigger_type_enum_not_extended():
    hints = TriggerSignal.model_fields["type"].annotation
    assert "world_change" not in repr(hints)
    assert "life_loop_event" not in repr(hints)
    assert "conversation_inactivity" in repr(hints)
    assert "scheduled_followup" in repr(hints)
    assert "action_due" in repr(hints)


def test_inactivity_signal_context_is_opportunity_summary():
    signal = trigger_evaluator.evaluate_inactivity(
        _tail(), "u1", episode_attempts=0, now=NOW
    )
    assert signal is not None
    assert signal.type == "conversation_inactivity"
    assert signal.context["idle_minutes"] >= 45
    assert signal.context["last_role"] == "ai"
    assert signal.dedupe_key == "inactivity:u1:m1"


def test_followup_signal_context_carries_summary_and_due_at():
    trigger_evaluator.register_followup(
        "u1",
        due_at=NOW - timedelta(minutes=1),
        summary="面试提醒",
        dedupe_key="followup:u1:面试",
    )
    signal = trigger_evaluator.poll_due_followup("u1", NOW)
    assert signal is not None
    assert signal.type == "scheduled_followup"
    assert signal.context["summary"] == "面试提醒"
    assert signal.context["due_at"] == (NOW - timedelta(minutes=1)).isoformat()
    assert "decision" not in signal.context
