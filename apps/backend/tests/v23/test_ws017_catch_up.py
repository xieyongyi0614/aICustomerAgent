"""WS-017：Catch-up 追赶与事件风暴防护测试。"""

from datetime import date, datetime

import pytest

from app.application import world_engine
from app.core.settings import get_settings
from app.repositories import world_repository, world_simulation_repository as repo
from app.services.world import catch_up

pytestmark = pytest.mark.xdist_group("ws017")


@pytest.fixture(autouse=True)
def sim_mode(monkeypatch):
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_plan_no_catchup_cases():
    today = date(2026, 9, 17)
    assert catch_up.compute_catch_up_plan(None, today, 7).mode == "none"
    assert catch_up.compute_catch_up_plan(today, today, 7).mode == "none"
    assert catch_up.compute_catch_up_plan(date(2026, 9, 16), today, 7).mode == "none"


def test_plan_daily_folding():
    plan = catch_up.compute_catch_up_plan(date(2026, 9, 14), date(2026, 9, 17), 7)
    assert plan.mode == "daily"
    assert plan.days_behind == 3
    assert [d.isoformat() for d in plan.missing_days] == ["2026-09-15", "2026-09-16"]


def test_plan_long_gap_beyond_max():
    plan = catch_up.compute_catch_up_plan(date(2026, 9, 1), date(2026, 9, 20), 7)
    assert plan.mode == "long_gap"
    assert plan.days_behind == 19
    assert plan.gap_from == date(2026, 9, 1)
    assert plan.gap_to == date(2026, 9, 20)


def _set_clock(user: str, sim_time: datetime):
    world = world_repository.ensure_world(user)
    repo.commit_time_advance(world.world_id, sim_time, sim_time)
    return world


def test_run_catch_up_daily(db_session_factory):
    from app.services.world import day_cycle

    user = "ws017-daily"
    _set_clock(user, datetime(2026, 9, 14, 9, 0))
    day_cycle.emit_time_markers(user)
    world = _set_clock(user, datetime(2026, 9, 17, 9, 0))
    result = catch_up.run_catch_up(user, datetime(2026, 9, 17, 9, 0))
    assert result["mode"] == "daily"
    assert set(result["emitted"]) == {
        "time:day_summary:2026-09-15",
        "time:day_summary:2026-09-16",
    }
    events = world_repository.list_events(world.world_id, limit=50)
    summaries = [e for e in events if (e.payload or {}).get("kind") == "day_summary"]
    assert len(summaries) == 2
    parts = [e for e in events if (e.payload or {}).get("from_part")]
    assert parts == []


def test_run_catch_up_long_gap(db_session_factory):
    from app.services.world import day_cycle

    user = "ws017-gap"
    _set_clock(user, datetime(2026, 9, 1, 9, 0))
    day_cycle.emit_time_markers(user)
    world = _set_clock(user, datetime(2026, 9, 20, 9, 0))
    result = catch_up.run_catch_up(user, datetime(2026, 9, 20, 9, 0))
    assert result["mode"] == "long_gap"
    assert result["emitted"] == ["time:long_gap:2026-09-01:2026-09-20"]
    events = world_repository.list_events(world.world_id, limit=50)
    gaps = [e for e in events if (e.payload or {}).get("kind") == "long_gap"]
    assert gaps and gaps[0].importance.value == "normal"
    second = catch_up.run_catch_up(user, datetime(2026, 9, 20, 9, 5))
    assert second["mode"] == "none"


def test_storm_cap_folds_into_digest(db_session_factory, monkeypatch):
    monkeypatch.setenv("WORLD_EVENT_TICK_CAP", "8")
    get_settings.cache_clear()
    try:
        user = "ws017-storm"
        world_repository.ensure_world(user)
        drafts = [
            {
                "event_type": "time_marker",
                "title": f"事件{i}",
                "importance": "high" if i < 2 else "low",
                "source": "time",
                "status": "completed",
                "payload": {"i": i},
                "idempotency_key": f"storm:{i}",
            }
            for i in range(20)
        ]
        emitted = world_engine._emit_simulation_events(user, drafts)
        assert len(emitted) == 8
        assert sum(1 for k in emitted if k.startswith("storm:")) == 7
        assert any(k.startswith("world_digest:") for k in emitted)
        events = world_repository.list_events(
            world_repository.ensure_world(user).world_id, limit=50
        )
        digests = [e for e in events if e.type == "world_digest"]
        assert digests and digests[0].payload["count"] == 13
    finally:
        get_settings.cache_clear()


def test_no_cap_passthrough(db_session_factory, monkeypatch):
    monkeypatch.setenv("WORLD_EVENT_TICK_CAP", "0")
    get_settings.cache_clear()
    try:
        user = "ws017-nocap"
        world_repository.ensure_world(user)
        drafts = [
            {
                "event_type": "time_marker",
                "title": f"事件{i}",
                "importance": "low",
                "source": "time",
                "status": "completed",
                "payload": {},
                "idempotency_key": f"nocap:{i}",
            }
            for i in range(12)
        ]
        assert len(world_engine._emit_simulation_events(user, drafts)) == 12
    finally:
        get_settings.cache_clear()
