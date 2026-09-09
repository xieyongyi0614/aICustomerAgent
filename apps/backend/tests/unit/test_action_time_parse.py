"""V9-002 时间短语解析单测（planner.md §1.2）。"""

from datetime import datetime

from app.services.action.time_parse import parse_time_phrase

NOW = datetime(2026, 9, 3, 14, 0, 0)


def test_tomorrow_default_10am():
    assert parse_time_phrase("明天有安排", NOW) == datetime(2026, 9, 4, 10, 0)


def test_tomorrow_morning_8():
    assert parse_time_phrase("明天早上8点", NOW) == datetime(2026, 9, 4, 8, 0)


def test_tomorrow_afternoon_3():
    assert parse_time_phrase("明天下午3点", NOW) == datetime(2026, 9, 4, 15, 0)


def test_day_after_tomorrow_evening():
    assert parse_time_phrase("后天晚上", NOW) == datetime(2026, 9, 5, 19, 0)


def test_tonight_8pm():
    assert parse_time_phrase("今晚提醒", NOW) == datetime(2026, 9, 3, 20, 0)


def test_half_hour_later():
    assert parse_time_phrase("半小时后", NOW) == datetime(2026, 9, 3, 14, 30)


def test_hours_before_absolute():
    assert parse_time_phrase("22小时之前", NOW) == datetime(2026, 9, 2, 16, 0)


def test_hours_before_cn_number():
    assert parse_time_phrase("三小时前", NOW) == datetime(2026, 9, 3, 11, 0)


def test_half_hour_before():
    assert parse_time_phrase("半小时前", NOW) == datetime(2026, 9, 3, 13, 30)


def test_days_before():
    assert parse_time_phrase("2天前", NOW) == datetime(2026, 9, 1, 14, 0)


def test_floor_number_is_not_time():
    assert parse_time_phrase("我在22层煮面", NOW) is None


def test_minutes_later_cn():
    assert parse_time_phrase("十分钟后", NOW) == datetime(2026, 9, 3, 14, 10)


def test_weekday_next_friday():
    # 2026-09-03 是周四
    assert parse_time_phrase("周五下午", NOW) == datetime(2026, 9, 4, 14, 0)


def test_evening_only_today():
    assert parse_time_phrase("晚上买牛奶", NOW) == datetime(2026, 9, 3, 19, 0)


def test_bare_clock_today():
    assert parse_time_phrase("20点", NOW) == datetime(2026, 9, 3, 20, 0)


def test_chinese_clock():
    assert parse_time_phrase("晚上八点半", NOW) == datetime(2026, 9, 3, 20, 30)


def test_no_time_phrase():
    assert parse_time_phrase("帮我买牛奶", NOW) is None
