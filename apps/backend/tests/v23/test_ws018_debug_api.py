"""WS-018：世界模拟调试端点（开关固化后的常开行为）。"""

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import timeutil
from app.api.v1.schemas import WorldSimulationOut
from app.application import world_engine
from app.main import app
from app.models.world_simulation import (
    DailyPlan,
    DailyPlanStatus,
    SituationDimension,
    UserSituation,
)
from app.repositories import world_repository, world_simulation_repository

pytestmark = pytest.mark.xdist_group("ws018")


async def _get(path: str, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, params=params)


async def _post(path: str, json: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=json)


def _seed_world(user: str) -> None:
    world_repository.ensure_world(user)
    world_engine.create_event(
        user,
        event_type="weather_change",
        title="外面转凉了",
        importance="normal",
        source="simulation",
        status="completed",
        idempotency_key=f"weather:{user}:2026-09-14",
    )
    now = timeutil.now()
    world_simulation_repository.save_plan(
        DailyPlan(
            id=world_simulation_repository.new_plan_id(),
            user_id=user,
            plan_date=now.date(),
            seq=0,
            part_of_day="morning",
            start_minutes=480,
            end_minutes=540,
            activity="晨间整理",
            location_id="home.living_room",
            status=DailyPlanStatus.ACTIVE,
            created_at=now,
        )
    )
    world_simulation_repository.save_situation(
        UserSituation(
            id=world_simulation_repository.new_situation_id(),
            user_id=user,
            dimension=SituationDimension.HEALTH,
            summary="用户身体不适",
            intensity=4,
            detected_at=now,
        )
    )


def test_schema_serialization_disabled():
    payload = WorldSimulationOut(enabled=False).model_dump(mode="json")
    assert payload["enabled"] is False
    assert payload["active_situations"] == []
    assert payload["recent_events"] == []
    assert payload["flags"] == {}


@pytest.mark.asyncio
async def test_simulation_endpoint_matches_db(db_session_factory):
    user = "ws018-on"
    _seed_world(user)

    resp = await _get("/api/v1/debug/world/simulation", user_id=user)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["time_context"] is not None
    assert body["brief"]["text"]
    assert body["current_block"]["activity"] == "晨间整理"
    assert body["current_block"]["status"] == "active"
    assert body["active_situations"][0]["dimension"] == "health"
    assert body["active_situations"][0]["intensity"] == 4
    assert body["recent_events"][0]["type"] == "weather_change"
    assert body["recent_events"][0]["idempotency_key"] == f"weather:{user}:2026-09-14"
    assert body["flags"] == {}


@pytest.mark.asyncio
async def test_plan_endpoint_and_date_validation(db_session_factory):
    user = "ws018-plan"
    _seed_world(user)

    resp = await _get("/api/v1/debug/world/plan", user_id=user)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["date"] == timeutil.now().date().isoformat()
    rows = [b for b in body["blocks"] if b["activity"] == "晨间整理"]
    assert rows and rows[0]["variability_source"]

    bad = await _get("/api/v1/debug/world/plan", user_id=user, date="not-a-date")
    assert bad.status_code == 422
    assert "detail" in bad.json()


@pytest.mark.asyncio
async def test_situations_endpoint_include_expired(db_session_factory):
    user = "ws018-sit"
    _seed_world(user)
    now = timeutil.now()
    world_simulation_repository.save_situation(
        UserSituation(
            id=world_simulation_repository.new_situation_id(),
            user_id=user,
            dimension=SituationDimension.TRAVEL,
            summary="用户外出中",
            intensity=2,
            status="expired",
            detected_at=now,
        )
    )

    active = await _get("/api/v1/debug/world/situations", user_id=user)
    assert [s["dimension"] for s in active.json()["situations"]] == ["health"]

    all_rows = await _get(
        "/api/v1/debug/world/situations", user_id=user, include_expired="true"
    )
    assert {s["dimension"] for s in all_rows.json()["situations"]} == {"health", "travel"}


@pytest.mark.asyncio
async def test_unknown_user_returns_404(db_session_factory):
    resp = await _get("/api/v1/debug/world/simulation", user_id="ws018-missing")
    assert resp.status_code == 404
    assert resp.json()["detail"]


@pytest.mark.asyncio
async def test_tick_runs_maintenance(db_session_factory):
    user = "ws018-tick-ok"
    _seed_world(user)
    resp = await _post("/api/v1/debug/world/simulation/tick", json={"user_id": user})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["result"]["advanced_minutes"] >= 0
    assert body["result"]["errors"] == []
    assert body["result"]["plan_summary"] is not None
    assert body["result"]["plan_summary"]["date"] == timeutil.now().date().isoformat()


@pytest.mark.asyncio
async def test_readonly_endpoints_do_not_mutate(db_session_factory):
    user = "ws018-readonly"
    _seed_world(user)
    world = world_repository.ensure_world(user)
    before = len(world_repository.list_events(world.world_id, limit=100))

    await _get("/api/v1/debug/world/simulation", user_id=user)
    await _get("/api/v1/debug/world/plan", user_id=user)
    await _get("/api/v1/debug/world/situations", user_id=user)

    after = len(world_repository.list_events(world.world_id, limit=100))
    assert before == after
    assert len(world_engine.build_debug_plan(user, timeutil.now().date())) == 1
