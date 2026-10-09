"""0009：应用版本发布与制品表（免商店自动更新的数据面）。

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "app_releases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("version_name", sa.String(), nullable=False),
        sa.Column("version_code", sa.Integer(), nullable=False),
        sa.Column("min_supported_version_code", sa.Integer(), nullable=False),
        sa.Column("force_update", sa.Boolean(), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "platform IN ('android', 'ios')",
            name="ck_app_releases_platform",
        ),
        sa.CheckConstraint(
            "channel IN ('dev', 'prod')",
            name="ck_app_releases_channel",
        ),
        sa.CheckConstraint(
            "version_code > 0",
            name="ck_app_releases_version_code",
        ),
        sa.CheckConstraint(
            "min_supported_version_code >= 0",
            name="ck_app_releases_min_supported",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "channel",
            "version_code",
            name="uq_app_releases_identity",
        ),
    )
    op.create_table(
        "app_release_artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("release_id", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("from_version_code", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("signature_fingerprint", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "artifact_type IN ('full', 'patch')",
            name="ck_app_release_artifacts_type",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_app_release_artifacts_size",
        ),
        sa.CheckConstraint(
            "from_version_code IS NULL OR from_version_code > 0",
            name="ck_app_release_artifacts_from_version",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["app_releases.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_app_release_artifacts_release",
        "app_release_artifacts",
        ["release_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_app_release_artifacts_release",
        table_name="app_release_artifacts",
    )
    op.drop_table("app_release_artifacts")
    op.drop_table("app_releases")
