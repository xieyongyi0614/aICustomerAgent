"""IDENT-005 owner 身份归并工具测试（v5.0.0 §14）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, UserRow
from app.core.settings import get_settings
from scripts.adopt_owner_identity import (
    adopt_owner_identity,
    bind_owner_email,
    merge_user_data,
)

pytestmark = pytest.mark.unit

SOURCE = "email-stray0000000001"
EMAIL = "owner@example.com"


def _make_engine(with_singleton_conflict: bool = False):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    target = get_settings().default_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE cutover_items (user_id TEXT, name TEXT, "
                "id INTEGER PRIMARY KEY AUTOINCREMENT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE cutover_singleton (user_id TEXT NOT NULL UNIQUE, label TEXT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO cutover_items (user_id, name) VALUES (:src, '旧记忆'), (:tgt, '新记忆')"
            ),
            {"src": SOURCE, "tgt": target},
        )
        if with_singleton_conflict:
            conn.execute(
                text(
                    "INSERT INTO cutover_singleton (user_id, label) VALUES (:src, '旧'), (:tgt, '新')"
                ),
                {"src": SOURCE, "tgt": target},
            )
        else:
            conn.execute(
                text("INSERT INTO cutover_singleton (user_id, label) VALUES (:src, '旧')"),
                {"src": SOURCE},
            )
    return engine


def _make_session_factory(engine):
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    now = datetime.now()
    with factory() as session:
        session.add_all(
            [
                UserRow(
                    id=SOURCE,
                    email=EMAIL,
                    display_name="stray",
                    status="active",
                    is_default=False,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        session.commit()
    return factory


def test_merge_user_data_moves_rows_and_skips_conflicts():
    engine = _make_engine(with_singleton_conflict=True)
    target = get_settings().default_user
    report = merge_user_data(
        SOURCE, target, ["cutover_items", "cutover_singleton"], engine
    )
    assert report["cutover_items"] == {"rows": 1, "merged": 1, "skipped": False}
    assert report["cutover_singleton"]["skipped"] is True

    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM cutover_items WHERE user_id = :u"),
                {"u": target},
            ).scalar_one()
            == 2
        )
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM cutover_singleton WHERE user_id = :u"),
                {"u": SOURCE},
            ).scalar_one()
            == 1
        )


def test_bind_owner_email_moves_email_from_stray():
    engine = _make_engine()
    factory = _make_session_factory(engine)
    target = get_settings().default_user
    with factory() as session:
        session.add(
            UserRow(
                id=target,
                display_name=None,
                status="active",
                is_default=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        session.commit()

    result = bind_owner_email(EMAIL, session_factory=factory)
    assert result["bound"] is True
    assert result["stray_id"] == SOURCE

    with factory() as session:
        target_row = session.get(UserRow, target)
        stray_row = session.get(UserRow, SOURCE)
        assert target_row.email == EMAIL
        assert target_row.display_name == "owner"
        assert stray_row.email is None

    again = bind_owner_email(EMAIL, session_factory=factory)
    assert again == {"bound": True, "already": True}


def test_adopt_owner_identity_dry_run_and_apply():
    engine = _make_engine()
    factory = _make_session_factory(engine)
    target = get_settings().default_user
    with factory() as session:
        session.add(
            UserRow(
                id=target,
                display_name=None,
                status="active",
                is_default=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        session.commit()

    dry = adopt_owner_identity(
        EMAIL, apply=False, engine=engine, session_factory=factory,
        tables=["cutover_items", "cutover_singleton"],
    )
    assert dry["mode"] == "dry_run"
    assert dry["stray_user_id"] == SOURCE
    assert dry["source_rows"]["cutover_items"] == 1

    applied = adopt_owner_identity(
        EMAIL, apply=True, engine=engine, session_factory=factory,
        tables=["cutover_items", "cutover_singleton"],
    )
    assert applied["bind"]["bound"] is True
    assert applied["stray_deleted"] is True
    with factory() as session:
        assert session.get(UserRow, SOURCE) is None
        assert session.get(UserRow, target).email == EMAIL

    rerun = adopt_owner_identity(
        EMAIL, apply=True, engine=engine, session_factory=factory,
        tables=["cutover_items", "cutover_singleton"],
    )
    assert rerun["stray_user_id"] is None
    assert rerun["bind"] == {"bound": True, "already": True}


def test_adopt_owner_identity_keeps_stray_when_conflict_unresolved():
    engine = _make_engine(with_singleton_conflict=True)
    factory = _make_session_factory(engine)
    target = get_settings().default_user
    with factory() as session:
        session.add(
            UserRow(
                id=target,
                display_name=None,
                status="active",
                is_default=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        session.commit()
    report = adopt_owner_identity(
        EMAIL, apply=True, engine=engine, session_factory=factory,
        tables=["cutover_items", "cutover_singleton"],
    )
    assert report["skipped_tables"] == ["cutover_singleton"]
    assert report["stray_deleted"] is False
    assert "待人工处理" in report["warning"]
