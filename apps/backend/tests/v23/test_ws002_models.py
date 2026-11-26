"""WS-002：daily_plans / user_situations 模型、约束与仓储测试。"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import timeutil
from app.core.db import DailyPlanRow, UserSituationRow, WorldEventRow
from app.models.world import EventImportance, EventSource, EventStatus, WorldEvent
from app.models.world_simulation import (
    DailyPlan,
    DailyPlanStatus,
    DailyPlanVariability,
    SituationDimension,
    SituationSource,
    SituationStatus,
    UserSituation,
)
from app.repositories import world_repository, world_simulation_repository as repo

pytestmark = pytest.mark.xdist_group("ws002")


def _plan(user_id: str = "ws002-user", seq: int = 0, **overrides) -> DailyPlan:
    values = dict(
        id=repo.new_plan_id(),
        user_id=user_id,
        plan_date=date(2026, 9, 14),
        seq=seq,
        part_of_day="evening",
        start_minutes=1080,
        end_minutes=1260,
        activity="阅读",
        location_id="home.living_room",
        variability_source=DailyPlanVariability.FIXED,
        status=DailyPlanStatus.PLANNED,
        routine_version=1,
        note=None,
    )
    values.update(overrides)
    return DailyPlan(**values)


def _situation(user_id: str = "ws002-user", **overrides) -> UserSituation:
    now = timeutil.ensure_aware(datetime(2026, 9, 14, 20, 0))
    values = dict(
        id=repo.new_situation_id(),
        user_id=user_id,
        dimension=SituationDimension.HEALTH,
        summary="用户感冒了",
        intensity=4,
        status=SituationStatus.ACTIVE,
        source=SituationSource.CONVERSATION_PATTERN,
        evidence={"message_id": "m1", "quote": "我感冒了"},
        detected_at=now,
        valid_until=now + timedelta(hours=48),
    )
    values.update(overrides)
    return UserSituation(**values)


def test_plan_round_trip(db_session_factory):
    plan = _plan()
    repo.save_plan(plan)
    loaded = repo.get_plan(plan.user_id, plan.id)
    assert loaded is not None
    assert loaded.activity == "阅读"
    assert loaded.status == DailyPlanStatus.PLANNED
    assert loaded.variability_source == DailyPlanVariability.FIXED


def test_supersede_open_plans_keeps_terminal(db_session_factory):
    open_plan = _plan(seq=0)
    completed = _plan(seq=1, status=DailyPlanStatus.COMPLETED)
    repo.save_plan(open_plan)
    repo.save_plan(completed)
    assert repo.supersede_open_plans(open_plan.user_id, open_plan.plan_date) == 1
    assert repo.get_plan(open_plan.user_id, open_plan.id).status == DailyPlanStatus.SUPERSEDED
    assert repo.get_plan(open_plan.user_id, completed.id).status == DailyPlanStatus.COMPLETED


def test_day_plans_filter_by_status(db_session_factory):
    user = "ws002-filter"
    repo.save_plan(_plan(user, seq=0, status=DailyPlanStatus.PLANNED))
    repo.save_plan(_plan(user, seq=1, status=DailyPlanStatus.SKIPPED))
    repo.save_plan(_plan(user, seq=2, status=DailyPlanStatus.SUPERSEDED))
    open_plans = repo.get_day_plans(user, date(2026, 9, 14), repo.OPEN_PLAN_STATUSES)
    assert [p.seq for p in open_plans] == [0]
    all_plans = repo.get_day_plans(user, date(2026, 9, 14))
    assert len(all_plans) == 3


def test_prune_plans_before(db_session_factory):
    user = "ws002-prune"
    repo.save_plan(_plan(user, plan_date=date(2026, 8, 1)))
    repo.save_plan(_plan(user, seq=1, plan_date=date(2026, 9, 14)))
    removed = repo.prune_plans_before(user, date(2026, 9, 1))
    assert removed == 1
    assert len(repo.get_day_plans(user, date(2026, 9, 14))) == 1


def test_invalid_part_of_day_rejected(db_session_factory):
    with pytest.raises(IntegrityError):
        with db_session_factory() as session:
            session.add(
                DailyPlanRow(
                    id=repo.new_plan_id(),
                    user_id="ws002-ck",
                    plan_date=date(2026, 9, 14),
                    seq=0,
                    part_of_day="noon",
                    start_minutes=0,
                    end_minutes=10,
                    activity="阅读",
                    location_id="home.living_room",
                    created_at=timeutil.ensure_aware(datetime(2026, 9, 14, 6, 0)),
                    updated_at=timeutil.ensure_aware(datetime(2026, 9, 14, 6, 0)),
                )
            )
            session.commit()


def test_situation_round_trip_and_active_lookup(db_session_factory):
    situation = _situation()
    repo.save_situation(situation)
    loaded = repo.get_situation(situation.user_id, situation.id)
    assert loaded.dimension == SituationDimension.HEALTH
    assert loaded.intensity == 4
    assert loaded.evidence["quote"] == "我感冒了"

    replacement = _situation(intensity=2, summary="感冒加重")
    repo.save_situation(replacement)
    active = repo.get_active_situation(situation.user_id, SituationDimension.HEALTH)
    assert active.id in {situation.id, replacement.id}


def test_superseded_active_situation_single_row(db_session_factory):
    user = "ws002-supersede"
    first = _situation(user)
    repo.save_situation(first)
    first.status = SituationStatus.EXPIRED
    repo.save_situation(first)
    second = _situation(user)
    repo.save_situation(second)
    statuses = {s.id: s.status for s in repo.list_situations(user)}
    assert statuses[first.id] == SituationStatus.EXPIRED
    assert statuses[second.id] == SituationStatus.ACTIVE


def test_expire_stale_situations(db_session_factory):
    user = "ws002-expire"
    stale = _situation(user, valid_until=timeutil.ensure_aware(datetime(2026, 9, 13, 0, 0)))
    fresh = _situation(user, valid_until=timeutil.ensure_aware(datetime(2026, 9, 20, 0, 0)))
    no_expiry = _situation(user, valid_until=None)
    for item in (stale, fresh, no_expiry):
        repo.save_situation(item)
    expired = repo.expire_stale_situations(user, timeutil.ensure_aware(datetime(2026, 9, 14, 12, 0)))
    assert [s.id for s in expired] == [stale.id]
    assert repo.get_situation(user, stale.id).status == SituationStatus.EXPIRED
    assert repo.get_situation(user, fresh.id).status == SituationStatus.ACTIVE
    assert repo.get_situation(user, no_expiry.id).status == SituationStatus.ACTIVE


def test_invalid_intensity_rejected(db_session_factory):
    with pytest.raises(IntegrityError):
        with db_session_factory() as session:
            session.add(
                UserSituationRow(
                    id=repo.new_situation_id(),
                    user_id="ws002-ck",
                    dimension="health",
                    summary="用户感冒了",
                    intensity=6,
                    detected_at=timeutil.ensure_aware(datetime(2026, 9, 14, 8, 0)),
                    updated_at=timeutil.ensure_aware(datetime(2026, 9, 14, 8, 0)),
                )
            )
            session.commit()
    with pytest.raises(ValueError):
        _situation(intensity=6)


def test_idempotency_key_unique_when_present(db_session_factory):
    world_id = "home:ws002-idem"
    world_repository.ensure_world("ws002-idem")

    def _event(key: str | None, event_id: str) -> WorldEvent:
        return WorldEvent(
            id=event_id,
            world_id=world_id,
            type="time_marker",
            title="day_start",
            importance=EventImportance.NORMAL,
            status=EventStatus.COMPLETED,
            payload={"date": "2026-09-14"},
            source=EventSource.TIME,
            idempotency_key=key,
            created_at=timeutil.ensure_aware(datetime(2026, 9, 14, 6, 0)),
        )

    world_repository.save_event(_event("time:day_start:2026-09-14", "evt_a"))
    world_repository.save_event(_event(None, "evt_b"))
    world_repository.save_event(_event(None, "evt_c"))
    with pytest.raises(IntegrityError):
        world_repository.save_event(_event("time:day_start:2026-09-14", "evt_d"))

    existing = repo.get_latest_idempotency_keys(
        world_id, ["time:day_start:2026-09-14", "time:day_start:2026-09-15"]
    )
    assert existing == {"time:day_start:2026-09-14"}


def test_commit_time_advance_updates_anchor(db_session_factory):
    world = world_repository.ensure_world("ws002-anchor")
    anchor = timeutil.ensure_aware(datetime(2026, 9, 14, 12, 0))
    sim_time = timeutil.ensure_aware(datetime(2026, 9, 14, 13, 0))
    assert repo.commit_time_advance(world.world_id, sim_time, anchor)
    stored = world_repository.get_world("ws002-anchor")
    assert stored.sim_time == sim_time
    assert stored.sim_last_advanced_at == anchor
    assert not repo.commit_time_advance("home:missing", sim_time, anchor)


def test_invalid_plan_status_rejected(db_session_factory):
    with pytest.raises(IntegrityError):
        with db_session_factory() as session:
            session.add(
                DailyPlanRow(
                    id=repo.new_plan_id(),
                    user_id="ws002-ck",
                    plan_date=date(2026, 9, 14),
                    seq=9,
                    part_of_day="evening",
                    start_minutes=0,
                    end_minutes=10,
                    activity="阅读",
                    location_id="home.living_room",
                    status="done",
                    created_at=timeutil.ensure_aware(datetime(2026, 9, 14, 6, 0)),
                    updated_at=timeutil.ensure_aware(datetime(2026, 9, 14, 6, 0)),
                )
            )
            session.commit()
    with pytest.raises(ValueError):
        _plan(status="done")
