from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import UserRow
from app.core.settings import Settings, get_settings
from app.repositories import user_repository
from app.services.identity.user_service import (
    UserContext,
    ensure_default_user,
    get_user,
    resolve_user,
)
from tests.v40.support import V30_ENABLED_FLAGS

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"


def test_ensure_default_user_is_idempotent(db_session_factory):
    for _ in range(3):
        ensure_default_user()
    with db_session_factory() as session:
        count = session.query(UserRow).filter(UserRow.is_default.is_(True)).count()
    assert count == 1


def test_ensure_default_user_does_not_overwrite(db_session_factory):
    first = ensure_default_user()
    with db_session_factory() as session:
        row = session.get(UserRow, first.user_id)
        row.display_name = "别覆盖我"
        session.commit()
    again = ensure_default_user()
    assert again.display_name == "别覆盖我"


def test_resolve_user_falls_back_to_default():
    for value in (None, ""):
        ctx = resolve_user(value)
        assert ctx.user_id == get_settings().default_user
        assert ctx.is_default is True


def test_resolve_user_returns_requested_id(db_session_factory):
    with db_session_factory() as session:
        before = session.query(UserRow).count()
    ctx = resolve_user("u1")
    assert ctx.user_id == "u1"
    assert ctx.display_name is None
    with db_session_factory() as session:
        assert session.query(UserRow).count() == before


def test_get_user_returns_none_when_absent(db_session_factory):
    with db_session_factory() as session:
        before = session.query(UserRow).count()
    assert get_user("missing-user") is None
    with db_session_factory() as session:
        assert session.query(UserRow).count() == before


def test_user_context_is_frozen():
    ctx = UserContext(
        user_id="u", display_name=None, status="active", is_default=False
    )
    with pytest.raises(FrozenInstanceError):
        ctx.user_id = "other"


def test_default_user_unique_index_blocks_second_default(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(
        user_repository, "SessionLocal", db_session_factory, raising=True
    )
    ensure_default_user()
    now = datetime.now()
    other = UserRow(
        id="second-default",
        display_name=None,
        status="active",
        is_default=True,
        created_at=now,
        updated_at=now,
    )
    with db_session_factory() as session:
        session.add(other)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_user_service_has_no_forbidden_imports():
    source = (APP / "services" / "identity" / "user_service.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in (
        "app.chains",
        "app.prompts",
        "app.api",
        "app.channels.feishu",
        "app.channels",
    ):
        assert not any(
            name == banned or name.startswith(banned + ".") for name in imported
        )


def test_life_settings_has_no_enabled_flag_field():
    from app.core.settings.life import LifeSettings

    assert not any(name.endswith("_enabled") for name in LifeSettings.model_fields)


def test_no_new_enabled_flag_across_settings():
    current = {name for name in Settings.model_fields if name.endswith("_enabled")}
    assert current == set(V30_ENABLED_FLAGS)
