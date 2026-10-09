"""应用版本与制品分发 API：只做表现，零仓储依赖（同 car.py 先例）。

两个端点均不鉴权：版本查询在客户端冷启动路径上（未登录用户也须能收到安全更新），
本域不含任何用户数据。制品下载路径由行 id 反查，客户端不传路径。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services.app_release import service as release_service

app_release_router = APIRouter(prefix="/app-release", tags=["app-release"])

APK_MEDIA_TYPE = "application/vnd.android.package-archive"


class AppReleaseArtifactOut(BaseModel):
    id: str
    type: str
    url: str
    size_bytes: int
    sha256: str
    signature_fingerprint: str | None
    from_version_code: int | None


class AppReleaseLatestInfoOut(BaseModel):
    version_name: str
    version_code: int
    min_supported_version_code: int
    force_update: bool
    release_notes: str | None
    published_at: str | None


class AppReleaseLatestOut(BaseModel):
    has_update: bool
    latest: AppReleaseLatestInfoOut | None
    artifacts: list[AppReleaseArtifactOut]


@app_release_router.get("/latest", response_model=AppReleaseLatestOut)
def get_latest_release(
    platform: Literal["android", "ios"] = Query(...),
    channel: Literal["dev", "prod"] = Query(...),
    version_code: int = Query(..., gt=0),
) -> AppReleaseLatestOut:
    payload = release_service.latest_payload(platform, channel, version_code)
    return AppReleaseLatestOut(**payload)


@app_release_router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str) -> FileResponse:
    try:
        resolved = release_service.open_artifact(artifact_id)
    except release_service.ArtifactPathRejected as exc:
        raise HTTPException(status_code=403, detail="制品路径不可用") from exc
    except release_service.ArtifactNotFound as exc:
        raise HTTPException(status_code=404, detail="制品不存在") from exc
    return FileResponse(
        resolved.path,
        media_type=APK_MEDIA_TYPE,
        filename=resolved.row.file_name,
        headers={"X-Artifact-Sha256": resolved.row.sha256},
    )
