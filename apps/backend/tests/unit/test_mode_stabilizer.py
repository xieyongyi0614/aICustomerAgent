import pytest

from app.services import mode_service
from app.services.mode_service import stabilize


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
