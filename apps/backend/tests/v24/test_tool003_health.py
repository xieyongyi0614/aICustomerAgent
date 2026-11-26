"""TOOL-003 §6.1 / §6.3：熔断、冷却半开、重启归零（E13、E14）。"""

from datetime import datetime, timedelta

import pytest

from app.services.action.registry import get_capability_registry
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from tests.v24.tool002_support import definition
from tests.v24.tool003_support import registry_with, tool_settings, tracker

TOOL_ID = "builtin.reminder.create"
T0 = datetime(2026, 6, 1, 12, 0, 0)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _registry() -> ToolRegistry:
    return registry_with(definition())


def _fail(health, times: int = 1, failure_kind: str = "transient") -> None:
    for _ in range(times):
        health.record_outcome(TOOL_ID, ok=False, failure_kind=failure_kind)


def test_success_resets_counter_and_stamps_last_success():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    health.record_outcome(TOOL_ID, ok=False, failure_kind="transient")
    health.record_outcome(TOOL_ID, ok=True)
    record = health.snapshot(TOOL_ID)[TOOL_ID]
    assert record.consecutive_failures == 0
    assert record.tripped is False
    assert record.last_success_at is not None


def test_failure_window_rate_is_computed_by_registry():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    health.record_outcome(TOOL_ID, ok=True)
    health.record_outcome(TOOL_ID, ok=False, failure_kind="transient")
    assert health.snapshot(TOOL_ID)[TOOL_ID].failure_rate_window == 0.5


def test_threshold_trips_and_disables_tool():
    registry = _registry()
    health = tracker(registry, settings=tool_settings(tool_breaker_threshold=3), clock=Clock(T0))
    _fail(health, 2)
    assert health.snapshot(TOOL_ID)[TOOL_ID].tripped is False
    assert registry.effective_status(TOOL_ID) == "enabled"
    _fail(health, 1)
    assert health.snapshot(TOOL_ID)[TOOL_ID].tripped is True
    assert health.is_tripped(TOOL_ID, T0) is True
    assert registry.effective_status(TOOL_ID) == "disabled"
    assert registry.has(TOOL_ID) is False
    assert TOOL_ID not in [item.id for item in registry.list(status="enabled")]


def test_threshold_is_read_from_settings_at_call_time():
    registry = _registry()
    settings = tool_settings(tool_breaker_threshold=10)
    health = tracker(registry, settings=settings, clock=Clock(T0))
    _fail(health, 3)
    assert health.snapshot(TOOL_ID)[TOOL_ID].tripped is False
    settings.tool_breaker_threshold = 3
    _fail(health, 1)
    assert health.snapshot(TOOL_ID)[TOOL_ID].tripped is True


def test_success_clears_trip():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    _fail(health, 3)
    assert registry.effective_status(TOOL_ID) == "disabled"
    health.record_outcome(TOOL_ID, ok=True)
    assert health.is_tripped(TOOL_ID, T0) is False
    assert registry.effective_status(TOOL_ID) == "enabled"


def test_half_open_after_cooldown_keeps_failure_count():
    registry = _registry()
    clock = Clock(T0)
    health = tracker(
        registry,
        settings=tool_settings(tool_breaker_cooldown_seconds=300),
        clock=clock,
    )
    _fail(health, 3)
    clock.advance(299)
    assert health.is_tripped(TOOL_ID, clock.now) is True
    assert registry.effective_status(TOOL_ID) == "disabled"
    clock.advance(2)
    assert health.is_tripped(TOOL_ID, clock.now) is False
    assert registry.effective_status(TOOL_ID) == "enabled"
    assert health.snapshot(TOOL_ID)[TOOL_ID].consecutive_failures == 3


def test_failure_inside_cooldown_does_not_reset_timer_e13():
    registry = _registry()
    clock = Clock(T0)
    health = tracker(
        registry,
        settings=tool_settings(tool_breaker_cooldown_seconds=300),
        clock=clock,
    )
    _fail(health, 3)
    clock.advance(100)
    _fail(health, 1)
    assert health.is_tripped(TOOL_ID, clock.now) is True
    assert registry.effective_status(TOOL_ID) == "disabled"
    clock.advance(201)
    assert health.is_tripped(TOOL_ID, clock.now) is False


def test_next_failure_after_half_open_re_trips_immediately():
    registry = _registry()
    clock = Clock(T0)
    health = tracker(
        registry,
        settings=tool_settings(tool_breaker_cooldown_seconds=300),
        clock=clock,
    )
    _fail(health, 3)
    clock.advance(301)
    assert health.is_tripped(TOOL_ID, clock.now) is False
    _fail(health, 1)
    assert health.is_tripped(TOOL_ID, clock.now) is True
    assert registry.effective_status(TOOL_ID) == "disabled"


def test_restart_resets_breaker_state():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    _fail(health, 3)
    assert registry.effective_status(TOOL_ID) == "disabled"
    restarted = ToolRegistry()
    register_builtin_tools(restarted)
    assert restarted.effective_status(TOOL_ID) == "enabled"
    assert restarted.health(TOOL_ID)[TOOL_ID].tripped is False
    assert restarted.health(TOOL_ID)[TOOL_ID].consecutive_failures == 0


def test_restart_does_not_inherit_tracker_memory():
    registry = _registry()
    first = tracker(registry, clock=Clock(T0))
    _fail(first, 3)
    second = tracker(registry, clock=Clock(T0 + timedelta(seconds=10)))
    assert second.snapshot(TOOL_ID)[TOOL_ID].tripped is True
    assert second._tripped_at == {}


def test_outcomes_accumulate_in_call_order_e14():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    for ok in (False, False, True, False, False):
        health.record_outcome(TOOL_ID, ok=ok, failure_kind=None if ok else "transient")
    assert health.snapshot(TOOL_ID)[TOOL_ID].consecutive_failures == 2
    assert health.snapshot(TOOL_ID)[TOOL_ID].failure_rate_window == pytest.approx(0.8)


def test_snapshot_returns_copies():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    _fail(health, 1)
    snapshot = health.snapshot(TOOL_ID)
    snapshot[TOOL_ID].consecutive_failures = 99
    assert health.snapshot(TOOL_ID)[TOOL_ID].consecutive_failures == 1
    assert list(health.snapshot()) == [TOOL_ID]


def test_unknown_tool_id_is_noop():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    health.record_outcome("nope.tool", ok=False, failure_kind="transient")
    assert health.is_tripped("nope.tool", T0) is False
    assert health.snapshot("nope.tool") == {}
    registry.mark_tripped("nope.tool")
    registry.clear_tripped("nope.tool")
    assert registry.effective_status("nope.tool") == "removed"


def test_invalid_failure_kind_is_rejected_by_registry():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    with pytest.raises(ValueError):
        health.record_outcome(TOOL_ID, ok=False, failure_kind="bogus")


def test_registry_write_surface_only_touches_tripped_flag():
    registry = _registry()
    registry.record_outcome(TOOL_ID, ok=False, failure_kind="transient")
    before = registry.health(TOOL_ID)[TOOL_ID]
    registry.mark_tripped(TOOL_ID)
    after = registry.health(TOOL_ID)[TOOL_ID]
    assert after.tripped is True
    assert after.consecutive_failures == before.consecutive_failures
    assert after.failure_rate_window == before.failure_rate_window
    registry.clear_tripped(TOOL_ID)
    cleared = registry.health(TOOL_ID)[TOOL_ID]
    assert cleared.tripped is False
    assert cleared.consecutive_failures == before.consecutive_failures


def test_tripped_tool_disappears_from_describe():
    registry = _registry()
    health = tracker(registry, clock=Clock(T0))
    assert [item.tool_id for item in registry.describe()] == [TOOL_ID]
    _fail(health, 3)
    assert registry.describe() == []
    assert registry.namespaces()["builtin"].enabled_count == 0


def test_health_tracker_module_reuses_v9_capability_registry():
    assert get_capability_registry().has("reminder", "create")
