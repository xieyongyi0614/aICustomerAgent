"""V8.5 M8 自主集成套件（autonomy-integration.md：R1~R5 + 默认态逐位一致）。"""

from datetime import datetime, timedelta

import pytest

from app.models.autonomy import TriggerSignal
from app.services.autonomy_policy import (
    PolicySnapshot,
    _apply_relationship_rules,
    effective_interval_minutes,
    evaluate,
)

NOW = datetime(2026, 8, 31, 12, 0, 0)


def _signal():
    return TriggerSignal(
        type="conversation_inactivity",
        user_id="u1",
        detected_at=NOW,
        dedupe_key="d1",
    )


def _snapshot(**overrides) -> PolicySnapshot:
    values = dict(
        selected_goal_type="user_care",
        last_proactive_at=NOW - timedelta(hours=6),
    )
    values.update(overrides)
    return PolicySnapshot(**values)


def _verdict(intention="check_in"):
    from app.models.autonomy import AutonomyVerdict

    return AutonomyVerdict(
        decision="act",
        reason="触发 conversation_inactivity",
        trigger=_signal(),
        intention=intention,
    )


def _rules(snapshot, intention="check_in", config=None):
    from app.core.settings import get_settings

    return _apply_relationship_rules(_verdict(intention), snapshot, config or get_settings())


def test_r1_conflict_blocks_all_proactive():
    verdict = _rules(_snapshot(conflict_status="conflict"))
    assert verdict.decision == "ignore"
    assert "R1冲突期克制" in verdict.reason


def test_r1_reconciliation_bypass_with_unlock():
    verdict = _rules(
        _snapshot(
            conflict_status="conflict",
            trust=0.5,
            unlocks=("conflict_recovery_available",),
        ),
        intention="reconciliation_check_in",
    )
    assert verdict.decision == "act"
    assert "R1单和解放行" in verdict.reason


def test_r1_reconciliation_blocked_without_unlock():
    verdict = _rules(
        _snapshot(conflict_status="conflict", trust=0.5),
        intention="reconciliation_check_in",
    )
    assert verdict.decision == "ignore"


def test_r1_reconciliation_once_per_conflict():
    snapshot = _snapshot(
        conflict_status="conflict",
        trust=0.5,
        unlocks=("conflict_recovery_available",),
        extra_flags={"reconciliation_attempted": True},
    )
    verdict = _rules(snapshot, intention="reconciliation_check_in")
    assert verdict.decision == "ignore"


def test_r3_low_trust_blocks_reminder():
    verdict = _rules(_snapshot(trust=0.30), intention="reminder")
    assert verdict.decision == "ignore"
    assert "R3信任不足" in verdict.reason


def test_r3_passes_above_trust_floor():
    verdict = _rules(_snapshot(trust=0.60), intention="reminder")
    assert verdict.decision == "act"


def test_r4_locked_intent_blocked_without_unlock():
    verdict = _rules(_snapshot(), intention="goodnight_care")
    assert verdict.decision == "ignore"
    assert "R4解锁未达成" in verdict.reason


def test_r4_unlocked_intent_passes():
    verdict = _rules(
        _snapshot(unlocks=("proactive_goodnight",)), intention="goodnight_care"
    )
    assert verdict.decision == "act"


def test_r5_neglect_recall_overrides_r3():
    verdict = _rules(
        _snapshot(trust=0.30, neglect_active=True, stage="close_friend"),
        intention="reminder",
    )
    assert verdict.decision == "act"
    assert "R5疏远召回覆盖R3" in verdict.reason


def test_r5_neglect_recall_shallow_stage_not_granted():
    verdict = _rules(
        _snapshot(trust=0.30, neglect_active=True, stage="stranger"),
        intention="reminder",
    )
    assert verdict.decision == "ignore"


def test_r2_low_comfort_extends_cooldown():
    config = type("C", (), {"autonomy_min_interval_minutes": 60.0, "autonomy_backoff_multiplier": 1.0, "autonomy_min_interval_floor_minutes": 1.0})()
    normal = effective_interval_minutes(_snapshot(comfort=0.6), config)
    low = effective_interval_minutes(_snapshot(comfort=0.30), config)
    assert low == pytest.approx(normal * 1.5)


def test_default_snapshot_fields_keep_v7_verdict():
    """不传新字段（默认值）时 R1~R5 全部不触发，输出与 V7 一致。"""
    snapshot = _snapshot()
    verdict = _rules(snapshot)
    assert verdict.decision == "act"
    assert "R1" not in verdict.reason and "R3" not in verdict.reason
    assert "R4" not in verdict.reason and "R5" not in verdict.reason


def test_full_pipeline_relationship_rules_applied_last():
    verdict = evaluate(_signal(), _snapshot(conflict_status="cold"), now=NOW)
    assert verdict.decision == "ignore"
    assert "R1冲突期克制" in verdict.reason