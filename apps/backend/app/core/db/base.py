"""ORM 基类与跨领域共享的自定义列类型。"""

from sqlalchemy import types as sa_types
from sqlalchemy.orm import DeclarativeBase


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
