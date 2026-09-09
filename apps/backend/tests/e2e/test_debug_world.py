"""V8 debug world 端点：全量状态、手动播种、环境、位置、快照。"""

from httpx import ASGITransport, AsyncClient
import pytest

from app.character.asuna.world import DEFAULT_HOUSEHOLD
from app.main import app


@pytest.mark.asyncio
async def test_debug_world_endpoints(db_session_factory):
    seed_names = {o["name"] for o in DEFAULT_HOUSEHOLD["objects"]}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        state = await client.get("/api/v1/debug/world")
        assert state.status_code == 200
        body = state.json()
        assert body["world"]["current_location"] == "home.living_room"
        assert {o["name"] for o in body["entities"]} == seed_names

        created = await client.post(
            "/api/v1/debug/world/entities",
            json={"name": "西瓜", "category": "food", "location_id": "home.kitchen.fridge", "aliases": ["瓜"]},
        )
        assert created.status_code == 200
        assert created.json()["state"] == "whole"

        env = await client.post(
            "/api/v1/debug/world/environment", json={"weather": "rain", "temperature_c": 18.0}
        )
        assert env.status_code == 200
        assert env.json()["weather"] == "rain"

        moved = await client.post(
            "/api/v1/debug/world/location", json={"location_id": "home.kitchen"}
        )
        assert moved.status_code == 200
        bad_move = await client.post(
            "/api/v1/debug/world/location", json={"location_id": "mars"}
        )
        assert bad_move.status_code == 404

        snap = await client.post(
            "/api/v1/debug/world/snapshots", json={"label": "manual"}
        )
        assert snap.status_code == 200
        listed = await client.get("/api/v1/debug/world/snapshots")
        assert [row["label"] for row in listed.json()] == ["manual"]

        state = await client.get("/api/v1/debug/world")
        assert state.json()["world"]["current_location"] == "home.kitchen"
        assert {o["name"] for o in state.json()["entities"]} == seed_names | {"西瓜"}
