"""全系统统一时间口径（UTC-aware）。

内部一律使用「带时区的 UTC」：取时走 `now()`，跨边界输入走 `ensure_aware()`，
跨边界输出走 `to_iso()`。数据库列由 `core.db.base.UtcDateTime` 承载，
读写两端保证 aware UTC（SQLite 无时区能力，由该类型补齐）。

`ensure_aware` 把 naive 视为部署本地时区（GMT+8）——即历史 `datetime.now()`
写入的墙钟口径；迁移完成、全库转 aware 后，naive 输入只应来自边界。
"""

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def now() -> datetime:
    return datetime.now(UTC)


def local_now() -> datetime:
    """本地墙钟（aware +08）。用于「本地日期」语义与未迁移域的对齐。"""
    return datetime.now(LOCAL_TZ)


def local_naive(value: datetime | None) -> datetime | None:
    """把任意 aware/naive 值换算为本地墙钟的朴素形式；未迁移域（naive 本地）边界用。"""
    aware = ensure_aware(value)
    return None if aware is None else aware.astimezone(LOCAL_TZ).replace(tzinfo=None)


def local(value: datetime | None) -> datetime | None:
    """把任意 aware/naive 值换算为本地墙钟（aware +08）；本地日期/小时语义用。"""
    aware = ensure_aware(value)
    return None if aware is None else aware.astimezone(LOCAL_TZ)


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(UTC)


def to_iso(value: datetime | None) -> str | None:
    aware = ensure_aware(value)
    return None if aware is None else aware.isoformat()
