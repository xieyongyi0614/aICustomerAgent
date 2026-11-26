"""ADR-16 §7 安全三动作钉测：调试面环境门禁 + 产品端点忽略显式 user_id。"""

import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import app
from app.repositories import memory_repository
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _enforce_debug_surface(monkeypatch):
    monkeypatch.setattr(get_settings(), "debug_surface_enforced", True)


def test_gate_disabled_returns_404(client, monkeypatch):
    _enforce_debug_surface(monkeypatch)
    for path in (
        "/api/v1/debug/tools",
        "/api/v1/state",
        "/api/v1/action",
        "/api/v1/debug/world",
    ):
        resp = client.get(path)
        assert resp.status_code == 404, path


def test_gate_not_enforced_by_default_allows_debug_surface(client):
    assert client.get("/api/v1/debug/tools").status_code == 200
    assert client.get("/api/v1/state").status_code == 200
    assert client.get("/api/v1/debug/world").status_code == 200


def test_product_endpoint_ignores_explicit_user_id(client, db_session_factory):
    memory_repository.create_memory(
        TEST_USER_ID, "asuna", "token 用户的记忆", "user_preference", 0.8
    )
    memory_repository.create_memory(
        "attacker", "asuna", "攻击者的记忆", "user_preference", 0.8
    )

    plain = client.get("/api/v1/memories")
    forged = client.get("/api/v1/memories", params={"user_id": "attacker"})

    assert plain.status_code == 200
    assert forged.status_code == 200
    assert plain.json()["user_id"] == TEST_USER_ID
    assert forged.json()["user_id"] == TEST_USER_ID
    contents = {m["memory"] for m in forged.json()["memories"]}
    assert "token 用户的记忆" in contents
    assert "攻击者的记忆" not in contents
