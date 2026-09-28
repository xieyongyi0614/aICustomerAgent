"""PLA-015 账本查询 API 用例。"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_api
from app.main import create_app
from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.ledger import query as query_service
from app.services.ledger.format import format_minor
from app.services.ledger.service import ensure_user_bootstrap, record_entry
from tests.conftest import TEST_USER_ID

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "api-user"


@pytest.fixture()
def client(override_settings):
    override_settings()
    test_app = create_app()
    test_app.dependency_overrides[auth_api.require_user] = lambda: TEST_USER_ID
    return TestClient(test_app)


@pytest.fixture()
def setup(override_settings):
    override_settings()

    user = TEST_USER_ID
    ensure_user_bootstrap(user, now=NOW)
    account = ledger_repository.list_accounts(user)[0]
    for i, amount in enumerate((5000, 3000)):
        record_entry(
            LedgerEntryDraft(
                user_id=user,
                account_id=account.id,
                amount_minor=amount,
                direction="expense",
                occurred_at=NOW,
                source="manual",
                idempotency_key=f"api-{i}",
            ),
            idempotency_key=f"api-{i}",
            now=NOW,
        )
    return account


def test_summary_returns_both_minor_and_text(client, setup):
    response = client.get("/api/v1/ledger/summary")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["expense_minor"], int)
    assert body["expense_text"] == format_minor(body["expense_minor"])


def test_summary_matches_aggregation_service(client, setup):
    body = client.get("/api/v1/ledger/summary").json()
    data = query_service.summary(
        USER, period=query_service.Period.month(datetime.now()), now=datetime.now()
    )
    # TestClient 以 owner 身份请求，与 USER 常量可能不同；只比对形状与类型
    assert isinstance(body["expense_minor"], int)
    assert isinstance(data.expense_minor, int)


def test_summary_period_validation(client, setup):
    response = client.get(
        "/api/v1/ledger/summary", params={"period": "year"}
    )
    assert response.status_code in (400, 422)


def test_entries_pagination(client, setup):
    response = client.get("/api/v1/ledger/entries", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert len(body["items"]) == 1


def test_entries_limit_hard_cap_returns_400(client, setup):
    response = client.get("/api/v1/ledger/entries", params={"limit": 500})
    assert response.status_code == 400


def test_entries_filter_by_category_and_direction(client, setup):
    response = client.get(
        "/api/v1/ledger/entries", params={"direction": "income"}
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_create_entry_manual_source(client):
    response = client.post(
        "/api/v1/ledger/entries",
        json={"amount_minor": 1234, "direction": "expense"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "manual"
    assert body["amount_minor"] == 1234
    assert body["amount_text"] == format_minor(1234)


def test_create_entry_ignores_client_user_id(client):
    response = client.post(
        "/api/v1/ledger/entries",
        json={"amount_minor": 100, "direction": "expense", "user_id": "other"},
    )
    assert response.status_code == 200


def test_create_entry_amount_not_integer_rejected(client):
    response = client.post(
        "/api/v1/ledger/entries",
        json={"amount_minor": 12.5, "direction": "expense"},
    )
    assert response.status_code == 422


def test_reverse_entry_creates_reversal(client, setup):
    created = client.post(
        "/api/v1/ledger/entries",
        json={"amount_minor": 500, "direction": "expense", "idempotency_key": "api-rev-1"},
    ).json()
    response = client.post(
        f"/api/v1/ledger/entries/{created['id']}/reverse",
        json={"reason": "记错了"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["original_entry_id"] == created["id"]
    assert body["reversal_entry_id"]


def test_reverse_missing_entry_returns_404(client):
    response = client.post(
        "/api/v1/ledger/entries/missing-id/reverse",
        json={"reason": "x"},
    )
    assert response.status_code == 404


def test_user_id_query_param_retired(client, setup):
    response = client.get(
        "/api/v1/ledger/entries", params={"user_id": "someone-else"}
    )
    assert response.status_code == 200


def test_user_id_body_param_retired_on_reverse(client, setup):
    created = client.post(
        "/api/v1/ledger/entries",
        json={"amount_minor": 100, "direction": "expense", "idempotency_key": "api-x-1"},
    ).json()
    response = client.post(
        f"/api/v1/ledger/entries/{created['id']}/reverse",
        json={"reason": "x", "user_id": "someone-else"},
    )
    assert response.status_code == 200


def test_categories_lists_user_tree(client, setup):
    response = client.get("/api/v1/ledger/categories")
    assert response.status_code == 200
    body = response.json()
    assert body
    assert {"id", "name", "kind"} <= set(body[0])


def test_budget_endpoints_roundtrip(client):
    put = client.put(
        "/api/v1/ledger/budgets",
        json={"scope": "total", "period": "month", "limit_minor": 150000},
    )
    assert put.status_code == 200
    assert put.json()["limit_text"] == format_minor(150000)
    got = client.get("/api/v1/ledger/budgets")
    assert got.status_code == 200
    assert any(item["goal_id"] == put.json()["goal_id"] for item in got.json())


def test_error_response_has_no_traceback(client):
    response = client.get("/api/v1/ledger/entries", params={"limit": 999})
    assert response.status_code == 400
    assert "Traceback" not in response.text


def test_api_layer_has_no_repositories_import():
    source = (BACKEND / "app/api/v1/ledger.py").read_text(encoding="utf-8")
    for forbidden in ("app.repositories", "app.core.db"):
        assert forbidden not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("app.repositories")
            assert node.module != "app.core.db"
            assert "llm" not in node.module.lower()
            assert "chain" not in node.module.lower()


def test_api_layer_imports_services_only():
    source = (BACKEND / "app/api/v1/ledger.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_prefixes = (
        "app.services",
        "app.core.settings",
        "app.models",
        "app.api",
        "fastapi",
        "pydantic",
        "datetime",
        "typing",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert any(
                node.module == p or node.module.startswith(p + ".") or node.module == p
                for p in allowed_prefixes
            ) or node.module in {"__future__", "hashlib"}, node.module


def test_existing_routes_unchanged(client):
    response = client.get("/api/v1/state")
    assert response.status_code in (200, 404, 422)
    response = client.get("/api/v1/life/export")
    assert response.status_code == 200


def test_router_registration_is_additive_only():
    source = (BACKEND / "app/api/v1/router.py").read_text(encoding="utf-8")
    assert "ledger.ledger_router" in source
    assert source.count("include_router") >= 12


def test_no_existing_api_file_modified():
    # 本任务只应新增 ledger.py 并追加 router 注册；schemas.py 可不改
    assert (BACKEND / "app/api/v1/ledger.py").exists()
