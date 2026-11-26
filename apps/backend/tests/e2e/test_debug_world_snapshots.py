"""V8-013 快照历史查询与恢复端点。"""

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_snapshot_history_and_restore_endpoints(db_session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/debug/world/entities",
            json={"name": "西瓜", "category": "food", "location_id": "home.living_room"},
        )
        snap = await client.post(
            "/api/v1/debug/world/snapshots", json={"label": "baseline"}
        )
        assert snap.status_code == 200
        snapshot_id = snap.json()["id"]

        listed = await client.get("/api/v1/debug/world/snapshots")
        assert [row["id"] for row in listed.json()] == [snapshot_id]

        await client.post(
            "/api/v1/debug/world/entities",
            json={"name": "蛋糕", "category": "food", "location_id": "home.living_room"},
        )
        detail = await client.get(f"/api/v1/debug/world/snapshots/{snapshot_id}")
        assert detail.status_code == 200
        baseline_names = {o["name"] for o in detail.json()["state"]["entities"]}
        assert "西瓜" in baseline_names
        assert len(baseline_names) == 1

        restored = await client.post(f"/api/v1/debug/world/snapshots/{snapshot_id}/restore")
        assert restored.status_code == 200
        state = await client.get("/api/v1/debug/world")
        restored_names = {o["name"] for o in state.json()["entities"]}
        assert "西瓜" in restored_names
        assert "蛋糕" not in restored_names
        assert len(restored_names) == 1

        missing = await client.post("/api/v1/debug/world/snapshots/snap_missing/restore")
        assert missing.status_code == 404
        assert (
            await client.get("/api/v1/debug/world/snapshots/snap_missing")
        ).status_code == 404
