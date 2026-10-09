"""应用版本与制品读面编排（API-022）：最新版本选取、制品定位与路径安全校验。

服务端只做「事实下发」：`has_update` / `force_update` / `min_supported_version_code`
原样给出，是否强制更新由客户端按契约判定。制品路径一律**相对** `app_release_storage_dir`
解析，解析结果必须仍在该目录之下。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import timeutil
from app.core.db import AppReleaseArtifactRow, AppReleaseRow
from app.core.settings import get_settings
from app.repositories import app_release_repository

logger = logging.getLogger(__name__)

FULL_ARTIFACT_TYPE = "full"
ARTIFACT_DOWNLOAD_PATH = "/api/v1/app-release/artifacts/{artifact_id}/download"


class ArtifactNotFound(Exception):
    """制品行不存在，或落盘文件缺失。"""


class ArtifactPathRejected(Exception):
    """制品路径越出存储根目录（目录穿越）。"""


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    row: AppReleaseArtifactRow
    path: Path


def storage_root() -> Path:
    return Path(get_settings().app_release_storage_dir)


def resolve_storage_path(storage_path: str, *, root: Path | None = None) -> Path:
    """把相对制品路径解析为绝对路径，越界即拒绝。

    `storage_path` 只接受以 `/` 分隔的相对路径：绝对路径、`..` 段、反斜杠分隔一律拒绝
    （Windows 会把 `a\\..\\b` 当单段，只查 parts 会被绕过）。
    """
    raw = (storage_path or "").strip()
    if not raw:
        raise ArtifactPathRejected("制品路径为空")
    if "\\" in raw:
        raise ArtifactPathRejected("制品路径不得含反斜杠分隔符")
    base = (root or storage_root()).resolve()
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ArtifactPathRejected("制品路径必须是相对路径")
    if ".." in candidate.parts:
        raise ArtifactPathRejected("制品路径不得含上级目录段")
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise ArtifactPathRejected("制品路径越出存储根目录")
    return resolved


def artifact_payload(row: AppReleaseArtifactRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.artifact_type,
        "url": ARTIFACT_DOWNLOAD_PATH.format(artifact_id=row.id),
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "signature_fingerprint": row.signature_fingerprint,
        "from_version_code": row.from_version_code,
    }


def release_payload(row: AppReleaseRow) -> dict[str, Any]:
    return {
        "version_name": row.version_name,
        "version_code": row.version_code,
        "min_supported_version_code": row.min_supported_version_code,
        "force_update": bool(row.force_update),
        "release_notes": row.release_notes,
        "published_at": timeutil.to_iso(row.published_at),
    }


def latest_payload(
    platform: str, channel: str, version_code: int
) -> dict[str, Any]:
    latest = app_release_repository.latest_release(platform, channel)
    if latest is None or latest.version_code <= version_code:
        return {"has_update": False, "latest": None, "artifacts": []}
    artifacts = app_release_repository.list_artifacts(latest.id)
    return {
        "has_update": True,
        "latest": release_payload(latest),
        "artifacts": [artifact_payload(row) for row in artifacts],
    }


def open_artifact(artifact_id: str) -> ResolvedArtifact:
    row = app_release_repository.get_artifact(artifact_id)
    if row is None:
        raise ArtifactNotFound(artifact_id)
    path = resolve_storage_path(row.storage_path)
    if not path.is_file():
        logger.error(
            "制品文件缺失 release_artifact_id=%s storage_path=%s", row.id, row.storage_path
        )
        raise ArtifactNotFound(artifact_id)
    return ResolvedArtifact(row=row, path=path)
