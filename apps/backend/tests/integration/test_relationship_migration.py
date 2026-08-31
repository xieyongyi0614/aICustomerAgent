"""V8.5-001 迁移一致性：扩列 server_default 旧行兼容 + upgrade/downgrade 往返。

需要 PostgreSQL（TEST_DATABASE_URL），不可用时跳过（同 test_db_migration 模式）。
"""

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.db import Base

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
def postgres_url():
    url = _ensure_test_database()
    if url is None:
        pytest.skip("PostgreSQL 不可用：docker compose up -d 后重跑")
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    yield url


def _run_alembic(url: str, target: str) -> None:
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, target)


def _legacy_relationship_state_row(engine):
    """模拟 V5 旧行：只写 V5 既有列。"""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO relationship_state"
                " (user_id, intimacy, trust, familiarity, tension, stage,"
                "  created_at, updated_at)"
                " VALUES ('legacy-user', 0.3, 0.35, 0.3, 0.0, 'friend',"
                "          NOW(), NOW())"
            )
        )


def test_upgrade_adds_columns_with_defaults(postgres_url):
    engine = create_engine(postgres_url)
    _run_alembic(postgres_url, "0018")
    inspector = inspect(engine)
    state_columns = {
        column["name"]: column for column in inspector.get_columns("relationship_state")
    }
    for name in (
        "respect",
        "comfort",
        "conflict_status",
        "neglect_active",
        "last_interaction_at",
        "version",
    ):
        assert name in state_columns
    event_columns = {
        column["name"] for column in inspector.get_columns("relationship_events")
    }
    assert {"impact_respect", "impact_comfort"} <= event_columns
    engine.dispose()


def test_legacy_row_defaults_after_upgrade(postgres_url):
    _run_alembic(postgres_url, "0017")
    engine = create_engine(postgres_url)
    _legacy_relationship_state_row(engine)
    _run_alembic(postgres_url, "0018")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT respect, comfort, conflict_status, neglect_active, version"
                " FROM relationship_state WHERE user_id = 'legacy-user'"
            )
        ).one()
    assert row.respect == 0.6
    assert row.comfort == 0.6
    assert row.conflict_status == "none"
    assert row.neglect_active is False
    assert row.version == 0
    engine.dispose()


def test_event_new_enum_values_and_legacy_impact_defaults(postgres_url):
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO relationship_events"
                " (id, user_id, character_id, session_id, type, magnitude,"
                "  impact_intimacy, impact_trust, impact_familiarity, impact_tension,"
                "  confidence, source, cause, created_at)"
                " VALUES ('legacy-event', 'legacy-user', 'asuna', 's1', 'user_care',"
                "         'normal', 0.03, 0.04, 0.01, -0.02, 0.9, 'conversation',"
                "         '', NOW())"
            )
        )
    with engine.begin() as connection, pytest.raises(sa.exc.IntegrityError):
        connection.execute(
            text(
                "INSERT INTO relationship_events"
                " (id, user_id, character_id, session_id, type, magnitude,"
                "  impact_intimacy, impact_trust, impact_familiarity, impact_tension,"
                "  confidence, source, cause, created_at)"
                " VALUES ('bad-type', 'legacy-user', 'asuna', 's1', 'bogus',"
                "         'normal', 0, 0, 0, 0, 0.5, 'conversation', '', NOW())"
            )
        )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT impact_respect, impact_comfort FROM relationship_events"
                " WHERE id = 'legacy-event'"
            )
        ).one()
    assert row.impact_respect == 0.0
    assert row.impact_comfort == 0.0
    engine.dispose()


def test_downgrade_roundtrip(postgres_url):
    _run_alembic(postgres_url, "0017")
    engine = create_engine(postgres_url)
    inspector = inspect(engine)
    state_columns = {column["name"] for column in inspector.get_columns("relationship_state")}
    assert "respect" not in state_columns
    assert "version" not in state_columns
    _run_alembic(postgres_url, "head")
    inspector = inspect(engine)
    state_columns = {column["name"] for column in inspector.get_columns("relationship_state")}
    assert "respect" in state_columns
    engine.dispose()


def test_orm_metadata_matches_migrations(postgres_url):
    engine = create_engine(postgres_url)
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if table.name not in ("relationship_state", "relationship_events"):
            continue
        expected = {column.name for column in table.columns}
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        assert expected == actual, table.name
    engine.dispose()
