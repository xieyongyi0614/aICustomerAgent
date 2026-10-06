"""API-004 首页聚合：占位字段真实化后的契约测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.api.v1 import home as home_api
from app.repositories import ledger_repository
from app.services.conversation import history as history_service
from app.services.insights import query as insights_query
from app.services.ledger import query as ledger_query

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, "夜深了"),
        (4, "夜深了"),
        (5, "早上好"),
        (10, "早上好"),
        (11, "中午好"),
        (13, "中午好"),
        (14, "下午好"),
        (17, "下午好"),
        (18, "晚上好"),
        (23, "晚上好"),
    ],
)
def test_greeting_follows_local_clock(hour, expected):
    assert home_api.greeting_for(datetime(2026, 9, 29, hour, 30)) == expected


def test_mode_chip_blank_without_conversation(db_session_factory, monkeypatch):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    assert home_api.mode_chip_for("u-none") == ""


def test_mode_chip_maps_known_mode(db_session_factory, monkeypatch):
    class _Conversation:
        mode = "immersive"

    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: _Conversation()
    )
    assert home_api.mode_chip_for("u1") == "Immersive 模式"


def test_mode_chip_blank_for_unknown_mode(db_session_factory, monkeypatch):
    class _Conversation:
        mode = "wat"

    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: _Conversation()
    )
    assert home_api.mode_chip_for("u1") == ""


def test_mode_chip_blank_when_history_lookup_raises(db_session_factory, monkeypatch):
    def _boom(_uid):
        raise RuntimeError("db down")

    monkeypatch.setattr(history_service, "find_latest_conversation", _boom)
    assert home_api.mode_chip_for("u1") == ""


def test_insight_is_empty_without_produced_insights(db_session_factory):
    block = home_api.insight_block_for("u-none")
    assert block.narrative == ""
    assert block.action_label is None


def test_insight_maps_produced_row(db_session_factory):
    now = timeutil.now()
    with insights_query.SessionLocal() as session:
        session.add(
            insights_query.InsightRow(
                id="ins-home",
                user_id="u1",
                statement="你最近更偏好在家做饭。夜间下单明显减少。",
                type="preference",
                confidence=0.8,
                scope="user",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    block = home_api.insight_block_for("u1")
    assert block.title == "你最近更偏好在家做饭"
    assert block.narrative == "你最近更偏好在家做饭。夜间下单明显减少。"
    assert block.action_label == "查看完整早间简报 →"


def test_summary_carries_no_fabricated_health_or_task_claims(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    summary = home_api.home_summary(user_id="u-none")
    assert summary.health.authorized is False
    assert summary.health.cells == []
    assert summary.tasks == []
    assert summary.tasks_hint == ""
    assert summary.hero.mode_chip == ""
    assert summary.insight.narrative == ""


def test_home_api_keeps_zero_repositories_dependency():
    import inspect

    src = inspect.getsource(home_api)
    assert "app.repositories" not in src


def _seed_expense(user_id: str, amount_minor: int, *, days_ago: int) -> None:
    occurred = timeutil.now() - timedelta(days=days_ago)
    ledger_repository.create_entry(
        ledger_repository.LedgerEntryDraft(
            user_id=user_id,
            account_id="acc-bars",
            amount_minor=amount_minor,
            direction="expense",
            occurred_at=occurred,
            source="manual",
            idempotency_key=f"{user_id}-{days_ago}-{amount_minor}",
        ),
        idempotency_key=f"{user_id}-{days_ago}-{amount_minor}",
    )


def test_daily_expense_series_buckets_by_local_day():
    user_id = "u-home-bars"
    _seed_expense(user_id, 3500, days_ago=0)
    _seed_expense(user_id, 600, days_ago=1)
    _seed_expense(user_id, 8700, days_ago=6)
    _seed_expense(user_id, 9900, days_ago=7)
    series = ledger_query.daily_expense_series(user_id, days=7)
    assert len(series) == 7
    assert series[6] == 3500
    assert series[5] == 600
    assert series[0] == 8700


def test_daily_expense_series_reversal_clamps_negative_day():
    user_id = "u-home-bars-reversal"
    now = timeutil.now()
    row, _ = ledger_repository.create_entry(
        ledger_repository.LedgerEntryDraft(
            user_id=user_id,
            account_id="acc-bars",
            amount_minor=1200,
            direction="expense",
            occurred_at=now,
            source="manual",
            idempotency_key=f"{user_id}-rev",
        ),
        idempotency_key=f"{user_id}-rev",
    )
    ledger_repository.create_entry(
        ledger_repository.LedgerEntryDraft(
            user_id=user_id,
            account_id="acc-bars",
            amount_minor=1200,
            direction="income",
            occurred_at=now,
            source="manual",
            reversal_of=row.id,
            idempotency_key=f"{user_id}-rev-r",
        ),
        idempotency_key=f"{user_id}-rev-r",
    )
    series = ledger_query.daily_expense_series(user_id, days=7)
    assert series[6] == 0


def test_summary_spend_carries_week_bars_in_yuan(db_session_factory, monkeypatch):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    user_id = "u-home-bars-endpoint"
    _seed_expense(user_id, 3500, days_ago=0)
    summary = home_api.home_summary(user_id=user_id)
    assert summary.spend is not None
    assert len(summary.spend.week_bars) == 7
    assert summary.spend.week_bars[6] == pytest.approx(35.0)


def test_summary_spend_week_bars_zero_without_entries(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    summary = home_api.home_summary(user_id="u-home-bars-none")
    assert summary.spend is not None
    assert summary.spend.week_bars == [0.0] * 7


def test_summary_spend_week_bars_degrade_to_empty_on_error(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )

    def _boom(_uid, *, days=7):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(ledger_query, "daily_expense_series", _boom)
    summary = home_api.home_summary(user_id="u-home-bars-error")
    assert summary.spend is not None
    assert summary.spend.week_bars == []
