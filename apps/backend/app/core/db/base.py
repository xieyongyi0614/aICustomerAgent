"""ORM 基类与跨领域共享的自定义列类型。"""

from datetime import timedelta, timezone

from sqlalchemy import types as sa_types
from sqlalchemy.orm import DeclarativeBase

_UTC = timezone.utc
_LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


class Base(DeclarativeBase):
    pass


class VectorType(sa_types.UserDefinedType):
    """pgvector 向量列类型；SQLite 下退化为 JSON 存储（仅保证迁移可跑，不启用向量检索）。"""

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "VECTOR(768)"

    def bind_processor(self, dialect):
        if dialect.name == "sqlite":
            return lambda value: value
        return None

    def result_processor(self, dialect, coltype):
        return None


class UtcDateTime(sa_types.TypeDecorator):
    """时间列统一类型：库内存 UTC，读出恒为 aware UTC。

    Postgres 侧落为 `timestamptz`；SQLite 无时区能力，裸 `DateTime(timezone=True)`
    读回会退化为 naive，本类型在结果侧补 UTC，使两种后端行为一致。
    """

    impl = sa_types.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=_LOCAL_TZ)
        return value.astimezone(_UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=_UTC)
        return value.astimezone(_UTC)
