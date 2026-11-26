"""`app/core/timeutil.py` 唯一时间口径工具的归一行为（naive/aware 三态）。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core import timeutil

pytestmark = pytest.mark.unit

UTC = timezone.utc
LOCAL = timezone(timedelta(hours=8), "Asia/Shanghai")


def test_now_is_aware_utc():
    value = timeutil.now()
    assert value.utcoffset() == timedelta(0)


def test_local_now_is_wall_clock_plus_eight():
    assert timeutil.local_now().utcoffset() == timedelta(hours=8)


def test_ensure_aware_treats_naive_as_deploy_local_wall_clock():
    aware = timeutil.ensure_aware(datetime(2026, 10, 6, 12, 0, 0))
    assert aware == datetime(2026, 10, 6, 4, 0, 0, tzinfo=UTC)


def test_ensure_aware_keeps_instant_and_normalizes_to_utc():
    aware = timeutil.ensure_aware(datetime(2026, 10, 6, 12, 0, 0, tzinfo=LOCAL))
    assert aware == datetime(2026, 10, 6, 4, 0, 0, tzinfo=UTC)


def test_ensure_aware_passes_none_through():
    assert timeutil.ensure_aware(None) is None


def test_local_moves_instant_to_local_wall_clock():
    assert timeutil.local(datetime(2026, 10, 6, 4, 0, 0, tzinfo=UTC)) == datetime(
        2026, 10, 6, 12, 0, 0, tzinfo=LOCAL
    )


def test_local_naive_strips_offset_after_local_conversion():
    value = timeutil.local_naive(datetime(2026, 10, 6, 4, 0, 0, tzinfo=UTC))
    assert value == datetime(2026, 10, 6, 12, 0, 0)
    assert value.tzinfo is None


def test_to_iso_emits_utc_offset_and_handles_none():
    assert timeutil.to_iso(datetime(2026, 10, 6, 12, 0, 0)) == "2026-10-06T04:00:00+00:00"
    assert timeutil.to_iso(None) is None
