"""WS-002：世界模拟 Schema 正放（PostgreSQL；不可用则跳过）。

2026-09-29 迁移链折叠为单迁移 0001，原 0044/0045 逆放用例随折叠退役；
本文件仅保留 head 态的对象存在性断言。
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.xdist_group("migration")

PG_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://asuna:asuna@127.0.0.1:5432/asuna_test"
)


def _ensure_test_database() -> str | None:
    server_url = PG_TEST_URL.rsplit("/", 1)[0] + "/postgres"
    database_name = PG_TEST_URL.rsplit("/", 1)[1]
    try:
        server = create_engine(server_url, connect_args={"connect_timeout": 2})
        with server.connect() as connection:
            connection.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f'CREATE DATABASE "{database_name}"')
            )
        server.dispose()
        return PG_TEST_URL
    except Exception as exc:
        if "already exists" in str(exc):
            return PG_TEST_URL
        return None


@pytest.fixture(scope="module")
def alembic_cfg():
    url = _ensure_test_database()
    if url is None:
        pytest.skip("PostgreSQL 不可用：docker compose up -d 后重跑")
    engine = create_engine(url, pool_pre_ping=True)
    from app.core.db import Base

    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    yield cfg
    engine = create_engine(url, pool_pre_ping=True)
    Base_drop(engine)
    engine.dispose()


def Base_drop(engine):
    from app.core.db import Base

    Base.metadata.drop_all(engine)


def _columns(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


def _tables(engine) -> set[str]:
    return set(inspect(create_engine(PG_TEST_URL)).get_table_names())


def test_upgrade_creates_simulation_tables_and_extensions(alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(PG_TEST_URL, pool_pre_ping=True)
    try:
        assert {"daily_plans", "user_situations"} <= _tables(engine)
        assert "sim_last_advanced_at" in _columns(engine, "worlds")
        assert "idempotency_key" in _columns(engine, "world_events")
        indexes = {
            idx["name"] for idx in inspect(engine).get_indexes("world_events")
        }
        assert "uq_world_events_idempotency" in indexes
    finally:
        engine.dispose()
