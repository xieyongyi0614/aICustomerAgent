"""把 `PLT-008` 产出的 `release-manifest.json` 幂等入库（`app_releases` / `app_release_artifacts`）。

为什么不开口管理端点：内测期无可信管理鉴权体系（调试面鉴权 `IDENT-010` 仍留白），
开放未鉴权的写接口 = 任何人可推假版本。入库因此走服务器本地脚本，攻击面 = 本地文件权限。

校验顺序（任一步不过即非 0 退出，**不部分写入**）：
1. `schema_version == 1`（未知契约版本拒绝，fail-closed）；
2. 枚举域校验（platform / channel / artifact.type / force_update / 版本号区间）；
3. 制品路径解析后必须仍在存储根目录之下（绝对路径 / `..` / 反斜杠一律拒绝）；
4. **重算** `size_bytes` 与 `sha256` 并与 manifest 比对（制品即真相的第二次收口）。

用法：
    uv run python -m scripts.import_release --manifest <path/to/release-manifest.json>
    uv run python -m scripts.import_release --manifest <...> --storage-dir <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core import timeutil
from app.core.settings import get_settings
from app.repositories import app_release_repository
from app.services.app_release import service as release_service

MANIFEST_SCHEMA_VERSION = 1
PLATFORMS = ("android", "ios")
CHANNELS = ("dev", "prod")
ARTIFACT_TYPES = ("full", "patch")
FULL_TYPE = "full"
_CHUNK = 1024 * 1024


class ImportRejected(Exception):
    """manifest 校验不通过。"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ImportRejected(message)


def _parse_published_at(raw: Any) -> datetime:
    _require(isinstance(raw, str) and raw.strip(), "published_at 缺失")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ImportRejected(f"published_at 不是合法 ISO-8601：{raw}") from exc
    aware = timeutil.ensure_aware(parsed)
    _require(aware is not None, "published_at 无法解析")
    return aware


def _relative_storage_path(manifest: dict[str, Any], artifact: dict[str, Any]) -> str:
    declared = artifact.get("storage_path")
    if declared is not None:
        _require(
            isinstance(declared, str) and declared.strip(),
            "artifact.storage_path 必须是非空字符串",
        )
        return declared.strip()
    return "/".join(
        (
            str(manifest["channel"]),
            str(manifest["version_code"]),
            str(artifact["type"]),
            str(artifact["file_name"]),
        )
    )


def validate_manifest(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    notes_max = get_settings().app_release_notes_max_chars
    _require(
        manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION,
        f"schema_version 必须是 {MANIFEST_SCHEMA_VERSION}，"
        f"实际为 {manifest.get('schema_version')!r}",
    )
    platform = manifest.get("platform")
    channel = manifest.get("channel")
    _require(platform in PLATFORMS, f"platform 越域：{platform!r}")
    _require(channel in CHANNELS, f"channel 越域：{channel!r}")
    version_name = manifest.get("version_name")
    _require(
        isinstance(version_name, str) and version_name.strip(),
        "version_name 必须是非空字符串",
    )
    version_code = manifest.get("version_code")
    _require(
        isinstance(version_code, int) and not isinstance(version_code, bool)
        and version_code > 0,
        f"version_code 必须是正整数：{version_code!r}",
    )
    min_supported = manifest.get("min_supported_version_code")
    _require(
        isinstance(min_supported, int) and not isinstance(min_supported, bool)
        and min_supported >= 0,
        f"min_supported_version_code 必须是非负整数：{min_supported!r}",
    )
    _require(
        min_supported <= version_code,
        "min_supported_version_code 不得大于 version_code",
    )
    force_update = manifest.get("force_update")
    _require(isinstance(force_update, bool), "force_update 必须是布尔值")
    release_notes = manifest.get("release_notes")
    _require(release_notes is None or isinstance(release_notes, str), "release_notes 必须是字符串或 null")
    if isinstance(release_notes, str):
        _require(
            len(release_notes) <= notes_max,
            f"release_notes 超过上限 {notes_max} 字符（实际 {len(release_notes)}）",
        )
    published_at = _parse_published_at(manifest.get("published_at"))

    artifact = manifest.get("artifact")
    _require(isinstance(artifact, dict), "manifest.artifact 缺失")
    artifact_type = artifact.get("type")
    _require(artifact_type in ARTIFACT_TYPES, f"artifact.type 越域：{artifact_type!r}")
    from_version_code = artifact.get("from_version_code")
    if artifact_type == FULL_TYPE:
        _require(
            from_version_code is None,
            "artifact.from_version_code 对全量包必须为 null",
        )
    else:
        _require(
            isinstance(from_version_code, int)
            and not isinstance(from_version_code, bool)
            and from_version_code > 0,
            "补丁包必须给出正整数 artifact.from_version_code",
        )
    file_name = artifact.get("file_name")
    _require(
        isinstance(file_name, str) and file_name.strip() and "/" not in file_name
        and "\\" not in file_name,
        f"artifact.file_name 必须是单段文件名：{file_name!r}",
    )
    size_bytes = artifact.get("size_bytes")
    _require(
        isinstance(size_bytes, int) and not isinstance(size_bytes, bool)
        and size_bytes > 0,
        f"artifact.size_bytes 必须是正整数：{size_bytes!r}",
    )
    sha256 = artifact.get("sha256")
    _require(
        isinstance(sha256, str) and len(sha256) == 64 and sha256 == sha256.lower(),
        "artifact.sha256 必须是 64 位小写十六进制",
    )
    signature = artifact.get("signature_fingerprint")
    _require(
        signature is None or (isinstance(signature, str) and signature.strip()),
        "artifact.signature_fingerprint 必须是字符串或 null",
    )

    relative = _relative_storage_path(manifest, artifact)
    resolved = release_service.resolve_storage_path(relative, root=root)
    _require(resolved.is_file(), f"制品文件不存在：{relative}")
    actual_size = resolved.stat().st_size
    _require(
        actual_size == size_bytes,
        f"size_bytes 不符：manifest {size_bytes} vs 实际 {actual_size}",
    )
    actual_sha256 = sha256_file(resolved)
    _require(
        actual_sha256 == sha256,
        f"sha256 不符：manifest {sha256} vs 实际 {actual_sha256}",
    )

    return {
        "platform": platform,
        "channel": channel,
        "version_name": version_name.strip(),
        "version_code": version_code,
        "min_supported_version_code": min_supported,
        "force_update": force_update,
        "release_notes": release_notes,
        "published_at": published_at,
        "artifact_type": artifact_type,
        "from_version_code": from_version_code,
        "storage_path": relative,
        "file_name": file_name.strip(),
        "size_bytes": size_bytes,
        "sha256": sha256,
        "signature_fingerprint": signature,
    }


def import_manifest(manifest_path: str | Path, *, storage_dir: str | Path | None = None) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.is_file():
        raise ImportRejected(f"manifest 不存在：{path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImportRejected(f"manifest 不是合法 JSON：{exc}") from exc
    if not isinstance(manifest, dict):
        raise ImportRejected("manifest 顶层必须是对象")

    root = Path(storage_dir) if storage_dir is not None else release_service.storage_root()
    payload = validate_manifest(manifest, root)

    release, release_created = app_release_repository.upsert_release(
        payload["platform"],
        payload["channel"],
        version_name=payload["version_name"],
        version_code=payload["version_code"],
        min_supported_version_code=payload["min_supported_version_code"],
        force_update=payload["force_update"],
        release_notes=payload["release_notes"],
        published_at=payload["published_at"],
    )
    artifact, artifact_created = app_release_repository.upsert_artifact(
        release.id,
        artifact_type=payload["artifact_type"],
        from_version_code=payload["from_version_code"],
        storage_path=payload["storage_path"],
        file_name=payload["file_name"],
        size_bytes=payload["size_bytes"],
        sha256=payload["sha256"],
        signature_fingerprint=payload["signature_fingerprint"],
    )
    return {
        "release_id": release.id,
        "release_created": release_created,
        "artifact_id": artifact.id,
        "artifact_created": artifact_created,
        "version_code": release.version_code,
        "channel": release.channel,
        "storage_path": artifact.storage_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布制品入库（幂等）")
    parser.add_argument("--manifest", required=True, help="release-manifest.json 路径")
    parser.add_argument("--storage-dir", default=None, help="制品根目录（缺省取设置项）")
    args = parser.parse_args(argv)
    try:
        summary = import_manifest(args.manifest, storage_dir=args.storage_dir)
    except (ImportRejected, release_service.ArtifactPathRejected) as exc:
        print(f"入库被拒绝：{exc}", file=sys.stderr)
        return 1
    action = "新增" if summary["release_created"] else "更新"
    artifact_action = "新增" if summary["artifact_created"] else "更新"
    print(
        f"{action}发布 {summary['channel']} v{summary['version_code']} "
        f"release_id={summary['release_id']}；{artifact_action}制品 "
        f"artifact_id={summary['artifact_id']} storage_path={summary['storage_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
