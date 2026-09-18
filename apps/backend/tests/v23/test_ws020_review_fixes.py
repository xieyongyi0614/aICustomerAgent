"""WS-020：V2.3.0 Code Review 修复项回归测试。

覆盖：
- M1 计划保留策略接线（prune_expired_plans 可被维护步触发）
- M4 时间推进锚点条件写入（并发不回退）
- M5 时间标记类事件豁免活跃配额 + 丢弃可观测
- M3 日循环观测锚点跨进程可见（不再依赖进程内 dict）
- m1 计划批量写入保持 supersede 语义
- m6 world_digest 幂等键确定性
"""

from datetime import date, datetime

import pytest

from app.application import world_engine
from app.core.settings import get_settings
from app.models.world import WorldEvent
from app.models.world_simulation import DailyPlan, DailyPlanStatus, DailyPlanVariability
from app.repositories import (
    world_repository,
    world_simulation_repository as repo,
)
from app.services.world import daily_plan, day_cycle

pytestmark = pytest.mark.xdist_group("ws020")


def _plan(user: str, seq: int = 0, plan_date: date = date(2026, 9, 14)) -> DailyPlan:
    return DailyPlan(
        id=repo.new_plan_id(),
        user_id=user,
        plan_date=plan_date,
        seq=seq,
        part_of_day="morning",
        start_minutes=390,
        end_minutes=450,
        activity="阅读",
        location_id="home.living_room",
        variability_source=DailyPlanVariability.FIXED,
        status=DailyPlanStatus.PLANNED,
        routine_version=1,
        note=None,
        created_at=datetime(2026, 9, 14, 6, 0),
    )


# --- M1：计划保留策略接线 ---------------------------------------------------


def test_prune_expired_plans_removes_only_beyond_retention(db_session_factory):
    user = "ws020-prune"
    today = date(2026, 9, 14)
    repo.save_plan(_plan(user, plan_date=date(2026, 1, 1)))
    repo.save_plan(_plan(user, plan_date=today))

    removed = daily_plan.prune_expired_plans(user, today)

    assert removed == 1
    assert len(repo.get_day_plans(user, today)) == 1


def test_prune_expired_plans_disabled_when_retention_non_positive(
    db_session_factory, monkeypatch
):
    monkeypatch.setenv("DAILY_PLAN_RETENTION_DAYS", "0")
    get_settings.cache_clear()
    try:
        user = "ws020-prune-off"
        repo.save_plan(_plan(user, plan_date=date(2026, 1, 1)))
        assert daily_plan.prune_expired_plans(user, date(2026, 9, 14)) == 0
        assert len(repo.get_day_plans(user, date(2026, 1, 1))) == 1
    finally:
        get_settings.cache_clear()


def test_maintenance_prunes_on_day_rollover(db_session_factory, monkeypatch):
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    get_settings.cache_clear()
    try:
        user = "ws020-rollover"
        world = world_repository.ensure_world(user)
        repo.save_plan(_plan(user, plan_date=date(2026, 1, 1)))
        anchor = datetime(2026, 9, 14, 9, 0)
        repo.commit_time_advance(world.world_id, anchor, anchor)

        world_engine.run_simulation_maintenance(user, now=anchor)

        assert repo.get_day_plans(user, date(2026, 1, 1)) == []
    finally:
        get_settings.cache_clear()


# --- M4：时间推进锚点条件写入 ------------------------------------------------


def test_commit_time_advance_rejects_earlier_anchor(db_session_factory):
    user = "ws020-anchor"
    world = world_repository.ensure_world(user)
    later = datetime(2026, 9, 14, 12, 0)
    earlier = datetime(2026, 9, 14, 10, 0)

    assert repo.commit_time_advance(world.world_id, later, later) is True
    assert repo.commit_time_advance(world.world_id, earlier, earlier) is False

    stored = world_repository.get_world(user)
    assert stored.sim_last_advanced_at == later
    assert stored.sim_time == later


def test_commit_time_advance_advances_monotonically(db_session_factory):
    user = "ws020-anchor-fwd"
    world = world_repository.ensure_world(user)

    assert repo.commit_time_advance(
        world.world_id, datetime(2026, 9, 14, 10, 0), datetime(2026, 9, 14, 10, 0)
    )
    assert repo.commit_time_advance(
        world.world_id, datetime(2026, 9, 14, 11, 0), datetime(2026, 9, 14, 11, 0)
    )

    stored = world_repository.get_world(user)
    assert stored.sim_last_advanced_at == datetime(2026, 9, 14, 11, 0)


# --- M5：时间标记豁免配额 + 丢弃可观测 ---------------------------------------


def test_time_marker_exempt_from_active_event_quota(
    db_session_factory, monkeypatch
):
    monkeypatch.setenv("WORLD_ACTIVE_EVENTS_LIMIT", "1")
    get_settings.cache_clear()
    try:
        user = "ws020-quota"
        world = world_repository.ensure_world(user)
        world_engine.reset_event_quota_drop_snapshot()
        _fill_quota(world.world_id, "world_event")

        assert (
            world_engine.create_event(
                user,
                event_type="world_event",
                source="simulation",
                idempotency_key="quota:blocked",
            )
            is None
        )
        marker = world_engine.create_event(
            user,
            event_type="time_marker",
            source="time",
            status="completed",
            idempotency_key="time:day_start:2026-09-14",
        )
        assert marker is not None
        assert marker.idempotency_key == "time:day_start:2026-09-14"
    finally:
        get_settings.cache_clear()


def test_event_quota_drop_is_observable(db_session_factory, monkeypatch):
    monkeypatch.setenv("WORLD_ACTIVE_EVENTS_LIMIT", "1")
    get_settings.cache_clear()
    try:
        user = "ws020-quota-count"
        world = world_repository.ensure_world(user)
        world_engine.reset_event_quota_drop_snapshot()
        _fill_quota(world.world_id, "world_event")

        world_engine.create_event(user, event_type="world_event", source="simulation")

        snapshot = world_engine.event_quota_drop_snapshot()
        assert snapshot["total"] == 1
        assert snapshot["by_type"]["world_event"] == 1
    finally:
        get_settings.cache_clear()


def _fill_quota(world_id: str, event_type: str) -> None:
    now = datetime(2026, 9, 14, 6, 0)
    world_repository.save_event(
        WorldEvent(
            id=world_repository.new_event_id(),
            world_id=world_id,
            type=event_type,
            title="占位",
            status="scheduled",
            source="simulation",
            payload={},
            created_at=now,
            updated_at=now,
        )
    )


# --- M3：日循环观测锚点持久化 ------------------------------------------------


def test_day_cycle_observation_survives_process_state_loss(
    db_session_factory, monkeypatch
):
    """清除进程内状态后仍能正确判定时段切换（观测锚点存 DB）。"""
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    get_settings.cache_clear()
    try:
        user = "ws020-observe"
        world = world_repository.ensure_world(user)
        repo.commit_time_advance(
            world.world_id,
            datetime(2026, 9, 14, 10, 0),
            datetime(2026, 9, 14, 10, 0),
        )
        day_cycle.reset_observation(user)

        assert day_cycle.emit_time_markers(user) == ["time:day_start:2026-09-14"]

        observation = repo.get_day_cycle_observation(world.world_id)
        assert observation is not None
        assert observation["part_of_day"] == "morning"

        repo.commit_time_advance(
            world.world_id,
            datetime(2026, 9, 14, 15, 0),
            datetime(2026, 9, 14, 15, 0),
        )
        emitted = day_cycle.emit_time_markers(user)
        assert emitted == ["time:part:2026-09-14:dusk"]
    finally:
        get_settings.cache_clear()


def test_day_cycle_observation_cleared_on_reset(db_session_factory):
    user = "ws020-observe-reset"
    world = world_repository.ensure_world(user)
    repo.save_day_cycle_observation(
        world.world_id,
        observed_at=datetime(2026, 9, 14, 10, 0),
        part_of_day="morning",
        time_mode="real_sync",
    )
    assert repo.get_day_cycle_observation(world.world_id) is not None

    day_cycle.reset_observation(user)

    assert repo.get_day_cycle_observation(world.world_id) is None


# --- m1：批量写入保持 supersede 语义 ----------------------------------------


def test_replace_day_plans_keeps_superseded_audit_rows(db_session_factory):
    user = "ws020-batch"
    first = daily_plan.build_daily_plan(user, date(2026, 9, 14))
    second = daily_plan.build_daily_plan(user, date(2026, 9, 14))

    rows = repo.get_day_plans(user, date(2026, 9, 14))
    assert len(rows) == len(first) * 2
    superseded = [p for p in rows if p.status == DailyPlanStatus.SUPERSEDED]
    assert len(superseded) == len(first)
    open_plans = repo.get_day_plans(user, date(2026, 9, 14), repo.OPEN_PLAN_STATUSES)
    assert {p.id for p in open_plans} == {p.id for p in second}


# --- m6：world_digest 幂等键确定性 ------------------------------------------


def test_world_digest_key_is_deterministic():
    drafts = [
        {"importance": "low", "idempotency_key": "time:part:day:a"},
        {"importance": "low", "idempotency_key": "time:part:day:b"},
        {"importance": "low", "idempotency_key": "time:part:day:c"},
    ]
    first = world_engine._digest_idempotency_key("u1", drafts)
    shuffled = [drafts[2], drafts[0], drafts[1]]
    assert world_engine._digest_idempotency_key("u1", shuffled) == first
    assert world_engine._digest_idempotency_key("u2", drafts) != first


def test_rank_drafts_is_stable_across_input_order():
    drafts = [
        {"importance": "normal", "idempotency_key": "b"},
        {"importance": "normal", "idempotency_key": "a"},
        {"importance": "high", "idempotency_key": "c"},
    ]
    ranked = world_engine._rank_drafts(drafts)
    assert [d["idempotency_key"] for d in ranked] == ["c", "a", "b"]
    assert world_engine._rank_drafts(list(reversed(drafts))) == ranked
