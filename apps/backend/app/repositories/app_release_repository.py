"""app_releases / app_release_artifacts 数据访问（API-022）：发布记录与制品元数据。

业务键：发布 = `(platform, channel, version_code)`；制品 = `(release_id, artifact_type,
from_version_code)`（`from_version_code` 为 NULL 时按 `IS NULL` 匹配）。幂等 upsert
由脚本侧调用，端点侧只读。
"""

from datetime import datetime

from sqlalchemy import select

from app.core import ids, timeutil
from app.core.db import AppReleaseArtifactRow, AppReleaseRow, SessionLocal


def find_release(
    platform: str, channel: str, version_code: int
) -> AppReleaseRow | None:
    with SessionLocal() as session:
        return session.execute(
            select(AppReleaseRow).where(
                AppReleaseRow.platform == platform,
                AppReleaseRow.channel == channel,
                AppReleaseRow.version_code == version_code,
            )
        ).scalar_one_or_none()


def latest_release(platform: str, channel: str) -> AppReleaseRow | None:
    with SessionLocal() as session:
        return session.execute(
            select(AppReleaseRow)
            .where(
                AppReleaseRow.platform == platform,
                AppReleaseRow.channel == channel,
            )
            .order_by(AppReleaseRow.version_code.desc())
            .limit(1)
        ).scalar_one_or_none()


def max_version_code(platform: str, channel: str) -> int | None:
    with SessionLocal() as session:
        return session.execute(
            select(AppReleaseRow.version_code)
            .where(
                AppReleaseRow.platform == platform,
                AppReleaseRow.channel == channel,
            )
            .order_by(AppReleaseRow.version_code.desc())
            .limit(1)
        ).scalar_one_or_none()


def upsert_release(
    platform: str,
    channel: str,
    *,
    version_name: str,
    version_code: int,
    min_supported_version_code: int,
    force_update: bool,
    release_notes: str | None,
    published_at: datetime,
) -> tuple[AppReleaseRow, bool]:
    now = timeutil.now()
    with SessionLocal() as session:
        row = session.execute(
            select(AppReleaseRow).where(
                AppReleaseRow.platform == platform,
                AppReleaseRow.channel == channel,
                AppReleaseRow.version_code == version_code,
            )
        ).scalar_one_or_none()
        created = row is None
        if row is None:
            row = AppReleaseRow(
                id=ids.new_id_str(),
                platform=platform,
                channel=channel,
                version_code=version_code,
                created_at=now,
            )
            session.add(row)
        row.version_name = version_name
        row.min_supported_version_code = min_supported_version_code
        row.force_update = force_update
        row.release_notes = release_notes
        row.published_at = published_at
        row.updated_at = now
        session.commit()
        return row, created


def list_artifacts(release_id: str) -> list[AppReleaseArtifactRow]:
    with SessionLocal() as session:
        return list(
            session.execute(
                select(AppReleaseArtifactRow)
                .where(AppReleaseArtifactRow.release_id == release_id)
                .order_by(AppReleaseArtifactRow.created_at.asc())
            ).scalars()
        )


def get_artifact(artifact_id: str) -> AppReleaseArtifactRow | None:
    with SessionLocal() as session:
        return session.get(AppReleaseArtifactRow, artifact_id)


def upsert_artifact(
    release_id: str,
    *,
    artifact_type: str,
    from_version_code: int | None,
    storage_path: str,
    file_name: str,
    size_bytes: int,
    sha256: str,
    signature_fingerprint: str | None,
) -> tuple[AppReleaseArtifactRow, bool]:
    with SessionLocal() as session:
        query = select(AppReleaseArtifactRow).where(
            AppReleaseArtifactRow.release_id == release_id,
            AppReleaseArtifactRow.artifact_type == artifact_type,
        )
        if from_version_code is None:
            query = query.where(AppReleaseArtifactRow.from_version_code.is_(None))
        else:
            query = query.where(
                AppReleaseArtifactRow.from_version_code == from_version_code
            )
        row = session.execute(query).scalar_one_or_none()
        created = row is None
        if row is None:
            row = AppReleaseArtifactRow(
                id=ids.new_id_str(),
                release_id=release_id,
                artifact_type=artifact_type,
                from_version_code=from_version_code,
                created_at=timeutil.now(),
            )
            session.add(row)
        row.storage_path = storage_path
        row.file_name = file_name
        row.size_bytes = size_bytes
        row.sha256 = sha256
        row.signature_fingerprint = signature_fingerprint
        session.commit()
        return row, created
