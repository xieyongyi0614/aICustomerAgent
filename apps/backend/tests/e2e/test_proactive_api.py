"""V7-007：GET /proactive/pending 与 POST /proactive/{id}/ack 契约（Case 11）。"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models.autonomy import ProactiveAction
from app.repositories import proactive_repository

NOW = datetime(2026, 8, 30, 14, 0)


def _action(**overrides) -> ProactiveAction:
    payload = {
        "id": "api-a1",
        "user_id": "default-user",
        "session_id": "s1",
        "trigger_type": "conversation_inactivity",
        "dedupe_key": "inactivity:default-user:1",
        "intention": "check_in",
        "reason": "闲置关心",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return ProactiveAction(**payload)


def _client():
    return TestClient(app)


def test_pending_empty_by_default(db_session_factory):
    with _client() as client:
        resp = client.get("/api/v1/proactive/pending")
        assert resp.status_code == 200
        assert resp.json() == {"actions": []}


def test_pending_lists_delivered_and_ack_transitions(
    db_session_factory, monkeypatch
):
    class _SimClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(minutes=1)

    monkeypatch.setattr(proactive_repository, "datetime", _SimClock)
    proactive_repository.enqueue(_action())
    proactive_repository.transition("api-a1", "approved", now=NOW)
    proactive_repository.transition(
        "api-a1", "delivered", now=NOW, delivered_at=NOW, payload_text="忙完了吗？"
    )
    with _client() as client:
        resp = client.get("/api/v1/proactive/pending")
        actions = resp.json()["actions"]
        assert len(actions) == 1
        assert actions[0]["id"] == "api-a1"
        assert actions[0]["text"] == "忙完了吗？"
        assert actions[0]["intention"] == "check_in"

        ack = client.post("/api/v1/proactive/api-a1/ack")
        assert ack.status_code == 200
        assert ack.json()["status"] == "acked"
        assert client.get("/api/v1/proactive/pending").json()["actions"] == []


def test_ack_unknown_id_404_and_double_ack_409(db_session_factory):
    with _client() as client:
        assert client.post("/api/v1/proactive/missing/ack").status_code == 404

    proactive_repository.enqueue(_action())
    proactive_repository.transition("api-a1", "approved", now=NOW)
    proactive_repository.transition(
        "api-a1", "delivered", now=NOW, delivered_at=NOW
    )
    with _client() as client:
        assert client.post("/api/v1/proactive/api-a1/ack").status_code == 200
        assert client.post("/api/v1/proactive/api-a1/ack").status_code == 409
