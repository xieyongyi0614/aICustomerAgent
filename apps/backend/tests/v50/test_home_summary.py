"""API-004 首页聚合：占位字段真实化后的契约测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core import timeutil
from app.api.v1 import home as home_api
from app.repositories import ledger_repository
from app.services.briefing import compose as brief_compose
from app.services.briefing import weather as brief_weather
from app.services.conversation import history as history_service
from app.services.insights import query as insights_query
from app.services.ledger import query as ledger_query
from app.services.life import tasks as task_service

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_weather(monkeypatch):
    """首页单测不碰真实天气源（开发者 .env 可能配了兜底坐标）。"""

    async def _none(_user_id, latitude=None, longitude=None):
        return None

    monkeypatch.setattr(brief_compose, "current_weather_for_user", _none)


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


def test_insight_empty_without_insights_or_fallback_data(db_session_factory):
    """无洞察且天气、任务都取不到时不出兜底句，空态交回客户端。"""
    block = asyncio.run(home_api.insight_block_for("u-none"))
    assert block.title == "今日 AI 总结"
    assert block.narrative == ""
    assert block.action_label is None


def test_insight_falls_back_to_weather_and_tasks(db_session_factory, monkeypatch):
    async def _snapshot(_user_id, latitude=None, longitude=None):
        return brief_weather.WeatherSnapshot(
            temperature_c=18.3,
            condition="少云",
            temp_min_c=12.4,
            temp_max_c=22.1,
            precipitation_probability=30,
        )

    monkeypatch.setattr(brief_compose, "current_weather_for_user", _snapshot)
    block = asyncio.run(
        home_api.insight_block_for("u-fallback", open_task_count=3)
    )
    assert block.title == "今日 AI 总结"
    assert block.narrative == "今天少云，12°~22°；有 3 项任务等你。"
    assert block.action_label == "查看完整早间简报 →"


def test_insight_fallback_omits_weather_without_snapshot(db_session_factory):
    block = asyncio.run(home_api.insight_block_for("u-fb", open_task_count=2))
    assert block.narrative == "有 2 项任务等你。"
    assert block.action_label == "查看完整早间简报 →"


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

    block = asyncio.run(home_api.insight_block_for("u1"))
    assert block.title == "你最近更偏好在家做饭"
    assert block.narrative == "你最近更偏好在家做饭。夜间下单明显减少。"
    assert block.action_label == "查看完整早间简报 →"


def test_summary_forwards_coordinates_to_weather(db_session_factory, monkeypatch):
    monkeypatch.setattr(history_service, "find_latest_conversation", lambda _uid: None)
    captured: dict[str, tuple[float, float] | None] = {}

    async def _capture(_user_id, latitude=None, longitude=None):
        captured["coords"] = (
            None if latitude is None or longitude is None else (latitude, longitude)
        )
        return None

    monkeypatch.setattr(brief_compose, "current_weather_for_user", _capture)
    asyncio.run(home_api.home_summary(user_id="u-coords", lat=39.9, lon=116.4))
    assert captured["coords"] == (39.9, 116.4)


def test_summary_rejects_unpaired_coordinates():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(home_api.home_summary(user_id="u-coords", lat=39.9))
    assert exc_info.value.status_code == 422


def test_summary_carries_no_fabricated_task_or_insight_claims(
    db_session_factory, monkeypatch
):
    """空数据下首页只给诚实空值。

    （原用例还断言 `summary.health.*`，但健康区块已随「移除健康模块」下线，
    字段不存在；断言随之删除，其余空值契约保留。）
    """
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    summary = asyncio.run(home_api.home_summary(user_id="u-none"))
    assert summary.tasks == []
    assert summary.tasks_hint == ""
    assert summary.hero.mode_chip == ""
    assert summary.insight.narrative == ""


def test_summary_fallback_narrative_counts_open_tasks(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(history_service, "find_latest_conversation", lambda _uid: None)
    rows = [{"id": f"t{i}", "title": f"任务{i}"} for i in range(3)]
    monkeypatch.setattr(task_service, "list_open", lambda _uid: rows)
    summary = asyncio.run(home_api.home_summary(user_id="u-fb-count"))
    assert "有 3 项任务等你" in summary.insight.narrative
    assert summary.tasks_hint == "3 项 · AI 已排序"


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
    summary = asyncio.run(home_api.home_summary(user_id=user_id))
    assert summary.spend is not None
    assert len(summary.spend.week_bars) == 7
    assert summary.spend.week_bars[6] == pytest.approx(35.0)


def test_summary_spend_week_bars_zero_without_entries(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    summary = asyncio.run(home_api.home_summary(user_id="u-home-bars-none"))
    assert summary.spend is not None
    assert summary.spend.week_bars == [0.0] * 7


def test_summary_spend_week_labels_end_with_today(
    db_session_factory, monkeypatch
):
    """横轴标签由服务端按产品时区下发，末位固定「今天」（端上倒推会错一天）。"""
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    summary = asyncio.run(home_api.home_summary(user_id="u-home-bars-none"))
    assert summary.spend is not None
    labels = summary.spend.week_labels
    assert len(labels) == 7
    assert labels[-1] == "今天"
    assert all(label in ("一", "二", "三", "四", "五", "六", "日") for label in labels[:6])


def test_summary_spend_week_labels_follow_local_days(monkeypatch):
    """标签逐位对齐 `week_bars`：首日 = 今天往前推 6 天。"""
    fixed = timeutil.ensure_aware(datetime(2026, 10, 7, 12, 0, 0))
    monkeypatch.setattr(timeutil, "local_now", lambda: fixed)
    labels = home_api._spend_labels()
    assert labels == ["四", "五", "六", "日", "一", "二", "今天"]


def test_summary_spend_week_bars_degrade_to_empty_on_error(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )

    def _boom(_uid, *, days=7):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(ledger_query, "daily_expense_series", _boom)
    summary = asyncio.run(home_api.home_summary(user_id="u-home-bars-error"))
    assert summary.spend is not None
    assert summary.spend.week_bars == []


def test_summary_spend_is_weekly_with_real_amount(db_session_factory, monkeypatch):
    """回归：金额此前读的是不存在的 `summary.expense`（恒为 ¥0），窗口按日、
    预算硬编码 ¥200——卡面长期「¥0 / 今天还没有记账」，等于没用。
    """
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    user_id = "u-home-spend-week"
    _seed_expense(user_id, 24000, days_ago=0)
    _seed_expense(user_id, 800, days_ago=3)
    _seed_expense(user_id, 99900, days_ago=9)  # 窗外：不得计入

    spend = asyncio.run(home_api.home_summary(user_id=user_id)).spend

    assert spend is not None
    assert spend.amount_label == "¥248"
    assert spend.note_label == "近 7 天 · 2 笔"
    assert spend.progress is None, "没有真实预算数据源时不再撑进度条"
    assert spend.conclusion.startswith("近 7 天日均 ¥")
    assert spend.conclusion.endswith("—— 亚丝娜")


def test_spend_conclusion_reports_week_over_week(db_session_factory, monkeypatch):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )
    user_id = "u-home-spend-ratio"
    _seed_expense(user_id, 10000, days_ago=0)
    _seed_expense(user_id, 20000, days_ago=8)  # 前 7 天

    spend = asyncio.run(home_api.home_summary(user_id=user_id)).spend

    assert spend is not None
    assert spend.conclusion == "近 7 天日均 ¥14，比上周少 50% —— 亚丝娜"


def test_summary_spend_empty_window_copy(db_session_factory, monkeypatch):
    monkeypatch.setattr(
        history_service, "find_latest_conversation", lambda _uid: None
    )

    spend = asyncio.run(home_api.home_summary(user_id="u-home-spend-none")).spend

    assert spend is not None
    assert spend.amount_label == "¥0"
    assert spend.note_label == "近 7 天"
    assert spend.progress is None
    assert spend.conclusion == "最近还没有记账 —— 亚丝娜"
