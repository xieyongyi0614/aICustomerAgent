"""API-022 `0009` 迁移与 Schema 契约测试（两表 / CHECK 布尔式 / 链头 / 正逆放）。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from app.core.db import AppReleaseArtifactRow, AppReleaseRow, Base
from tests.support.schema_pins import (
    MIGRATION_HEAD,
    MIGRATION_HEAD_PARENT,
    SCHEMA_COLUMNS_DIGEST,
    SCHEMA_TABLE_COUNT,
    schema_columns_digest,
)

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION_FILE = BACKEND / "migrations" / "versions" / "0009_app_release_artifacts.py"

RELEASE_TABLES = ("app_releases", "app_release_artifacts")
EXPECTED_RELEASE_CHECKS = (
    "ck_app_releases_platform",
    "ck_app_releases_channel",
    "ck_app_releases_version_code",
    "ck_app_releases_min_supported",
)
EXPECTED_ARTIFACT_CHECKS = (
    "ck_app_release_artifacts_type",
    "ck_app_release_artifacts_size",
    "ck_app_release_artifacts_from_version",
)
_COMPARISON = re.compile(r"(IN \(|\>=|\<=|>|<)")


def _migration_source() -> str:
    return MIGRATION_FILE.read_text(encoding="utf-8")


def _checks(table) -> dict[str, str]:
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_release_tables_are_registered_in_metadata():
    assert set(RELEASE_TABLES) <= set(Base.metadata.tables)


def test_schema_table_count_matches_pin():
    assert len(Base.metadata.tables) == SCHEMA_TABLE_COUNT == 57


def test_schema_columns_digest_matches_pin():
    assert schema_columns_digest() == SCHEMA_COLUMNS_DIGEST


def test_migration_chain_head_matches_pin():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == [MIGRATION_HEAD]
    # 钉值升级声明（2026-10-16 / 2026-10-27）：合并迁移 `0010` 入链后 0009（本任务迁移）不再是链尾，
    # 断言改为**不绑定链尾**：「本任务迁移自身在链上且父版本不变」——后续迁移不再动本用例。
    app_release_revision = script.get_revision("0009")
    assert app_release_revision is not None
    assert app_release_revision.down_revision == "0008"
    head_revision = script.get_revision(MIGRATION_HEAD)
    assert head_revision is not None
    assert head_revision.down_revision == MIGRATION_HEAD_PARENT


def test_migration_exists_with_expected_filename():
    assert MIGRATION_FILE.is_file()


def test_migration_has_downgrade_with_drop_table_per_table():
    source = _migration_source()
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    for name in RELEASE_TABLES:
        assert f'"{name}"' in source
        assert f'op.drop_table("{name}")' in source


def test_migration_has_no_bare_timezone_true():
    assert "timezone=True" not in _migration_source()


def test_migration_creates_two_tables_and_one_index():
    source = _migration_source()
    assert source.count("op.create_table(") == 2
    assert source.count("op.create_index(") == 1
    assert '"ix_app_release_artifacts_release"' in source


def test_check_constraints_are_complete_boolean_expressions():
    source = _migration_source()
    for name in (*EXPECTED_RELEASE_CHECKS, *EXPECTED_ARTIFACT_CHECKS):
        assert name in source
    for expression in (
        "platform IN ('android', 'ios')",
        "channel IN ('dev', 'prod')",
        "version_code > 0",
        "min_supported_version_code >= 0",
        "artifact_type IN ('full', 'patch')",
        "size_bytes > 0",
        "from_version_code IS NULL OR from_version_code > 0",
    ):
        assert f'"{expression}"' in source


def test_orm_check_constraints_are_boolean_expressions():
    for table in (AppReleaseRow.__table__, AppReleaseArtifactRow.__table__):
        checks = _checks(table)
        assert checks, table.name
        for name, sqltext in checks.items():
            assert _COMPARISON.search(sqltext), f"{name} 不是完整布尔式：{sqltext}"


def test_orm_release_checks_named_as_designed():
    assert set(_checks(AppReleaseRow.__table__)) == set(EXPECTED_RELEASE_CHECKS)


def test_orm_artifact_checks_named_as_designed():
    assert set(_checks(AppReleaseArtifactRow.__table__)) == set(EXPECTED_ARTIFACT_CHECKS)


def test_artifact_type_check_predeclares_patch():
    sqltext = _checks(AppReleaseArtifactRow.__table__)[
        "ck_app_release_artifacts_type"
    ]
    assert "'full'" in sqltext and "'patch'" in sqltext


def test_release_identity_is_unique_on_platform_channel_version():
    unique = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in AppReleaseRow.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("channel", "platform", "version_code") in unique


def test_release_has_no_is_active_like_column():
    names = {column.name for column in AppReleaseRow.__table__.columns}
    assert names == {
        "id",
        "platform",
        "channel",
        "version_name",
        "version_code",
        "min_supported_version_code",
        "force_update",
        "release_notes",
        "published_at",
        "created_at",
        "updated_at",
    }


def test_artifact_columns_match_contract():
    names = {column.name for column in AppReleaseArtifactRow.__table__.columns}
    assert names == {
        "id",
        "release_id",
        "artifact_type",
        "from_version_code",
        "storage_path",
        "file_name",
        "size_bytes",
        "sha256",
        "signature_fingerprint",
        "created_at",
    }


def test_artifact_release_index_declared():
    indexes = {
        index.name: [column.name for column in index.columns]
        for index in AppReleaseArtifactRow.__table__.indexes
        if isinstance(index, Index)
    }
    assert indexes["ix_app_release_artifacts_release"] == ["release_id"]


def test_artifact_release_id_cascades():
    foreign_keys = list(AppReleaseArtifactRow.__table__.foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].target_fullname == "app_releases.id"
    assert foreign_keys[0].ondelete == "CASCADE"
