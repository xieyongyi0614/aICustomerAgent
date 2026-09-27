from __future__ import annotations

import ast
import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.db import Base, UserRow
from tests.support.schema_pins import (
    MIGRATION_HEAD,
    SCHEMA_PREVIOUS_HEAD,
    SCHEMA_TABLE_COUNT,
    schema_columns_digest,
    schema_pin,
)

BACKEND = Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "migrations" / "versions"
MIGRATION_PATH = VERSIONS / "0053_life_user_identity.py"


def test_orm_has_users_columns():
    columns = UserRow.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "email",
        "display_name",
        "status",
        "is_default",
        "created_at",
        "updated_at",
    }
    assert columns["id"].primary_key is True


def test_default_index_declared():
    indexes = {index.name: index for index in UserRow.__table__.indexes}
    assert "ux_users_is_default" in indexes
    assert indexes["ux_users_is_default"].unique is True


def test_migration_chain_head_matches_pin():
    config = Config(str(BACKEND / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [MIGRATION_HEAD]
    revision = script.get_revision(MIGRATION_HEAD)
    assert revision is not None
    assert revision.down_revision == SCHEMA_PREVIOUS_HEAD


def test_migration_has_upgrade_and_downgrade():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    assert "op.create_table" in source and '"users"' in source
    assert "op.drop_table" in source
    assert "ux_users_is_default" in source
    assert "sqlite_where" in source and "postgresql_where" in source


def test_schema_table_count_is_pinned():
    assert SCHEMA_TABLE_COUNT == len(Base.metadata.tables)


def test_pins_module_is_single_source():
    offenders = []
    for path in (BACKEND / "tests").rglob("*.py"):
        if path.name == "schema_pins.py":
            continue
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^MIGRATION_HEAD\s*=\s*[\"']", source, re.M):
            offenders.append(f"{path}:{match.start()}")
    assert offenders == []


def test_pin_values_match_reality():
    pin = schema_pin()
    assert pin.migration_head == MIGRATION_HEAD
    assert pin.schema_table_count == len(Base.metadata.tables)
    config = Config(str(BACKEND / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [pin.migration_head]
    assert schema_columns_digest() == pin.schema_columns_digest
