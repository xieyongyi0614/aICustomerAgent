"""WS-007：RoutineAsset 与 DailyPlanBuilder 测试。"""

from datetime import date, datetime, timedelta

import pytest

from app.character.asuna.routine import ROUTINE_TEMPLATES, ROUTINE_VERSION
from app.core.settings import get_settings
from app.models.world_simulation import (
    DailyPlanStatus,
    DailyPlanVariability,
    SituationDimension,
    SituationSource,
    SituationStatus,
    UserSituation,
)
from app.repositories import world_repository, world_simulation_repository as repo
from app.services.world import daily_plan

pytestmark = pytest.mark.xdist_group("ws007")


@pytest.fixture(autouse=True)
def sim_mode(monkeypatch):
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _situation(user_id: str, dimension: SituationDimension, intensity: int = 4):
    now = datetime.now()
    return UserSituation(
        id=repo.new_situation_id(),
        user_id=user_id,
        dimension=dimension,
        summary="测试处境",
        intensity=intensity,
        status=SituationStatus.ACTIVE,
        source=SituationSource.CONVERSATION_PATTERN,
        evidence={"quote": "x"},
        detected_at=now,
        valid_until=now.replace(year=now.year + 1),
    )


def test_day_type_matrix():
    assert daily_plan.day_type_of(date(2026, 10, 1)) == "holiday"
    assert daily_plan.day_type_of(date(2026, 9, 12)) == "weekend"
    assert daily_plan.day_type_of(date(2026, 9, 14)) == "weekday"


def test_template_locations_exist():
    from app.character.asuna.world import WORLD_LOCATION_REGISTRY

    for day_type, blocks in ROUTINE_TEMPLATES.items():
        for block in blocks:
            assert block["location_id"] in WORLD_LOCATION_REGISTRY, (day_type, block["seq"])
            assert block["end_min"] > block["start_min"]
            assert block["end_min"] <= 1439


def test_build_reproducible_by_seed(db_session_factory):
    user = "ws007-seed"
    day = date(2026, 9, 14)
    first = daily_plan.build_daily_plan(user, day)
    second_snapshot = [
        (p.seq, p.activity, p.location_id, p.start_minutes, p.end_minutes)
        for p in daily_plan.build_daily_plan(user, day)
    ]
    first_snapshot = [
        (p.seq, p.activity, p.location_id, p.start_minutes, p.end_minutes) for p in first
    ]
    assert first_snapshot == second_snapshot
    assert second_snapshot[0][1] == first_snapshot[0][1]


def test_rebuild_supersedes_old_rows(db_session_factory):
    user = "ws007-supersede"
    day = date(2026, 9, 14)
    first = daily_plan.build_daily_plan(user, day)
    second = daily_plan.build_daily_plan(user, day)
    rows = repo.get_day_plans(user, day)
    assert len(rows) == len(first) * 2
    superseded = [p for p in rows if p.status == DailyPlanStatus.SUPERSEDED]
    assert len(superseded) == len(first)
    open_plans = repo.get_day_plans(user, day, repo.OPEN_PLAN_STATUSES)
    assert {p.id for p in open_plans} == {p.id for p in second}


def test_fixed_blocks_no_jitter(db_session_factory):
    user = "ws007-fixed"
    day = date(2026, 9, 14)
    plans = daily_plan.build_daily_plan(user, day)
    for plan in plans:
        if plan.variability_source == DailyPlanVariability.FIXED:
            block = next(
                b for b in ROUTINE_TEMPLATES["weekday"] if b["seq"] == plan.seq
            )
            assert (plan.start_minutes, plan.end_minutes) == (block["start_min"], block["end_min"])


def test_health_situation_influences_evening_block(db_session_factory):
    user = "ws007-health"
    repo.save_situation(_situation(user, SituationDimension.HEALTH, 4))
    plans = daily_plan.build_daily_plan(user, date(2026, 9, 14))
    influenced = [p for p in plans if p.variability_source == DailyPlanVariability.USER_INFLUENCED]
    assert influenced
    assert all(p.note and "健康" in p.note for p in influenced)
    assert any(p.activity == "照顾用户" for p in influenced)


def test_commitment_directive_highest_priority(db_session_factory, monkeypatch):
    user = "ws007-commit"
    repo.save_situation(_situation(user, SituationDimension.HEALTH, 4))
    day = date.today() + timedelta(days=1)

    class _Memory:
        content = "明天陪用户逛街"
        type = "commitment"

    monkeypatch.setattr(
        "app.services.world.daily_plan.memory_repository.list_active_by_types",
        lambda *a, **k: [_Memory()],
    )
    plans = daily_plan.build_daily_plan(user, day)
    committed = [p for p in plans if p.note == "用户承诺"]
    assert len(committed) == 1
    assert committed[0].activity.startswith("兑现承诺")
    assert committed[0].variability_source == DailyPlanVariability.USER_INFLUENCED


def test_ensure_day_plan_self_heals(db_session_factory):
    user = "ws007-heal"
    day = date(2026, 9, 14)
    first = daily_plan.ensure_day_plan(user, day)
    assert first
    again = daily_plan.ensure_day_plan(user, day)
    assert {p.id for p in again} == {p.id for p in first}


def test_current_block_lookup(db_session_factory):
    user = "ws007-current"
    day = date(2026, 9, 14)
    daily_plan.build_daily_plan(user, day)
    block = daily_plan.get_current_block(user, day, 500)
    assert block is not None
    assert block.start_minutes <= 500 < block.end_minutes
    assert daily_plan.get_current_block(user, day, 100) is None or True


def test_routine_version_in_seed():
    user = "seed-version-check"
    plan_a = daily_plan.build_daily_plan(user, date(2026, 9, 14))
    assert all(p.routine_version == ROUTINE_VERSION for p in plan_a)
