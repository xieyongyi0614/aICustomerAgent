"""API-004 首页聚合：占位字段真实化后的契约测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.api.v1 import home as home_api
from app.services.conversation import history as history_service
from app.services.insights import query as insights_query

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
    now = datetime.now()
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
