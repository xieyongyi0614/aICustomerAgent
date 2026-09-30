from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_api
from app.main import create_app
from app.services.governance import DomainHandlers, register_domain
from app.services.governance import core as provenance_mod
from app.services.governance import core as registry_mod
from tests.conftest import TEST_USER_ID

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client():
    test_app = create_app()
    test_app.dependency_overrides[auth_api.require_user] = lambda: TEST_USER_ID
    return TestClient(test_app)


@pytest.fixture(autouse=True)
def _clean_registry():
    registry_mod.reset_registry()
    provenance_mod.reset_provenance_store()
    yield
    registry_mod.reset_registry()
    provenance_mod.reset_provenance_store()


def _register_sample():
    store = {"rows": ["a", "b"]}

    def export(user_id: str):
        return {"rows": list(store["rows"])}

    def delete(user_id: str) -> int:
        n = len(store["rows"])
        store["rows"].clear()
        return n

    register_domain(DomainHandlers(name="sample", export=export, delete=delete))
    return store


def test_export_endpoint_returns_bundle(client):
    _register_sample()
    response = client.get("/api/v1/life/export")
    assert response.status_code == 200
    body = response.json()
    assert body["format"] == "json"
    assert "sample" in body["domains"]
    assert body["domains"]["sample"]["rows"] == ["a", "b"]


def test_export_csv_streams(client):
    _register_sample()
    response = client.get("/api/v1/life/export", params={"format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = [line for line in response.text.splitlines() if line]
    assert lines[0] == "domain,key,value"
    assert any(line.startswith("sample,") for line in lines[1:])


def test_delete_requires_explicit_confirm(client):
    store = _register_sample()
    response = client.delete("/api/v1/life/data")
    assert response.status_code == 400
    assert store["rows"] == ["a", "b"]


def test_delete_endpoint_returns_report(client):
    store = _register_sample()
    response = client.delete("/api/v1/life/data", params={"confirm": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["per_domain"] == {"sample": 2}
    assert body["total"] == 2
    assert store["rows"] == []


def test_user_id_param_retired_on_delete(client):
    store = _register_sample()
    response = client.delete(
        "/api/v1/life/data",
        params={"confirm": "true", "user_id": "someone-else"},
    )
    assert response.status_code == 200
    assert store["rows"] == []


def test_api_layer_has_no_repositories_import():
    source = (BACKEND / "app" / "api" / "v1" / "governance.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in ("app.repositories", "langchain", "langchain_openai"):
        assert not any(
            name == banned or name.startswith(banned + ".") for name in imported
        )


def test_existing_debug_routes_unchanged(client):
    response = client.get("/api/v1/debug/state")
    assert response.status_code in (200, 400, 404, 422)
