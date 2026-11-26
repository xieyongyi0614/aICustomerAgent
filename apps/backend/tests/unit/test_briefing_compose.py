"""简报合成：真实数据卡装配、无数据源卡省略、天气降级与定位优先级链（零网络）。

契约字段（APP-018 §4.4）：{type, greeting, title, orb_note, cards, cta, generated_at}。
"""

from types import SimpleNamespace

import pytest

from app.repositories import briefing_preference_repository
from app.services.briefing import weather
from app.services.briefing import compose
from app.services.car import service as car_service
from app.services.ledger import query as ledger_query
from app.services.life import tasks as task_service


def _snapshot():
    return weather.WeatherSnapshot(
        temperature_c=18.3,
        condition="少云",
        temp_min_c=12.4,
        temp_max_c=22.1,
        precipitation_probability=30,
    )


def _prefs_row(**overrides):
    fields = dict(
        morning_at=None,
        evening_at=None,
        city=None,
        latitude=None,
        longitude=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.fixture(autouse=True)
def _no_saved_prefs(monkeypatch):
    monkeypatch.setattr(briefing_preference_repository, "get", lambda user_id: None)


def _week_summary(entry_count=0, expense_minor=0, ratio=None):
    return SimpleNamespace(
        entry_count=entry_count,
        expense_minor=expense_minor,
        compared_to_previous=None
        if ratio is None
        else SimpleNamespace(expense_ratio=ratio),
    )


@pytest.fixture(autouse=True)
def _no_spend_and_car(monkeypatch):
    """合成单测不碰账本/车辆域：默认无消费、无临期提醒，两卡省略。"""
    monkeypatch.setattr(
        ledger_query, "summary", lambda *args, **kwargs: _week_summary()
    )
    monkeypatch.setattr(car_service, "reminders", lambda user_id, **kwargs: ())


@pytest.fixture
def patch_weather(monkeypatch):
    def _apply(snapshot=None):
        calls: list[tuple[float, float]] = []

        async def _fake(latitude, longitude):
            calls.append((latitude, longitude))
            return snapshot

        monkeypatch.setattr(weather, "get_current_weather", _fake)
        return calls

    return _apply


@pytest.fixture
def patch_prefs(monkeypatch):
    def _apply(**row_fields):
        row = _prefs_row(**row_fields)
        monkeypatch.setattr(
            briefing_preference_repository, "get", lambda user_id: row
        )

    return _apply


@pytest.fixture
def patch_tasks(monkeypatch):
    def _apply(count=0, error=None):
        def _fake_list_open(user_id):
            if error is not None:
                raise error
            return list(range(count))

        monkeypatch.setattr(task_service, "list_open", _fake_list_open)

    return _apply


async def test_morning_contract_fields(patch_weather, patch_tasks):
    patch_weather(_snapshot())
    patch_tasks(count=2)

    draft = await compose.compose_brief(
        "morning", "u-1", latitude=39.9042, longitude=116.4074
    )

    assert draft.type == "morning"
    assert draft.greeting.endswith("早间简报")
    assert draft.title == "早上好，今天交给我吧"
    assert draft.orb_note == "今天少云，18°"
    assert draft.cta == "开始今天"
    assert draft.generated_at
    assert draft.cards[0].title == "天气"
    assert draft.cards[0].body == "18° 少云"
    assert draft.cards[0].note == "今日 12°~22° · 降水 30%"
    assert draft.cards[1].title == "任务"
    assert "2 项" in draft.cards[1].body


async def test_greeting_uses_saved_time_then_env_default(patch_prefs, override_settings):
    patch_prefs(morning_at="07:30")

    draft = await compose.compose_brief("morning", "u-1")
    assert draft.greeting == "07:30 · 早间简报"

    patch_prefs(morning_at=None)
    override_settings(briefing_morning_time="08:00")
    draft = await compose.compose_brief("morning", "u-1")
    assert draft.greeting == "08:00 · 早间简报"

    patch_prefs(morning_at=None)
    override_settings(briefing_morning_time="")
    draft = await compose.compose_brief("morning", "u-1")
    assert draft.greeting == "早间简报"


async def test_morning_omits_cards_without_data_sources(patch_weather, patch_tasks):
    patch_weather(None)
    patch_tasks(count=0)

    draft = await compose.compose_brief(
        "morning", "u-1", latitude=39.9042, longitude=116.4074
    )

    titles = [card.title for card in draft.cards]
    assert titles == ["天气", "任务"]
    assert draft.cards[0].body == "暂无实时数据"
    assert draft.cards[0].note == "天气源未配置或暂不可用"
    assert "生活节奏" not in titles
    assert "日程" not in titles


async def test_evening_keeps_only_task_backed_card(patch_weather, patch_tasks):
    patch_weather(None)
    patch_tasks(count=1)

    draft = await compose.compose_brief("evening", "u-1")

    assert draft.type == "evening"
    assert draft.cta == "安顿明天"
    titles = [card.title for card in draft.cards]
    assert titles == ["未完成"]
    assert "1 项" in draft.cards[0].body
    assert "记住的你" not in titles
    assert "生活节奏" not in titles


async def test_task_service_failure_falls_back_to_zero(patch_weather, patch_tasks):
    patch_weather(None)
    patch_tasks(error=RuntimeError("db down"))

    draft = await compose.compose_brief(
        "morning", "u-1", latitude=39.9042, longitude=116.4074
    )

    task_card = next(card for card in draft.cards if card.title == "任务")
    assert "0 项" in task_card.body


async def test_saved_prefs_win_over_request_coordinates(patch_weather, patch_prefs):
    calls = patch_weather(_snapshot())
    patch_prefs(latitude=31.2304, longitude=121.4737)

    await compose.compose_brief(
        "morning", "u-1", latitude=39.9042, longitude=116.4074
    )

    assert calls == [(31.2304, 121.4737)]


async def test_request_coordinates_win_without_saved_prefs(patch_weather):
    calls = patch_weather(_snapshot())

    await compose.compose_brief(
        "morning", "u-1", latitude=39.9042, longitude=116.4074
    )

    assert calls == [(39.9042, 116.4074)]


async def test_default_location_is_beijing_without_any_source(patch_weather):
    calls = patch_weather(_snapshot())

    await compose.compose_brief("morning", "u-1")

    assert calls == [(39.9042, 116.4073)]


async def test_weather_fetch_failure_degrades_card(patch_weather):
    calls = patch_weather(None)

    draft = await compose.compose_brief("morning", "u-1")

    assert calls == [(39.9042, 116.4073)]
    assert draft.cards[0].title == "天气"
    assert draft.cards[0].body == "暂无实时数据"


async def test_morning_carries_car_then_spend_cards(
    patch_weather, patch_tasks, monkeypatch
):
    patch_weather(_snapshot())
    patch_tasks(count=2)
    monkeypatch.setattr(
        ledger_query,
        "summary",
        lambda *args, **kwargs: _week_summary(
            entry_count=6, expense_minor=9600, ratio=-0.12
        ),
    )
    monkeypatch.setattr(
        car_service,
        "reminders",
        lambda user_id, **kwargs: (
            SimpleNamespace(
                kind="service",
                title="下次保养",
                detail="还剩 800 km 或 5 天",
                level="soon",
            ),
            SimpleNamespace(
                kind="insurance",
                title="车辆保险",
                detail="2026-10-20 到期，该比价续保了",
                level="normal",
            ),
        ),
    )

    draft = await compose.compose_brief(
        "morning", "u-1", latitude=39.9042, longitude=116.4074
    )

    titles = [card.title for card in draft.cards]
    assert titles == ["天气", "任务", "车辆", "消费"]
    assert draft.cards[2].body == "下次保养 还剩 800 km 或 5 天"
    assert draft.cards[3].body == "近 7 天 ¥96 · 6 笔"
    assert draft.cards[3].note == "比上周少 12%"


async def test_spend_card_omitted_without_entries(patch_weather, patch_tasks):
    patch_weather(_snapshot())
    patch_tasks(count=0)

    draft = await compose.compose_brief("morning", "u-1")

    assert [card.title for card in draft.cards] == ["天气", "任务"]


async def test_car_card_omitted_without_soon_reminders(
    patch_weather, patch_tasks, monkeypatch
):
    patch_weather(_snapshot())
    patch_tasks(count=0)
    monkeypatch.setattr(
        car_service,
        "reminders",
        lambda user_id, **kwargs: (
            SimpleNamespace(
                kind="insurance",
                title="车辆保险",
                detail="2026-12-01 到期，该比价续保了",
                level="normal",
            ),
        ),
    )

    draft = await compose.compose_brief("morning", "u-1")

    assert [card.title for card in draft.cards] == ["天气", "任务"]
