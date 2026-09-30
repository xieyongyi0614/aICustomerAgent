"""AUTO-007 频率控制与可暂停回归（architecture.md §14/§19/§20/§21/§34）。

Interruption Policy 四档判定固化：Hard Block → ignore（静音/关系浅/无动机/
R1 冲突期克制）、Soft Block → wait（冷却中/对话中/上一条未处理）、
Allowed → act、High Priority Override → act（P0 覆盖普通冷却）。
重试耗尽终态、dedupe 抑制、用户发言复位、Channel 失败不重生成分别由
test_proactive_executor / test_auto005_proactive_delivery / test_proactive_repository
回归覆盖；本文件固化四档映射全景。
"""

from datetime import datetime, timedelta

from app.models.autonomy import TriggerSignal
from app.engines.autonomy import PolicySnapshot, evaluate

NOW = datetime(2026, 8, 30, 14, 0)


def _signal(trigger_type="conversation_inactivity") -> TriggerSignal:
    return TriggerSignal(
        type=trigger_type,
        user_id="u1",
        detected_at=NOW,
        context={},
        dedupe_key=f"{trigger_type}:u1:1",
    )


def _snapshot(**overrides) -> PolicySnapshot:
    payload = {
        "generating": False,
        "has_active_action": False,
        "last_proactive_at": None,
        "attempt_count": 0,
        "intimacy": 0.62,
        "tension": 0.0,
        "mood": "calm",
        "current_activity": None,
        "selected_goal_type": "user_care",
        "goal_degraded": False,
    }
    payload.update(overrides)
    return PolicySnapshot(**payload)


def _config():
    from app.core.settings import get_settings

    return get_settings()


def _evaluate(snapshot, signal=None, now=NOW):
    return evaluate(signal or _signal(), snapshot, _config(), now)


def test_hard_block_quiet_hours():
    verdict = _evaluate(_snapshot(), now=datetime(2026, 8, 30, 23, 30))
    assert verdict.decision == "ignore"
    assert "静音时段" in verdict.reason


def test_hard_block_shallow_relationship():
    verdict = _evaluate(_snapshot(intimacy=0.2))
    assert verdict.decision == "ignore"
    assert "关系尚浅" in verdict.reason


def test_hard_block_no_motivation():
    verdict = _evaluate(_snapshot(goal_degraded=True))
    assert verdict.decision == "ignore"
    assert "无主动动机" in verdict.reason


def test_hard_block_r1_conflict_restraint():
    verdict = _evaluate(_snapshot(conflict_status="conflict"))
    assert verdict.decision == "ignore"
    assert "R1冲突期克制" in verdict.reason


def test_soft_block_generating():
    verdict = _evaluate(_snapshot(generating=True))
    assert verdict.decision == "wait"
    assert "用户正在对话" in verdict.reason


def test_soft_block_cooldown():
    verdict = _evaluate(_snapshot(last_proactive_at=NOW - timedelta(minutes=10)))
    assert verdict.decision == "wait"
    assert "冷却中" in verdict.reason


def test_soft_block_active_action():
    verdict = _evaluate(_snapshot(has_active_action=True))
    assert verdict.decision == "wait"
    assert "上一条主动还未处理" in verdict.reason


def test_allowed_acts():
    verdict = _evaluate(_snapshot())
    assert verdict.decision == "act"


def test_high_priority_override_acts_within_cooldown():
    snapshot = _snapshot(last_proactive_at=NOW - timedelta(minutes=10))
    verdict = _evaluate(snapshot, signal=_signal("scheduled_followup"))
    assert verdict.decision == "act"
    assert "覆盖冷却" in verdict.reason


def test_episode_cap_hard_stops_even_override():
    snapshot = _snapshot(attempt_count=2)
    for trigger_type in ("conversation_inactivity", "scheduled_followup"):
        verdict = _evaluate(snapshot, signal=_signal(trigger_type))
        assert verdict.decision == "ignore"
        assert "集期已达上限" in verdict.reason
