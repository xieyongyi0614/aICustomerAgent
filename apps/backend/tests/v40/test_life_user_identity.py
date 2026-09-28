from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.core.db import UserRow
from app.core.settings import Settings
from app.services.identity.user_service import UserContext, get_user
from tests.v40.support import V30_ENABLED_FLAGS

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"


def test_get_user_returns_none_when_absent(db_session_factory):
    with db_session_factory() as session:
        before = session.query(UserRow).count()
    assert get_user("missing-user") is None
    with db_session_factory() as session:
        assert session.query(UserRow).count() == before


def test_user_context_is_frozen():
    ctx = UserContext(user_id="u", display_name=None, status="active")
    with pytest.raises(FrozenInstanceError):
        ctx.user_id = "other"


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
