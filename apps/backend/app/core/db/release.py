"""应用版本与制品域模型：版本发布记录与制品（全量 / 补丁）元数据。

`app_releases` 一行 = 一次发布；`app_release_artifacts` 一行 = 一个可下载制品。
`artifact_type` 的取值域预置 `'patch'`（差分演进扩展位，当前无写入路径）。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, UtcDateTime


class AppReleaseRow(Base):
    __tablename__ = "app_releases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    version_name: Mapped[str] = mapped_column(String, nullable=False)
    version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    min_supported_version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    force_update: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "platform IN ('android', 'ios')",
            name="ck_app_releases_platform",
        ),
        CheckConstraint(
            "channel IN ('dev', 'prod')",
            name="ck_app_releases_channel",
        ),
        CheckConstraint("version_code > 0", name="ck_app_releases_version_code"),
        CheckConstraint(
            "min_supported_version_code >= 0",
            name="ck_app_releases_min_supported",
        ),
        UniqueConstraint(
            "platform",
            "channel",
            "version_code",
            name="uq_app_releases_identity",
        ),
    )


class AppReleaseArtifactRow(Base):
    __tablename__ = "app_release_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    release_id: Mapped[str] = mapped_column(
        String, ForeignKey("app_releases.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)
    from_version_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('full', 'patch')",
            name="ck_app_release_artifacts_type",
        ),
        CheckConstraint("size_bytes > 0", name="ck_app_release_artifacts_size"),
        CheckConstraint(
            "from_version_code IS NULL OR from_version_code > 0",
            name="ck_app_release_artifacts_from_version",
        ),
        Index("ix_app_release_artifacts_release", "release_id"),
    )
