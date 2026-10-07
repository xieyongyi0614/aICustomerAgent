"""数据库引擎与会话工厂；engine 在本模块导入时创建。"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import get_settings

SESSION_TIMEZONE = "UTC"


def json_serializer(value) -> str:
    """JSON 列统一 UTF-8 直存。

    Python `json.dumps` 默认 `ensure_ascii=True`：中文会落成 `\\uXXXX`（列类型是
    PG `json`，原样存文本不做规范化），于是 `aliases` 这类给人看的 JSON 在库里
    可读性归零、`LIKE '%滴滴%'` 也查不到。语义上无损（读回仍解码成中文），
    但排障与文本检索都受影响；存量由迁移 `0008` 一次性规范化。
    """
    return json.dumps(value, ensure_ascii=False)


def create_engine_from_url(url: str | None = None):
    database_url = url or get_settings().database_url
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            json_serializer=json_serializer,
        )
    if not database_url.startswith("postgresql"):
        raise ValueError(f"不支持的数据库 URL：{database_url}")
    settings = get_settings()
    session_options = [f"-c timezone={SESSION_TIMEZONE}"]
    if settings.db_statement_timeout_ms > 0:
        session_options.append(
            f"-c statement_timeout={settings.db_statement_timeout_ms}"
        )
    return create_engine(
        database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
        connect_args={"options": " ".join(session_options)},
        json_serializer=json_serializer,
    )


engine = create_engine_from_url()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
