"""API-015 待确认账单产品级读 / 写接口用例。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import timeutil
from app.api.v1 import auth as auth_api
from app.main import create_app
from app.models.action import ActionRecord
from app.models.ledger import LedgerExtraction
from app.repositories import action_repository, ledger_repository, scene_state_repository
from app.services.ledger import pending as pending_service
from app.services.ledger.confirmation import (
    REASON_AMOUNT_OVER_THRESHOLD,
    ConfirmationRequest,
    request_to_mapping,
)
from app.services.ledger.service import ensure_user_bootstrap
from tests.conftest import TEST_USER_ID

BACKEND = Path(__file__).resolve().parents[2]
USER = TEST_USER_ID
SESSION = "session-pending-1"
KEY = "pk-1"


@pytest.fixture()
def client():
    test_app = create_app()
    test_app.dependency_overrides[auth_api.require_user] = lambda: TEST_USER_ID
    return TestClient(test_app)


def _request(
    pending_key: str = KEY,
    *,
    amount_minor: int | None = 320000,
    expires_in: timedelta = timedelta(hours=1),
    source_ref: str = "turn-1",
) -> ConfirmationRequest:
    return ConfirmationRequest(
        reason=REASON_AMOUNT_OVER_THRESHOLD,
        question="这笔金额较大，要记吗？",
        candidates=(),
        pending_key=pending_key,
        expires_at=timeutil.now() + expires_in,
        amount_minor=amount_minor,
        source_ref=source_ref,
    )


def _extraction(**overrides) -> LedgerExtraction:
    payload = {
        "amount_value": "3200",
        "direction": "expense",
        "category_hint": "数码",
        "merchant_hint": "苹果店",
        "evidence_span": "买了个平板 3200",
        "confidence": 0.6,
    }
    payload.update(overrides)
    return LedgerExtraction(**payload)


def _seed(
    user_id: str = USER,
    *,
    session_id: str = SESSION,
    pending_key: str = KEY,
    expires_in: timedelta = timedelta(hours=1),
):
    ensure_user_bootstrap(user_id)
    return pending_service.register_pending(
        user_id=user_id,
        session_id=session_id,
        request=_request(pending_key, expires_in=expires_in),
        extraction=_extraction(),
    )


def _entries(user_id: str = USER) -> list:
    return ledger_repository.list_entries(user_id)


def test_list_pending_returns_items_for_user(db_session_factory, client):
    _seed()
    _seed("other-user", session_id="session-other", pending_key="pk-other")
    response = client.get("/api/v1/ledger/pending")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["pending_key"] for item in body["items"]] == [KEY]
    item = body["items"][0]
    assert item["reason"] == REASON_AMOUNT_OVER_THRESHOLD
    assert item["question"]
    assert item["amount_minor"] == 320000
    assert item["ai_guess"]["category_hint"] == "数码"
    assert body["degraded"] == 0


def test_list_pending_excludes_expired(db_session_factory, client):
    record = _seed(expires_in=timedelta(hours=-1))
    body = client.get("/api/v1/ledger/pending").json()
    assert body["items"] == []
    assert body["total"] == 0
    assert action_repository.get_record(record.id).status == "cancelled"


def test_list_pending_skips_malformed_payload_and_counts_degraded(
    db_session_factory, client
):
    action_repository.save_record(
        ActionRecord(
            id="act_malformed",
            user_id=USER,
            session_id="session-malformed",
            source="conversation",
            action_type="record_ledger_entry",
            dedupe_key="pk-malformed",
            params={"confirmation": request_to_mapping(_request("pk-malformed"))},
            status="planned",
            gate_reason="pending_confirmation",
            created_at=timeutil.now(),
            updated_at=timeutil.now(),
        )
    )
    response = client.get("/api/v1/ledger/pending")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["degraded"] == 1


def test_confirm_creates_entry_and_clears_pending(db_session_factory, client):
    _seed()
    response = client.post(f"/api/v1/ledger/pending/{KEY}/confirm")
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["learned_alias"] is None
    entry_ids = [row.id for row in _entries()]
    assert body["entry_id"] in entry_ids
    assert client.get("/api/v1/ledger/pending").json()["items"] == []
    pointer = scene_state_repository.get_scene_state(SESSION).pending_action
    assert pointer is not None and pointer.status == "completed"


def test_confirm_is_idempotent_by_pending_key(db_session_factory, client):
    _seed()
    first = client.post(f"/api/v1/ledger/pending/{KEY}/confirm").json()
    before = len(_entries())
    second = client.post(f"/api/v1/ledger/pending/{KEY}/confirm")
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["entry_id"] == first["entry_id"]
    assert len(_entries()) == before


def test_confirm_with_changed_category_learns_alias(db_session_factory, client):
    _seed()
    response = client.post(
        f"/api/v1/ledger/pending/{KEY}/confirm", json={"category_name": "餐饮"}
    )
    assert response.status_code == 200
    assert response.json()["learned_alias"] == "数码"
    categories = {row.name: row for row in ledger_repository.list_categories(USER)}
    assert "数码" in (categories["餐饮"].aliases or [])


def test_confirm_without_change_learns_nothing(db_session_factory, client):
    _seed()
    body = client.post(f"/api/v1/ledger/pending/{KEY}/confirm").json()
    assert body["learned_alias"] is None
    categories = {row.name: row for row in ledger_repository.list_categories(USER)}
    assert "数码" not in (categories["餐饮"].aliases or [])


def test_ignore_does_not_create_entry(db_session_factory, client):
    _seed()
    before = len(_entries())
    response = client.post(f"/api/v1/ledger/pending/{KEY}/ignore")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "pending_key": KEY}
    assert len(_entries()) == before
    assert client.get("/api/v1/ledger/pending").json()["items"] == []
    pointer = scene_state_repository.get_scene_state(SESSION).pending_action
    assert pointer is not None and pointer.status == "cancelled"


def test_pending_endpoints_are_404_on_unknown_key(db_session_factory, client):
    assert client.post("/api/v1/ledger/pending/missing/confirm").status_code == 404
    assert client.post("/api/v1/ledger/pending/missing/ignore").status_code == 404


def test_pending_endpoints_are_404_on_cross_user_access(db_session_factory, client):
    _seed("other-user", session_id="session-other", pending_key="pk-other")
    assert client.post("/api/v1/ledger/pending/pk-other/confirm").status_code == 404
    assert client.post("/api/v1/ledger/pending/pk-other/ignore").status_code == 404


def test_pending_endpoints_are_404_after_ignore(db_session_factory, client):
    _seed()
    assert client.post(f"/api/v1/ledger/pending/{KEY}/ignore").status_code == 200
    assert client.post(f"/api/v1/ledger/pending/{KEY}/ignore").status_code == 404
    assert client.post(f"/api/v1/ledger/pending/{KEY}/confirm").status_code == 404


def test_confirm_rejects_non_positive_amount(db_session_factory, client):
    _seed()
    response = client.post(
        f"/api/v1/ledger/pending/{KEY}/confirm", json={"amount_minor": 0}
    )
    assert response.status_code == 422


def test_pending_list_caps_limit(db_session_factory, client):
    assert client.get("/api/v1/ledger/pending", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/ledger/pending", params={"limit": 500}).status_code == 422


def test_ledger_api_has_zero_repositories_import():
    source = (BACKEND / "app" / "api" / "v1" / "ledger.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if name.startswith("app.repositories")]
    assert not [name for name in imported if name.startswith("app.core.db")]
