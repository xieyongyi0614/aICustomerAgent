import pytest
from datetime import datetime, timedelta, timezone

from app.application.chat_pipeline import _idle_seconds_since, _stabilize_mode
from app.services import mode_service
from app.services.mode_service import stabilize


class _StateStub:
    def __init__(self, mode, mode_entered_at):
        self.mode = mode
        self.mode_entered_at = mode_entered_at


@pytest.fixture(autouse=True)
def _reset():
    mode_service.reset_candidate_counts()
    yield
    mode_service.reset_candidate_counts()


def test_r1_same_candidate_no_change():
    d = stabilize("default", "default", 0.9, "s1", 0)
    assert (d.effective, d.rule, d.write_back) == ("default", "R1", False)


def test_r2_hysteresis_switch_after_two_turns():
    stabilize("default", "immersive", 0.9, "s1", 0)
    d = stabilize("default", "immersive", 0.9, "s1", 0)
    assert (d.effective, d.rule, d.write_back, d.switched) == (
        "immersive", "R2", True, True,
    )


def test_r2_blocked_by_low_confidence():
    stabilize("default", "immersive", 0.6, "s1", 0)
    d = stabilize("default", "immersive", 0.6, "s1", 0)
    assert (d.effective, d.rule) == ("default", "R3")


def test_r2_blocked_by_single_turn():
    d = stabilize("default", "immersive", 0.9, "s1", 0)
    assert (d.effective, d.rule, d.write_back) == ("default", "R3", False)


def test_r3_candidate_counter_resets_on_confirmed():
    stabilize("default", "immersive", 0.9, "s1", 0)
    stabilize("default", "default", 0.9, "s1", 0)
    d = stabilize("default", "immersive", 0.9, "s1", 0)
    assert d.rule == "R3"


def test_r4_idle_reset():
    d = stabilize("immersive", "default", 0.9, "s1", 7201)
    assert (d.effective, d.rule, d.write_back, d.switched) == (
        "default", "R4", True, True,
    )


def test_r4_boundary_not_triggered():
    d = stabilize("immersive", "default", 0.9, "s1", 7200)
    assert d.rule != "R4"


def test_r5_router_failure_keeps_confirmed():
    d = stabilize("immersive", "", 0.0, "s1", 0)
    assert (d.effective, d.rule, d.write_back) == ("immersive", "R5", False)


def test_r5_invalid_candidate_keeps_confirmed():
    d = stabilize("immersive", "romantic", 0.9, "s1", 0)
    assert d.rule == "R5"


def test_confirmed_invalid_falls_back_default():
    d = stabilize("weird", "default", 0.9, "s1", 0)
    assert d.effective == "default"


def test_sessions_counted_independently():
    stabilize("default", "immersive", 0.9, "s1", 0)
    d = stabilize("default", "immersive", 0.9, "s2", 0)
    assert d.rule == "R3"
    d = stabilize("default", "immersive", 0.9, "s1", 0)
    assert d.rule == "R2"


def test_idle_seconds_handles_aware_utc_moment():
    moment = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert 599 <= _idle_seconds_since(moment) <= 601


def test_idle_seconds_handles_aware_non_utc_offset():
    tz = timezone(timedelta(hours=8))
    moment = datetime.now(tz) - timedelta(minutes=10)
    assert 599 <= _idle_seconds_since(moment) <= 601


def test_idle_seconds_handles_naive_moment():
    moment = datetime.now() - timedelta(minutes=10)
    assert 599 <= _idle_seconds_since(moment) <= 601


def test_idle_seconds_future_moment_clamped_to_zero():
    moment = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert _idle_seconds_since(moment) == 0.0


def test_stabilize_mode_with_aware_mode_entered_at_no_typeerror():
    state = _StateStub("immersive", datetime.now(timezone.utc) - timedelta(hours=3))
    d = _stabilize_mode(None, state, "s-tz")
    assert (d.effective, d.rule) == ("default", "R4")


def test_stabilize_mode_with_naive_mode_entered_at_recent_keeps_confirmed():
    state = _StateStub("immersive", datetime.now() - timedelta(minutes=1))
    d = _stabilize_mode(None, state, "s-naive")
    assert (d.effective, d.rule) == ("immersive", "R5")


def test_stabilize_mode_with_none_mode_entered_at():
    state = _StateStub("immersive", None)
    d = _stabilize_mode(None, state, "s-none")
    assert (d.effective, d.rule) == ("immersive", "R5")
