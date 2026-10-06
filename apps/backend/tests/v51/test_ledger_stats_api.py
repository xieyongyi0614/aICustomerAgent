"""API-016 记账智能读面用例：统计 / 已学规则 / 备注分类预览。"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import timeutil
from app.api.v1 import auth as auth_api
from app.core.settings import get_settings
from app.main import create_app
from app.models.ledger import LedgerEntryDraft, LedgerExtraction
from app.repositories import ledger_repository
from app.services.ledger import pending as pending_service
from app.services.ledger.confirmation import (
    REASON_AMOUNT_OVER_THRESHOLD,
    ConfirmationRequest,
)
from app.services.ledger.service import ensure_user_bootstrap, record_entry
from tests.conftest import TEST_USER_ID

BACKEND = Path(__file__).resolve().parents[2]
USER = TEST_USER_ID
SESSION = "session-stats-1"


@pytest.fixture()
def client():
    test_app = create_app()
    test_app.dependency_overrides[auth_api.require_user] = lambda: TEST_USER_ID
    return TestClient(test_app)


def _account_id(user_id: str = USER) -> str:
    ensure_user_bootstrap(user_id)
    return ledger_repository.list_accounts(user_id)[0].id


def _record(user_id: str, account_id: str, key: str, *, source: str, amount: int = 1000):
    draft = LedgerEntryDraft(
        user_id=user_id,
        account_id=account_id,
        amount_minor=amount,
        direction="expense",
        occurred_at=timeutil.now(),
        source=source,
        idempotency_key=key,
    )
    return record_entry(draft, idempotency_key=key)


def _seed_pending(user_id: str = USER, *, pending_key: str = "pk-stats") -> None:
    now = timeutil.now()
    pending_service.register_pending(
        user_id=user_id,
        session_id=SESSION,
        request=ConfirmationRequest(
            reason=REASON_AMOUNT_OVER_THRESHOLD,
            question="这笔金额较大，要记吗？",
            candidates=(),
            pending_key=pending_key,
            expires_at=now.replace(year=now.year + 1),
            amount_minor=320000,
            source_ref="turn-stats",
        ),
        extraction=LedgerExtraction(
            amount_value="3200",
            direction="expense",
            category_hint="数码",
            merchant_hint="苹果店",
            confidence=0.6,
        ),
    )


def _aliases_snapshot(user_id: str = USER) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (row.name, tuple(row.aliases or []))
        for row in ledger_repository.list_categories(user_id)
    ]


def test_auto_summary_counts_only_ai_sources(db_session_factory, client):
    account_id = _account_id()
    _record(USER, account_id, "s-1", source="conversation")
    _record(USER, account_id, "s-2", source="conversation")
    _record(USER, account_id, "s-3", source="action")
    _record(USER, account_id, "s-4", source="manual")
    body = client.get("/api/v1/ledger/auto-summary").json()
    assert body["auto_count"] == 3
    assert body["by_category"]
    assert sum(item["count"] for item in body["by_category"]) == 3


def test_auto_summary_period_is_current_month(db_session_factory, client):
    _account_id()
    expected = client.get("/api/v1/ledger/summary").json()["period"]
    body = client.get("/api/v1/ledger/auto-summary").json()
    assert body["period"] == expected


def test_auto_summary_accuracy_is_absent_when_unavailable(db_session_factory, client):
    _account_id()
    body = client.get("/api/v1/ledger/auto-summary").json()
    assert "accuracy" not in body


def test_auto_summary_pending_count_matches_pending_endpoint(db_session_factory, client):
    _account_id()
    _seed_pending()
    auto = client.get("/api/v1/ledger/auto-summary").json()
    pending = client.get("/api/v1/ledger/pending").json()
    assert auto["pending_count"] == pending["total"] == 1


def test_auto_summary_week_period(db_session_factory, client):
    _account_id()
    body = client.get("/api/v1/ledger/auto-summary", params={"period": "week"}).json()
    assert body["period"]["label"]
    assert client.get(
        "/api/v1/ledger/auto-summary", params={"period": "year"}
    ).status_code == 422


def test_rules_excludes_seed_aliases(db_session_factory, client):
    ensure_user_bootstrap(USER)
    body = client.get("/api/v1/ledger/rules").json()
    assert body["items"] == []
    assert body["total"] == 0


def test_rules_includes_user_learned_alias_after_confirm(db_session_factory, client):
    _account_id()
    _seed_pending()
    confirmed = client.post(
        "/api/v1/ledger/pending/pk-stats/confirm", json={"category_name": "餐饮"}
    )
    assert confirmed.json()["learned_alias"] == "数码"
    body = client.get("/api/v1/ledger/rules").json()
    assert body["total"] == 1
    assert body["items"][0]["keyword"] == "数码"
    assert body["items"][0]["category_name"] == "餐饮"


def test_rules_learned_from_is_absent_without_source(db_session_factory, client):
    _account_id()
    _seed_pending()
    client.post("/api/v1/ledger/pending/pk-stats/confirm", json={"category_name": "餐饮"})
    item = client.get("/api/v1/ledger/rules").json()["items"][0]
    assert "learned_from" not in item


def test_classify_preview_is_read_only(db_session_factory, client):
    _account_id()
    aliases_before = _aliases_snapshot()
    entries_before = len(ledger_repository.list_entries(USER))
    response = client.get("/api/v1/ledger/classify-preview", params={"note": "奶茶"})
    assert response.status_code == 200
    assert _aliases_snapshot() == aliases_before
    assert len(ledger_repository.list_entries(USER)) == entries_before


def test_classify_preview_matches_alias(db_session_factory, client):
    _account_id()
    body = client.get("/api/v1/ledger/classify-preview", params={"note": "奶茶"}).json()
    assert body["matched"] is True
    assert body["category_name"] == "饮品"
    assert body["reason"] == "alias"
    assert body["is_fallback"] is False
    assert body["category_id"]


def test_classify_preview_blank_note_returns_unmatched(db_session_factory, client):
    _account_id()
    response = client.get("/api/v1/ledger/classify-preview", params={"note": "   "})
    assert response.status_code == 200
    assert response.json()["matched"] is False


def test_classify_preview_reports_fallback(db_session_factory, client):
    _account_id()
    body = client.get(
        "/api/v1/ledger/classify-preview", params={"note": "外星人飞船燃料"}
    ).json()
    assert body["matched"] is False
    assert body["is_fallback"] is True
    assert body["category_name"] == get_settings().ledger_category_fallback
    assert body["reason"] == "fallback"


def test_ledger_stats_api_has_zero_repositories_import():
    source = (BACKEND / "app" / "api" / "v1" / "ledger.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if name.startswith("app.repositories")]
