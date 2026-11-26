from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models.ledger import LedgerExtraction
from app.services.ledger.timeparse import resolve_occurred_at

BACKEND = Path(__file__).resolve().parents[2]
TZ_NAME = "Asia/Shanghai"
WORLD_TIME = datetime(2026, 6, 15, 18, 0, 0, tzinfo=ZoneInfo(TZ_NAME))


def test_noon_resolves_to_local_12():
    result = resolve_occurred_at("中午", world_time=WORLD_TIME, timezone=TZ_NAME)
    assert result.resolved is not None
    assert result.resolved.hour == 12
    assert result.resolved.date() == WORLD_TIME.date()


def test_yesterday_night_crosses_midnight():
    result = resolve_occurred_at("昨晚", world_time=WORLD_TIME, timezone=TZ_NAME)
    assert result.resolved is not None
    assert result.resolved.date() == (WORLD_TIME - timedelta(days=1)).date()
    assert result.resolved.hour == 21


def test_last_friday_resolves_backwards():
    result = resolve_occurred_at("上周五", world_time=WORLD_TIME, timezone=TZ_NAME)
    assert result.resolved is not None
    assert result.resolved.weekday() == 4
    assert result.resolved < WORLD_TIME


def test_unparsable_returns_none():
    result = resolve_occurred_at("前几天", world_time=WORLD_TIME, timezone=TZ_NAME)
    assert result.resolved is None
    assert result.reason == "unparsable"


def test_uses_world_time_not_system_clock(monkeypatch):
    other = datetime(2026, 1, 5, 9, 0, 0, tzinfo=ZoneInfo(TZ_NAME))
    a = resolve_occurred_at("中午", world_time=WORLD_TIME, timezone=TZ_NAME)
    b = resolve_occurred_at("中午", world_time=other, timezone=TZ_NAME)
    assert a.resolved.date() == WORLD_TIME.date()
    assert b.resolved.date() == other.date()
    assert a.resolved != b.resolved


def test_timezone_boundary_correct():
    utc = datetime(2026, 6, 15, 16, 30, 0, tzinfo=ZoneInfo("UTC"))
    shanghai = utc.astimezone(ZoneInfo("Asia/Shanghai"))
    result = resolve_occurred_at("今天中午", world_time=shanghai, timezone="Asia/Shanghai")
    assert result.resolved is not None
    assert result.resolved.hour == 12
    assert result.resolved.tzinfo is not None


def test_empty_hint_returns_none():
    result = resolve_occurred_at(None, world_time=WORLD_TIME, timezone=TZ_NAME)
    assert result.resolved is None
