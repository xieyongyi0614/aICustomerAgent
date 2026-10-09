"""API-022 版本端点与制品下载契约测试（含 Range / 目录穿越 / 入库幂等）。

用**最小 FastAPI 应用**挂载本域路由，避免整机 lifespan 与真实库耦合；DB 走
`db_session_factory` 注入的离线 SQLite。
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import app_release as app_release_api
from app.api.v1.router import api_router
from app.core import timeutil
from app.core.settings import get_settings
from app.repositories import app_release_repository
from app.services.app_release import service as release_service
from scripts import import_release

pytestmark = pytest.mark.unit

LATEST_URL = "/api/v1/app-release/latest"
APK_PAYLOAD = b"PK\x03\x04-fake-apk-payload-0123456789"
FINGERPRINT = "AB:CD:EF:01"


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_RELEASE_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _client() -> TestClient:
    mini = FastAPI()
    mini.include_router(app_release_api.app_release_router, prefix="/api/v1")
    return TestClient(mini)


def _write_artifact(
    storage_dir: Path,
    channel: str,
    version_code: int,
    name: str = "zhaoxi.apk",
    payload: bytes = APK_PAYLOAD,
    artifact_type: str = "full",
) -> tuple[str, int, str]:
    relative = f"{channel}/{version_code}/{artifact_type}/{name}"
    path = Path(storage_dir) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return relative, len(payload), hashlib.sha256(payload).hexdigest()


def _seed_release(
    storage_dir: Path,
    *,
    channel: str = "prod",
    platform: str = "android",
    version_code: int = 20,
    min_supported: int = 18,
    force_update: bool = False,
    release_notes: str | None = "修复若干问题",
    artifact_type: str = "full",
    from_version_code: int | None = None,
) -> tuple[str, str]:
    release, _ = app_release_repository.upsert_release(
        platform,
        channel,
        version_name=f"0.{version_code}.0",
        version_code=version_code,
        min_supported_version_code=min_supported,
        force_update=force_update,
        release_notes=release_notes,
        published_at=timeutil.now(),
    )
    relative, size, sha256 = _write_artifact(
        storage_dir,
        channel,
        version_code,
        artifact_type=artifact_type,
    )
    artifact, _ = app_release_repository.upsert_artifact(
        release.id,
        artifact_type=artifact_type,
        from_version_code=from_version_code,
        storage_path=relative,
        file_name="zhaoxi.apk",
        size_bytes=size,
        sha256=sha256,
        signature_fingerprint=FINGERPRINT,
    )
    return release.id, artifact.id


def test_router_is_mounted_in_api_router(db_session_factory, storage_dir):
    mini = FastAPI()
    mini.include_router(api_router, prefix="/api/v1")
    response = TestClient(mini).get(
        LATEST_URL, params={"platform": "android", "channel": "prod", "version_code": 1}
    )
    assert response.status_code == 200
    assert response.json()["has_update"] is False


def test_no_records_returns_has_update_false(db_session_factory, storage_dir):
    response = _client().get(
        LATEST_URL, params={"platform": "android", "channel": "prod", "version_code": 1}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"has_update": False, "latest": None, "artifacts": []}


def test_latest_picks_max_version_code_and_isolates_channel(
    db_session_factory, storage_dir
):
    _seed_release(storage_dir, channel="prod", version_code=10)
    _seed_release(storage_dir, channel="prod", version_code=12)
    _seed_release(storage_dir, channel="dev", version_code=99)
    response = _client().get(
        LATEST_URL,
        params={"platform": "android", "channel": "prod", "version_code": 10},
    )
    body = response.json()
    assert body["has_update"] is True
    assert body["latest"]["version_code"] == 12
    assert body["latest"]["version_name"] == "0.12.0"


def test_ios_platform_does_not_see_android_release(db_session_factory, storage_dir):
    _seed_release(storage_dir, platform="android", version_code=20)
    response = _client().get(
        LATEST_URL, params={"platform": "ios", "channel": "prod", "version_code": 1}
    )
    assert response.json()["has_update"] is False


def test_client_at_latest_gets_no_update(db_session_factory, storage_dir):
    _seed_release(storage_dir, version_code=20)
    response = _client().get(
        LATEST_URL,
        params={"platform": "android", "channel": "prod", "version_code": 20},
    )
    assert response.json()["has_update"] is False


def test_min_supported_and_force_are_passed_through(db_session_factory, storage_dir):
    _seed_release(storage_dir, version_code=20, min_supported=18, force_update=True)
    response = _client().get(
        LATEST_URL,
        params={"platform": "android", "channel": "prod", "version_code": 10},
    )
    latest = response.json()["latest"]
    assert latest["min_supported_version_code"] == 18
    assert latest["force_update"] is True
    assert latest["release_notes"] == "修复若干问题"
    assert latest["published_at"]


def test_full_artifact_payload_shape(db_session_factory, storage_dir):
    _, artifact_id = _seed_release(storage_dir, version_code=20)
    response = _client().get(
        LATEST_URL,
        params={"platform": "android", "channel": "prod", "version_code": 10},
    )
    artifacts = response.json()["artifacts"]
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["id"] == artifact_id
    assert artifact["type"] == "full"
    assert artifact["from_version_code"] is None
    assert artifact["signature_fingerprint"] == FINGERPRINT
    assert artifact["size_bytes"] == len(APK_PAYLOAD)
    assert artifact["url"] == f"/api/v1/app-release/artifacts/{artifact_id}/download"


def test_patch_artifact_is_returned_verbatim_for_client_fail_closed(
    db_session_factory, storage_dir
):
    _, artifact_id = _seed_release(
        storage_dir,
        version_code=20,
        artifact_type="patch",
        from_version_code=12,
    )
    response = _client().get(
        LATEST_URL,
        params={"platform": "android", "channel": "prod", "version_code": 10},
    )
    artifacts = response.json()["artifacts"]
    assert [item["type"] for item in artifacts] == ["patch"]
    assert artifacts[0]["from_version_code"] == 12
    assert artifacts[0]["id"] == artifact_id


@pytest.mark.parametrize(
    "params",
    [
        {"platform": "windows", "channel": "prod", "version_code": 1},
        {"platform": "android", "channel": "staging", "version_code": 1},
        {"platform": "android", "channel": "prod", "version_code": 0},
        {"platform": "android", "channel": "prod", "version_code": -3},
    ],
)
def test_invalid_params_return_422(db_session_factory, storage_dir, params):
    assert _client().get(LATEST_URL, params=params).status_code == 422


def test_download_returns_full_body_with_headers(db_session_factory, storage_dir):
    _, artifact_id = _seed_release(storage_dir, version_code=20)
    response = _client().get(f"/api/v1/app-release/artifacts/{artifact_id}/download")
    assert response.status_code == 200
    assert response.content == APK_PAYLOAD
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["x-artifact-sha256"] == hashlib.sha256(
        APK_PAYLOAD
    ).hexdigest()
    assert "zhaoxi.apk" in response.headers["content-disposition"]


def test_download_range_returns_206_with_content_range(
    db_session_factory, storage_dir
):
    _, artifact_id = _seed_release(storage_dir, version_code=20)
    response = _client().get(
        f"/api/v1/app-release/artifacts/{artifact_id}/download",
        headers={"Range": "bytes=3-"},
    )
    assert response.status_code == 206
    assert response.content == APK_PAYLOAD[3:]
    assert response.headers["content-range"] == (
        f"bytes 3-{len(APK_PAYLOAD) - 1}/{len(APK_PAYLOAD)}"
    )


def test_download_range_out_of_bounds_returns_416(db_session_factory, storage_dir):
    _, artifact_id = _seed_release(storage_dir, version_code=20)
    response = _client().get(
        f"/api/v1/app-release/artifacts/{artifact_id}/download",
        headers={"Range": f"bytes={len(APK_PAYLOAD) + 100}-"},
    )
    assert response.status_code == 416


def test_download_unknown_id_returns_404(db_session_factory, storage_dir):
    response = _client().get("/api/v1/app-release/artifacts/missing/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "制品不存在"


def test_download_missing_file_returns_404_without_path(
    db_session_factory, storage_dir
):
    _, artifact_id = _seed_release(storage_dir, version_code=20)
    for path in Path(storage_dir).rglob("*.apk"):
        path.unlink()
    response = _client().get(f"/api/v1/app-release/artifacts/{artifact_id}/download")
    assert response.status_code == 404
    assert str(storage_dir) not in response.text


def test_download_rejects_storage_path_escape(db_session_factory, storage_dir):
    release, _ = app_release_repository.upsert_release(
        "android",
        "prod",
        version_name="0.20.0",
        version_code=20,
        min_supported_version_code=18,
        force_update=False,
        release_notes=None,
        published_at=timeutil.now(),
    )
    artifact, _ = app_release_repository.upsert_artifact(
        release.id,
        artifact_type="full",
        from_version_code=None,
        storage_path="../escaped.apk",
        file_name="escaped.apk",
        size_bytes=10,
        sha256="0" * 64,
        signature_fingerprint=None,
    )
    response = _client().get(f"/api/v1/app-release/artifacts/{artifact.id}/download")
    assert response.status_code == 403


def test_api_module_has_no_repository_or_orm_import():
    tree = ast.parse(inspect.getsource(app_release_api))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        name
        for name in imported
        if name.startswith(
            ("app.repositories", "app.core.db", "sqlalchemy", "app.application")
        )
    }
    assert forbidden == set()


def test_service_layer_does_not_import_application_or_channels():
    source = inspect.getsource(release_service)
    assert "app.application" not in source
    assert "app.channels" not in source


@pytest.mark.parametrize(
    "storage_path",
    ["../x.apk", "/abs/x.apk", "a\\..\\b.apk", "", "prod/20/full/../../x.apk"],
)
def test_resolve_storage_path_rejects_escapes(storage_dir, storage_path):
    with pytest.raises(release_service.ArtifactPathRejected):
        release_service.resolve_storage_path(storage_path)


def test_resolve_storage_path_accepts_relative_inside_root(storage_dir):
    resolved = release_service.resolve_storage_path("prod/20/full/a.apk")
    assert resolved.is_relative_to(Path(storage_dir).resolve())


def _manifest(
    storage_dir: Path,
    *,
    channel: str = "prod",
    version_code: int = 21,
    schema_version: int = 1,
    overrides: dict | None = None,
) -> tuple[Path, dict]:
    relative, size, sha256 = _write_artifact(
        storage_dir, channel, version_code, name="zhaoxi-0.21.0+21-prod.apk"
    )
    manifest = {
        "schema_version": schema_version,
        "platform": "android",
        "channel": channel,
        "version_name": "0.21.0",
        "version_code": version_code,
        "min_supported_version_code": 18,
        "force_update": False,
        "release_notes": "新增自动更新",
        "published_at": "2026-10-09T00:00:00Z",
        "commit": "deadbeef",
        "built_at": "2026-10-09T00:00:00Z",
        "artifact": {
            "type": "full",
            "file_name": "zhaoxi-0.21.0+21-prod.apk",
            "size_bytes": size,
            "sha256": sha256,
            "signature_fingerprint": FINGERPRINT,
            "from_version_code": None,
        },
    }
    if overrides:
        manifest.update(overrides)
    path = Path(storage_dir) / f"{channel}" / str(version_code) / "full" / "release-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert relative
    return path, manifest


def test_import_manifest_creates_rows(db_session_factory, storage_dir):
    path, manifest = _manifest(storage_dir)
    summary = import_release.import_manifest(path, storage_dir=storage_dir)
    assert summary["release_created"] is True
    assert summary["artifact_created"] is True
    latest = app_release_repository.latest_release("android", "prod")
    assert latest is not None
    assert latest.version_code == manifest["version_code"]
    artifacts = app_release_repository.list_artifacts(latest.id)
    assert artifacts[0].sha256 == manifest["artifact"]["sha256"]


def test_import_manifest_is_idempotent(db_session_factory, storage_dir):
    path, _ = _manifest(storage_dir)
    first = import_release.import_manifest(path, storage_dir=storage_dir)
    second = import_release.import_manifest(path, storage_dir=storage_dir)
    assert first["release_id"] == second["release_id"]
    assert first["artifact_id"] == second["artifact_id"]
    assert second["release_created"] is False
    assert second["artifact_created"] is False


def test_import_rejects_unknown_schema_version(db_session_factory, storage_dir):
    path, _ = _manifest(storage_dir, schema_version=2)
    with pytest.raises(import_release.ImportRejected):
        import_release.import_manifest(path, storage_dir=storage_dir)


def test_import_rejects_sha256_mismatch(db_session_factory, storage_dir):
    path, manifest = _manifest(storage_dir)
    manifest["artifact"]["sha256"] = "a" * 64
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(import_release.ImportRejected):
        import_release.import_manifest(path, storage_dir=storage_dir)


def test_import_rejects_size_mismatch(db_session_factory, storage_dir):
    path, manifest = _manifest(storage_dir)
    manifest["artifact"]["size_bytes"] = manifest["artifact"]["size_bytes"] + 1
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(import_release.ImportRejected):
        import_release.import_manifest(path, storage_dir=storage_dir)


def test_import_rejects_declared_storage_path_escape(db_session_factory, storage_dir):
    path, manifest = _manifest(storage_dir)
    manifest["artifact"]["storage_path"] = "../escaped.apk"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(release_service.ArtifactPathRejected):
        import_release.import_manifest(path, storage_dir=storage_dir)


def test_import_rejects_min_supported_above_version(db_session_factory, storage_dir):
    path, manifest = _manifest(storage_dir)
    manifest["min_supported_version_code"] = manifest["version_code"] + 1
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(import_release.ImportRejected):
        import_release.import_manifest(path, storage_dir=storage_dir)


def test_import_rejects_patch_without_from_version(db_session_factory, storage_dir):
    path, manifest = _manifest(storage_dir)
    manifest["artifact"]["type"] = "patch"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(import_release.ImportRejected):
        import_release.import_manifest(path, storage_dir=storage_dir)


def test_import_rejects_overlong_release_notes(db_session_factory, storage_dir):
    path, manifest = _manifest(storage_dir)
    manifest["release_notes"] = "长" * (get_settings().app_release_notes_max_chars + 1)
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(import_release.ImportRejected):
        import_release.import_manifest(path, storage_dir=storage_dir)


def test_import_main_returns_nonzero_on_rejection(
    db_session_factory, storage_dir, capsys
):
    path, manifest = _manifest(storage_dir, schema_version=99)
    assert import_release.main(["--manifest", str(path), "--storage-dir", str(storage_dir)]) == 1
    assert "入库被拒绝" in capsys.readouterr().err
    assert manifest


def test_settings_defaults_and_flags():
    settings = get_settings()
    assert settings.app_release_notes_max_chars == 2000
    assert settings.app_release_storage_dir
    assert not any(
        name.endswith("_enabled")
        for name in type(settings).model_fields
        if name.startswith("app_release")
    )
