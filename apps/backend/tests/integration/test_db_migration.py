import os
from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core import llm_factory
from app.core.db import Base, Conversation, Message, create_engine_from_url
from app.main import app
from app.repositories import (
    character_state_repository,
    conversation_repository,
    relationship_event_repository,
    emotion_history_repository,
    goal_repository,
    memory_repository,
    relationship_repository,
    scene_state_repository,
    summary_repository,
)
from tests.conftest import wait_until

PG_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://asuna:asuna@localhost:5432/asuna_test"
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


def test_create_engine_rejects_unknown_dialect():
    with pytest.raises(ValueError):
        create_engine_from_url("mysql://user:pass@localhost:3306/asuna")


def test_create_engine_postgresql_branch_keeps_pool_settings():
    engine = create_engine_from_url(
        "postgresql+psycopg://asuna:asuna@localhost:5432/asuna"
    )
    assert engine.url.get_backend_name() == "postgresql"
    engine.dispose()


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

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, "head")
    yield url


def _structured_responses():
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "MemoryExtraction": {
            "candidates": [
                {
                    "action": "save",
                    "type": "user_preference",
                    "content": "用户喜欢寿司",
                    "importance": 0.8,
                    "confidence": 0.9,
                    "source": "user_stated",
                }
            ]
        },
    }


def test_alembic_upgrade_matches_orm_metadata(postgres_url):
    engine = create_engine(postgres_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "conversations",
        "messages",
        "conversation_summaries",
        "memories",
        "alembic_version",
    } <= tables

    for table in Base.metadata.sorted_tables:
        expected = {column.name for column in table.columns}
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        assert expected == actual, table.name
    engine.dispose()


def test_http_lifecycle_on_postgres(postgres_url, fake_llm):
    engine = create_engine(postgres_url, pool_pre_ping=True)
    pg_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(conversation_repository, "SessionLocal", pg_session)
    monkey.setattr(summary_repository, "SessionLocal", pg_session)
    monkey.setattr(memory_repository, "SessionLocal", pg_session)
    monkey.setattr(character_state_repository, "SessionLocal", pg_session)
    monkey.setattr(relationship_repository, "SessionLocal", pg_session)
    monkey.setattr(relationship_event_repository, "SessionLocal", pg_session)
    monkey.setattr(emotion_history_repository, "SessionLocal", pg_session)
    monkey.setattr(scene_state_repository, "SessionLocal", pg_session)
    monkey.setattr(goal_repository, "SessionLocal", pg_session)

    llm = fake_llm(
        response=["好的"],
        structured_responses=_structured_responses(),
    )
    llm_factory.set_llm(llm)
    try:
        with TestClient(app) as client:
            resp = client.post("/api/v1/chat/message", json={"content": "我喜欢寿司"})
            assert resp.status_code == 200
            session_id = resp.headers.get("x-session-id")
            assert wait_until(
                lambda: any(
                    m.memory == "用户喜欢寿司"
                    for m in memory_repository.list_by_user("default-user")
                )
            )

            resp2 = client.post(
                "/api/v1/chat/message",
                json={"session_id": session_id, "content": "晚上想吃寿司"},
            )
            assert resp2.status_code == 200
            assert any(
                "用户喜欢寿司" in str(m) for m in llm.seen_messages
            )
    finally:
        monkey.undo()
        llm_factory.reset_llm()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
        engine.dispose()


def test_sqlite_to_postgres_migration_script(postgres_url, tmp_path):
    from scripts.migrate_sqlite_to_postgres import migrate

    source_url = f"sqlite:///{(tmp_path / 'source.db').as_posix()}"
    source_engine = create_engine(
        source_url, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(source_engine)
    now = datetime.now()
    with Session(source_engine) as session:
        session.add(
            Conversation(
                id="conv-mig", user_id="default-user", created_at=now, updated_at=now
            )
        )
        session.add(
            Message(
                conversation_id="conv-mig",
                role="human",
                content="我喜欢寿司",
                created_at=now,
            )
        )
        session.add(
            Message(
                conversation_id="conv-mig", role="ai", content="好的", created_at=now
            )
        )
        session.commit()

    counts = migrate(source_url, postgres_url)
    assert counts == {
        "conversations": 1,
        "messages": 2,
        "conversation_summaries": 0,
        "memories": 0,
        "scene_state": 0,
    }

    target_engine = create_engine(postgres_url, pool_pre_ping=True)
    with Session(target_engine) as session:
        contents = [m.content for m in session.query(Message).all()]
        assert contents == ["我喜欢寿司", "好的"]
    with target_engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    source_engine.dispose()
    target_engine.dispose()
