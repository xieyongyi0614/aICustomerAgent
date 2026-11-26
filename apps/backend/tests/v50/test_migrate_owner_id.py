"""owner 行 id 规范化脚本测试（默认用户概念退役收尾，IDENT-009）。

用内存 SQLite 造最小数据面：`users` 由 ORM 建表，级联面用合成表，
覆盖 `user_id` / `worlds.id` / `world_id` 三条改写路径。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import timeutil
from app.core.db import UserRow
def world_id_for(user_id: str) -> str:
    """存量世界行主键格式；本脚本只改写 legacy 行（ADR-16 C2 后新世界为雪花）。"""
    return f"home:{user_id}"
from app.services.identity.user_service import legacy_email_user_id
from scripts.migrate_owner_id_to_email import migrate_owner_id

pytestmark = pytest.mark.unit

SOURCE = "default-user"
EMAIL = "owner@example.com"

_CASCADE_DDL = (
    "CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL)",
    "CREATE TABLE memories (id TEXT PRIMARY KEY, user_id TEXT NOT NULL)",
    "CREATE TABLE worlds (id TEXT PRIMARY KEY, user_id TEXT NOT NULL)",
    "CREATE TABLE world_entities (id TEXT PRIMARY KEY, world_id TEXT NOT NULL)",
    "CREATE TABLE world_events (id TEXT PRIMARY KEY, world_id TEXT NOT NULL)",
)


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    UserRow.__table__.create(engine)
    now = timeutil.now()
    with engine.begin() as conn:
        for ddl in _CASCADE_DDL:
            conn.execute(text(ddl))
        conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, status, created_at, "
                "updated_at) VALUES (:id, :email, NULL, 'active', :now, :now)"
            ),
            {"id": SOURCE, "email": EMAIL, "now": now},
        )
        conn.execute(
            text("INSERT INTO conversations (id, user_id) VALUES ('s1', :u)"),
            {"u": SOURCE},
        )
        conn.execute(
            text("INSERT INTO memories (id, user_id) VALUES ('m1', :u)"),
            {"u": SOURCE},
        )
        conn.execute(
            text("INSERT INTO worlds (id, user_id) VALUES (:w, :u)"),
            {"w": world_id_for(SOURCE), "u": SOURCE},
        )
        conn.execute(
            text("INSERT INTO world_entities (id, world_id) VALUES ('e1', :w)"),
            {"w": world_id_for(SOURCE)},
        )
        conn.execute(
            text("INSERT INTO world_events (id, world_id) VALUES ('ev1', :w)"),
            {"w": world_id_for(SOURCE)},
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, factory
    engine.dispose()


def _scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_dry_run_reports_without_writing(env):
    engine, factory = env
    report = migrate_owner_id(SOURCE, engine=engine, session_factory=factory)

    assert report["mode"] == "dry_run"
    assert report["status"] == "planned"
    assert report["to_id"] == legacy_email_user_id(EMAIL)
    assert report["user_id_tables"]["conversations"] == 1
    assert report["user_id_tables"]["worlds"] == 1
    assert report["worlds"] == 1
    assert report["world_id_tables"]["world_entities"] == 1
    assert report["old_world_id"] == world_id_for(SOURCE)

    assert _scalar(engine, "SELECT COUNT(*) FROM users WHERE id = :v", v=SOURCE) == 1


def test_apply_rewrites_user_id_and_world_cascade(env):
    engine, factory = env
    report = migrate_owner_id(
        SOURCE, apply=True, engine=engine, session_factory=factory
    )

    target = legacy_email_user_id(EMAIL)
    assert report["status"] == "applied"
    assert _scalar(engine, "SELECT COUNT(*) FROM users WHERE id = :v", v=target) == 1
    assert _scalar(engine, "SELECT COUNT(*) FROM users WHERE id = :v", v=SOURCE) == 0
    for table in ("conversations", "memories", "worlds"):
        assert (
            _scalar(
                engine,
                f"SELECT COUNT(*) FROM {table} WHERE user_id = :v",
                v=target,
            )
            == 1
        )
    assert _scalar(engine, "SELECT COUNT(*) FROM worlds WHERE id = :v", v=world_id_for(target)) == 1
    for table in ("world_entities", "world_events"):
        assert (
            _scalar(
                engine,
                f"SELECT COUNT(*) FROM {table} WHERE world_id = :v",
                v=world_id_for(target),
            )
            == 1
        )


def test_rerun_reports_source_absent(env):
    engine, factory = env
    migrate_owner_id(SOURCE, apply=True, engine=engine, session_factory=factory)
    again = migrate_owner_id(SOURCE, apply=True, engine=engine, session_factory=factory)

    assert again["status"] == "noop_source_absent"
    assert _scalar(
        engine, "SELECT COUNT(*) FROM users WHERE id = :v", v=legacy_email_user_id(EMAIL)
    ) == 1


def test_missing_source_reports_noop(env):
    engine, factory = env
    report = migrate_owner_id("ghost-user", engine=engine, session_factory=factory)

    assert report["status"] == "noop_source_absent"
    assert report["from_id"] == "ghost-user"


def test_user_without_email_is_refused(env):
    engine, factory = env
    with factory() as session:
        row = session.get(UserRow, SOURCE)
        row.email = None
        session.commit()

    with pytest.raises(RuntimeError, match="无绑定邮箱"):
        migrate_owner_id(SOURCE, engine=engine, session_factory=factory)


def test_existing_target_row_is_refused(env):
    engine, factory = env
    target = legacy_email_user_id(EMAIL)
    now = timeutil.now()
    with factory() as session:
        session.add(
            UserRow(
                id=target,
                email="other@example.com",
                display_name=None,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    report = migrate_owner_id(SOURCE, apply=True, engine=engine, session_factory=factory)
    assert report["status"] == "refused_target_exists"
    assert _scalar(engine, "SELECT COUNT(*) FROM users WHERE id = :v", v=SOURCE) == 1
