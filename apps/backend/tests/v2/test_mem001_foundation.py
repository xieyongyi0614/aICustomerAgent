import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.db import Base

pytestmark = pytest.mark.xdist_group("migration")

PG_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://asuna:asuna@127.0.0.1:5432/asuna_test"
)

NEW_TABLES = {"memory_candidates", "memory_links", "background_jobs"}
NEW_COLUMNS = {
    "embedding",
    "salience",
    "last_reinforced_at",
    "merge_chain",
    "source_ref",
    "visibility",
}


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
        connection.execute(text("DROP INDEX IF EXISTS idx_memories_embedding_hnsw"))
    engine.dispose()

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, "head")
    yield url


def _inspector(url):
    return inspect(create_engine(url))


def test_upgrade_adds_columns_and_tables(postgres_url):
    inspector = _inspector(postgres_url)
    memory_columns = {c["name"] for c in inspector.get_columns("memories")}
    assert NEW_COLUMNS <= memory_columns
    assert NEW_TABLES <= set(inspector.get_table_names())

    candidate_columns = {c["name"] for c in inspector.get_columns("memory_candidates")}
    assert {
        "id", "user_id", "character_id", "content", "proposed_type", "source",
        "source_ref", "source_table", "source_id", "salience", "status",
        "reason", "visibility", "created_at",
    } <= candidate_columns

    job_columns = {c["name"] for c in inspector.get_columns("background_jobs")}
    assert {
        "id", "job_type", "payload", "status", "attempts", "run_at",
        "idempotency_key", "last_error", "created_at",
    } <= job_columns


def test_hnsw_index_on_memories_embedding(postgres_url):
    engine = create_engine(postgres_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname ="
                " 'idx_memories_embedding_hnsw'"
            )
        ).fetchall()
    assert rows, "memories.embedding 缺少 HNSW 索引"
    assert "hnsw" in rows[0][0]
    assert "vector_cosine_ops" in rows[0][0]


def test_unique_constraints(postgres_url):
    inspector = _inspector(postgres_url)
    candidate_uniques = {
        u["name"] for u in inspector.get_unique_constraints("memory_candidates")
    }
    assert "uq_memory_candidates_source" in candidate_uniques
    job_uniques = {
        tuple(u["column_names"]) for u in inspector.get_unique_constraints("background_jobs")
    }
    assert ("idempotency_key",) in job_uniques


def test_check_constraints_state_machines(postgres_url):
    inspector = _inspector(postgres_url)
    candidate_checks = {
        c["name"] for c in inspector.get_check_constraints("memory_candidates")
    }
    link_checks = {c["name"] for c in inspector.get_check_constraints("memory_links")}
    job_checks = {c["name"] for c in inspector.get_check_constraints("background_jobs")}
    assert "ck_memory_candidates_status" in candidate_checks
    assert "ck_memory_links_relation" in link_checks
    assert "ck_background_jobs_status" in job_checks


def test_upgrade_downgrade_upgrade_round_trip(postgres_url):
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)

    command.downgrade(alembic_cfg, "0021")
    engine = create_engine(postgres_url)
    inspector = inspect(engine)
    assert not (NEW_TABLES & set(inspector.get_table_names()))
    memory_columns = {c["name"] for c in inspector.get_columns("memories")}
    assert not (NEW_COLUMNS & memory_columns)

    command.upgrade(alembic_cfg, "head")
    inspector = inspect(engine)
    assert NEW_TABLES <= set(inspector.get_table_names())
    memory_columns = {c["name"] for c in inspector.get_columns("memories")}
    assert NEW_COLUMNS <= memory_columns
    engine.dispose()


def test_v1_data_preserved_across_round_trip(postgres_url):
    engine = create_engine(postgres_url)
    now = "2026-01-01 00:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO memories (id, user_id, content, type, importance,"
                " character_id, confidence, source, status, created_at, updated_at)"
                " VALUES ('mem-rt', 'u-rt', '往返数据', 'user_fact', 0.5, '*',"
                " 0.9, 'ai_inferred', 'active', :now, :now)"
            ),
            {"now": now},
        )

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.downgrade(alembic_cfg, "0021")
    command.upgrade(alembic_cfg, "head")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, user_id, content, type, importance, confidence, source,"
                " status FROM memories WHERE id = 'mem-rt'"
            )
        ).fetchone()
    assert row == (
        "mem-rt", "u-rt", "往返数据", "user_fact", 0.5, 0.9, "ai_inferred", "active",
    )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM memories WHERE id = 'mem-rt'"))
    engine.dispose()


def test_upgrade_is_idempotent_when_already_at_head(postgres_url):
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(alembic_cfg, "head")
    command.upgrade(alembic_cfg, "head")
    assert NEW_TABLES <= set(_inspector(postgres_url).get_table_names())


def test_sqlite_round_trip(tmp_path):
    url = f"sqlite:///{(tmp_path / 'v2_foundation.db').as_posix()}"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(url)
    inspector = inspect(engine)
    assert NEW_TABLES <= set(inspector.get_table_names())
    memory_columns = {c["name"] for c in inspector.get_columns("memories")}
    assert NEW_COLUMNS <= memory_columns
    engine.dispose()

    command.downgrade(alembic_cfg, "0021")
    engine = create_engine(url)
    inspector = inspect(engine)
    assert not (NEW_TABLES & set(inspector.get_table_names()))
    memory_columns = {c["name"] for c in inspector.get_columns("memories")}
    assert not (NEW_COLUMNS & memory_columns)
    engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(url)
    inspector = inspect(engine)
    assert NEW_TABLES <= set(inspector.get_table_names())
    engine.dispose()


def test_sqlite_candidate_unique_and_job_state(tmp_path):
    url = f"sqlite:///{(tmp_path / 'v2_constraints.db').as_posix()}"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(url)

    import datetime

    now = datetime.datetime.now()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO memory_candidates (id, user_id, content, proposed_type,"
                " source, source_table, source_id, status, created_at)"
                " VALUES ('c1', 'u1', '内容', 'user_fact', 'action_records',"
                " 'action_records', 'a1', 'pending', :now)"
            ),
            {"now": now},
        )
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO memory_candidates (id, user_id, content,"
                    " proposed_type, source, source_table, source_id, status,"
                    " created_at)"
                    " VALUES ('c2', 'u1', '重复', 'user_fact', 'action_records',"
                    " 'action_records', 'a1', 'pending', :now)"
                ),
                {"now": now},
            )
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO background_jobs (id, job_type, payload, status,"
                    " attempts, idempotency_key, created_at)"
                    " VALUES ('j1', 'x', '{}', 'bogus', 0, 'k1', :now)"
                ),
                {"now": now},
            )
    engine.dispose()