"""WS-008：DailyPlanRunner 块推进测试（断言基于固定块，无抖动）。"""

from datetime import date, datetime

import pytest

from app.core.settings import get_settings
from app.models.world_simulation import DailyPlanStatus
from app.repositories import world_repository, world_simulation_repository as repo
from app.services.world import daily_plan

pytestmark = pytest.mark.xdist_group("ws008")


@pytest.fixture(autouse=True)
def sim_mode(monkeypatch):
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _prepare(user: str):
    world_repository.ensure_world(user)
    daily_plan.build_daily_plan(user, date(2026, 9, 14))
    return _plans(user)


def _plans(user: str):
    return {p.seq: p for p in repo.get_day_plans(user, date(2026, 9, 14))}


def test_activation_within_window(db_session_factory):
    user = "ws008-activate"
    _prepare(user)
    summary = daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 12, 0))
    assert summary["activated"] is not None
    plans = _plans(user)
    assert plans[3].status == DailyPlanStatus.ACTIVE
    assert plans[3].start_minutes <= 720 < plans[3].end_minutes


def test_completion_past_end(db_session_factory):
    user = "ws008-complete"
    _prepare(user)
    daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 12, 0))
    summary = daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 15, 0))
    plans = _plans(user)
    assert plans[3].status == DailyPlanStatus.COMPLETED
    assert plans[5].status == DailyPlanStatus.ACTIVE
    assert summary["completed"]


def test_missed_block_skipped(db_session_factory):
    user = "ws008-skip"
    _prepare(user)
    summary = daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 21, 0))
    plans = _plans(user)
    assert plans[3].status == DailyPlanStatus.SKIPPED
    assert plans[3].id in summary["skipped"]
    assert summary["activated"] is not None
    activated = next(p for p in plans.values() if p.status == DailyPlanStatus.ACTIVE)
    assert activated.seq == 8


def test_block_move_updates_location(db_session_factory):
    user = "ws008-move"
    _prepare(user)
    daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 12, 0))
    assert world_repository.get_world(user).current_location == "home.dining_area"
    daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 15, 0))
    assert world_repository.get_world(user).current_location == "company.workstation"
    events = world_repository.list_events(
        world_repository.world_id_for(user), statuses=["completed"], limit=20
    )
    moves = [e for e in events if (e.payload or {}).get("kind") == "location_change"]
    assert len(moves) == 2
    assert all(e.payload["move_source"] == "schedule" for e in moves)


def test_double_advance_idempotent(db_session_factory):
    user = "ws008-idem"
    _prepare(user)
    first = daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 12, 0))
    second = daily_plan.advance_daily_plan(user, datetime(2026, 9, 14, 12, 5))
    assert first["activated"] is not None
    assert second["activated"] is None
    plans = _plans(user)
    assert plans[3].status == DailyPlanStatus.ACTIVE


def test_no_world_is_noop(db_session_factory):
    summary = daily_plan.advance_daily_plan("ws008-noworld", datetime(2026, 9, 14, 8, 0))
    assert summary["activated"] is None


def test_maintenance_step_advances_plan(db_session_factory, monkeypatch):
    get_settings.cache_clear()
    try:
        from app.application import world_engine
        from app.repositories import world_simulation_repository as repo

        user = "ws008-maint"
        world = world_repository.ensure_world(user)
        anchor = datetime(2026, 9, 14, 12, 0)
        repo.commit_time_advance(world.world_id, anchor, anchor)
        world_engine.run_simulation_maintenance(user, now=anchor)
        plans = daily_plan.get_day_plan(user, date(2026, 9, 14))
        assert plans
        active = [p for p in plans if p.status == DailyPlanStatus.ACTIVE]
        assert active and active[0].seq == 3
    finally:
        get_settings.cache_clear()
