"""V8.5 /debug/relationship 三端点（state/timeline/rollback）e2e 测试。"""

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.relationship import RelationshipDelta, RelationshipEvent, RelationshipState
from app.repositories import (
    relationship_event_repository,
    relationship_repository,
    relationship_snapshot_repository,
)

NOW = datetime(2026, 8, 31, 12, 0, 0)


@pytest.fixture
def repos(db_session_factory, monkeypatch):
    monkeypatch.setattr(relationship_snapshot_repository, "SessionLocal", db_session_factory)
    return db_session_factory


def _seed_relationship(user_id="u1"):
    for i in range(3):
        relationship_repository.upsert_relationship(
            user_id,
            RelationshipState(trust=0.4 + i * 0.1, version=i + 1),
        )
        relationship_event_repository.create_event(
            RelationshipEvent(
                user_id=user_id,
                session_id="s1",
                type="praise",
                magnitude="normal",
                impact=RelationshipDelta(trust=0.1),
                confidence=0.9,
                created_at=NOW + timedelta(hours=i),
            )
        )
        relationship_snapshot_repository.create_snapshot(
            user_id,
            i + 1,
            RelationshipState(trust=0.4 + i * 0.1, version=i + 1),
            trigger="stage_check",
            now=NOW + timedelta(hours=i),
        )


@pytest.mark.asyncio
async def test_relationship_state_endpoint(repos):
    _seed_relationship()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/debug/relationship/state", params={"user_id": "u1"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "u1"
        assert body["state"]["version"] == 3
        assert "distance_index" in body["derived"]


@pytest.mark.asyncio
async def test_relationship_timeline_merges_kinds(repos):
    _seed_relationship()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/debug/relationship/timeline", params={"user_id": "u1"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        kinds = {item["kind"] for item in items}
        assert "event" in kinds and "snapshot" in kinds
        assert all(items[i]["at"] >= items[i + 1]["at"] for i in range(len(items) - 1))


@pytest.mark.asyncio
async def test_relationship_rollback_to_anchor(repos):
    _seed_relationship()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/debug/relationship/rollback",
            params={"user_id": "u1", "target_version": 1},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["anchor_version"] == 1
        assert body["replayed_events"] == 2
        assert body["final_state"]["trust"] == pytest.approx(0.6)
        assert body["final_state"]["version"] == 4


@pytest.mark.asyncio
async def test_relationship_rollback_without_snapshot_404(repos):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/debug/relationship/rollback",
            params={"user_id": "nobody", "target_version": 1},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_relationship_rollback_before_earliest_400(repos):
    _seed_relationship()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/debug/relationship/rollback",
            params={"user_id": "u1", "target_version": 0},
        )
        assert resp.status_code == 400