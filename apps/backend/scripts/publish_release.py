"""把已签名 APK 变成可被服务端消费的制品（PLT-008）：反读版本 → 门禁 → 归档 → manifest。

设计要点：
- **版本号从产物反读**（`aapt2 dump badging`），不从 `pubspec.yaml` 解析——`pubspec.yaml`
  与最终产物之间存在 flavor / `--dart-define` / 手工覆盖三层偏差。
- **签名指纹硬门禁**：`android/key.properties` 缺失时 release 会静默回退 debug 签名
  （`apps/mobile/android/app/build.gradle.kts`），一旦分发出去，已安装用户**永久无法
  覆盖升级**。故 debug 签名（DN 含 `Android Debug` 或命中已知 debug 摘要）一律非 0 退出。
- **只测量与归档，不改包**：不重签名、不二次压缩、不做路径猜测。
- 与 `PLT-005` 的边界：`PLT-005` 负责构建出签名 APK，本脚本负责「APK → 制品 + 元数据」。

用法：
    uv run python -m scripts.publish_release --apk <path> --channel prod \
        --storage-dir <dir> --min-supported-version-code 1 \
        --release-notes "修复若干问题"
    uv run python -m scripts.publish_release --apk <path> --channel dev --allow-republish
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILE_NAME = "release-manifest.json"
FULL_ARTIFACT_TYPE = "full"
DEFAULT_PLATFORM = "android"
DEFAULT_AAPT = "aapt2"
DEFAULT_APKSIGNER = "apksigner"
CHANNELS = ("dev", "prod")
PACKAGE_BY_CHANNEL = {"prod": "com.zhaoxi.app", "dev": "com.zhaoxi.app.dev"}
KEY_PROPERTIES = Path("apps/mobile/android/key.properties")
REPO_ROOT_MARKER = "apps"
REQUIRED_ABI_ENTRY = "lib/arm64-v8a/libflutter.so"
DEBUG_DN_MARKER = "cn=android debug"
KNOWN_DEBUG_SHA256_HEX = {
    "61ed377e85d386a8dfee6b864bd85b0bfaa5af8152ac655b5c2bf26d146b5a03",
}
_CHUNK = 1024 * 1024


class ReleaseRejected(Exception):
    """发布前置校验或门禁不通过。"""


CommandRunner = Callable[[list[str]], str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseRejected(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_command_runner(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ReleaseRejected(
            f"缺少工具 {command[0]}：请安装 Android SDK build-tools 并加入 PATH"
        ) from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "").strip()
        raise ReleaseRejected(f"{command[0]} 执行失败：{message}") from exc
    return completed.stdout


def normalize_fingerprint(raw: str) -> str:
    """归一化为大写、冒号分隔的 SHA-256 指纹（客户端比对口径）。"""
    hex_only = "".join(ch for ch in raw if ch in "0123456789abcdefABCDEF").upper()
    _require(len(hex_only) == 64, f"签名指纹长度不是 64 位十六进制：{raw!r}")
    return ":".join(hex_only[index : index + 2] for index in range(0, 64, 2))


def fingerprint_hex(raw: str) -> str:
    return normalize_fingerprint(raw).replace(":", "").lower()


def parse_badging(text: str) -> dict[str, Any]:
    """解析 `aapt2 dump badging` 的 package 行。"""
    line = next(
        (row for row in text.splitlines() if row.startswith("package: ")),
        None,
    )
    _require(line is not None, "aapt2 输出中没有 package 行")
    assert line is not None
    fields: dict[str, str] = {}
    for token in line[len("package: ") :].split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        fields[key.strip()] = value.strip().strip("'")
    version_code = fields.get("versionCode")
    _require(
        version_code is not None and version_code.isdigit(),
        f"aapt2 输出缺少 versionCode：{line}",
    )
    _require(bool(fields.get("versionName")), "aapt2 输出缺少 versionName")
    _require(bool(fields.get("name")), "aapt2 输出缺少 package name")
    return {
        "application_id": fields["name"],
        "version_code": int(version_code or 0),
        "version_name": fields["versionName"],
    }


def parse_apksigner_certs(text: str) -> tuple[str | None, str | None]:
    """从 `apksigner verify --print-certs` 输出取 (DN, 归一化指纹)。"""
    dn: str | None = None
    fingerprint: str | None = None
    for row in text.splitlines():
        if "certificate DN:" in row and dn is None:
            dn = row.split("certificate DN:", 1)[1].strip()
        elif "SHA-256 digest:" in row and fingerprint is None:
            fingerprint = normalize_fingerprint(row.split("SHA-256 digest:", 1)[1].strip())
    return dn, fingerprint


def read_apk_metadata(
    apk_path: Path,
    *,
    aapt: str = DEFAULT_AAPT,
    apksigner: str = DEFAULT_APKSIGNER,
    runner: CommandRunner = default_command_runner,
) -> dict[str, Any]:
    badging = parse_badging(runner([aapt, "dump", "badging", str(apk_path)]))
    dn, fingerprint = parse_apksigner_certs(
        runner([apksigner, "verify", "--print-certs", str(apk_path)])
    )
    return {**badging, "signer_dn": dn, "signature_fingerprint": fingerprint}


def abi_entries(apk_path: Path) -> set[str]:
    with zipfile.ZipFile(apk_path) as archive:
        return set(archive.namelist())


def max_published_version_code(storage_dir: Path, channel: str) -> int | None:
    channel_dir = Path(storage_dir) / channel
    if not channel_dir.is_dir():
        return None
    codes = [
        int(entry.name)
        for entry in channel_dir.iterdir()
        if entry.is_dir() and entry.name.isdigit()
    ]
    return max(codes) if codes else None


def release_notes_text(raw: str | None, *, from_file: str | None = None) -> str | None:
    if from_file is not None:
        return Path(from_file).read_text(encoding="utf-8").strip()
    return raw


def publish(
    apk_path: str | Path,
    *,
    channel: str,
    storage_dir: str | Path,
    min_supported_version_code: int,
    force_update: bool = False,
    release_notes: str | None = None,
    platform: str = DEFAULT_PLATFORM,
    expect_version_code: int | None = None,
    allow_republish: bool = False,
    aapt: str = DEFAULT_AAPT,
    apksigner: str = DEFAULT_APKSIGNER,
    key_properties: str | Path | None = None,
    runner: CommandRunner = default_command_runner,
) -> dict[str, Any]:
    _require(channel in CHANNELS, f"channel 越域：{channel!r}")
    apk = Path(apk_path)
    _require(apk.is_file(), f"APK 不存在：{apk}")

    resolved_key_properties = (
        Path(key_properties) if key_properties is not None else _locate_key_properties(apk)
    )
    _require(
        resolved_key_properties.is_file(),
        f"缺少 {resolved_key_properties}：release 会静默回退 debug 签名，拒绝发布",
    )

    meta = read_apk_metadata(apk, aapt=aapt, apksigner=apksigner, runner=runner)
    _require(
        meta["signature_fingerprint"] is not None,
        "无法读取 APK 签名指纹：请确认 apksigner 可用（不得回退 keytool）",
    )
    _reject_debug_signature(meta["signer_dn"], meta["signature_fingerprint"])
    if expect_version_code is not None:
        _require(
            meta["version_code"] == expect_version_code,
            f"versionCode 与期望不符：产物 {meta['version_code']} vs 期望 {expect_version_code}",
        )
    _require(
        min_supported_version_code >= 0,
        "min_supported_version_code 必须非负",
    )
    _require(
        min_supported_version_code <= meta["version_code"],
        "min_supported_version_code 不得大于 version_code",
    )
    _require_flavor(meta["application_id"], channel)
    _require_arm64(apk, meta["application_id"])
    _require_monotonic(
        Path(storage_dir),
        channel,
        meta["version_code"],
        allow_republish=allow_republish,
    )

    file_name = f"zhaoxi-{meta['version_name']}+{meta['version_code']}-{channel}.apk"
    relative = f"{channel}/{meta['version_code']}/{FULL_ARTIFACT_TYPE}/{file_name}"
    target_dir = Path(storage_dir) / channel / str(meta["version_code"]) / FULL_ARTIFACT_TYPE
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / file_name
    if target.resolve() != apk.resolve():
        target.write_bytes(apk.read_bytes())

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "platform": platform,
        "channel": channel,
        "version_name": meta["version_name"],
        "version_code": meta["version_code"],
        "min_supported_version_code": min_supported_version_code,
        "force_update": force_update,
        "release_notes": release_notes,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "commit": _git_head(),
        "built_at": datetime.fromtimestamp(
            target.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "artifact": {
            "type": FULL_ARTIFACT_TYPE,
            "file_name": file_name,
            "size_bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            "signature_fingerprint": meta["signature_fingerprint"],
            "from_version_code": None,
        },
    }
    manifest_path = target_dir / MANIFEST_FILE_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "manifest_path": str(manifest_path),
        "storage_path": relative,
        "file_name": file_name,
        "application_id": meta["application_id"],
        "version_code": meta["version_code"],
        "version_name": meta["version_name"],
        "sha256": manifest["artifact"]["sha256"],
        "signature_fingerprint": meta["signature_fingerprint"],
    }


def _locate_key_properties(apk: Path) -> Path:
    for base in (Path.cwd(), *Path.cwd().parents, apk.parent, *apk.parents):
        candidate = base / KEY_PROPERTIES
        if (base / REPO_ROOT_MARKER).is_dir() and candidate.is_file():
            return candidate
        if candidate.is_file():
            return candidate
    return Path.cwd() / KEY_PROPERTIES


def _reject_debug_signature(dn: str | None, fingerprint: str | None) -> None:
    if dn is not None and DEBUG_DN_MARKER in dn.lower():
        raise ReleaseRejected("疑似 debug 签名回退（证书 DN 含 Android Debug）：拒绝发布")
    if fingerprint is not None:
        digest = fingerprint.replace(":", "").lower()
        _require(
            digest not in KNOWN_DEBUG_SHA256_HEX,
            "疑似 debug 签名回退（命中已知 debug 证书摘要）：拒绝发布",
        )


def _require_flavor(application_id: str, channel: str) -> None:
    expected = PACKAGE_BY_CHANNEL[channel]
    _require(
        application_id == expected,
        f"flavor 与 channel 不匹配：产物 {application_id} vs {channel} 期望 {expected}",
    )


def _require_arm64(apk: Path, application_id: str) -> None:
    entries = abi_entries(apk)
    _require(
        REQUIRED_ABI_ENTRY in entries,
        f"{application_id} 缺少 {REQUIRED_ABI_ENTRY}：真机可能白屏闪退（需 --target-platform android-arm64）",
    )


def _require_monotonic(
    storage_dir: Path,
    channel: str,
    version_code: int,
    *,
    allow_republish: bool,
) -> None:
    current = max_published_version_code(storage_dir, channel)
    if current is None or allow_republish:
        return
    _require(
        version_code > current,
        f"versionCode 必须单调递增：已发布 {current}，本次 {version_code}"
        "（同号重发请显式加 --allow-republish）",
    )


def _git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _git_dirty() -> bool:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(completed.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="APK 制品发布（含签名门禁与 manifest 产出）")
    parser.add_argument("--apk", required=True, help="已签名 APK 路径")
    parser.add_argument("--channel", required=True, choices=list(CHANNELS))
    parser.add_argument("--storage-dir", required=True, help="制品根目录")
    parser.add_argument("--min-supported-version-code", type=int, default=0)
    parser.add_argument("--force-update", action="store_true")
    parser.add_argument("--release-notes", default=None, help="更新说明纯文本")
    parser.add_argument("--release-notes-file", default=None, help="更新说明文件（优先于 --release-notes）")
    parser.add_argument("--platform", default=DEFAULT_PLATFORM, choices=["android", "ios"])
    parser.add_argument("--expect-version-code", type=int, default=None)
    parser.add_argument("--allow-republish", action="store_true")
    parser.add_argument("--aapt", default=DEFAULT_AAPT)
    parser.add_argument("--apksigner", default=DEFAULT_APKSIGNER)
    args = parser.parse_args(argv)

    if _git_dirty():
        print("警告：工作区不干净，manifest 的 commit 可能不含全部改动", file=sys.stderr)
    try:
        summary = publish(
            args.apk,
            channel=args.channel,
            storage_dir=args.storage_dir,
            min_supported_version_code=args.min_supported_version_code,
            force_update=args.force_update,
            release_notes=release_notes_text(
                args.release_notes, from_file=args.release_notes_file
            ),
            platform=args.platform,
            expect_version_code=args.expect_version_code,
            allow_republish=args.allow_republish,
            aapt=args.aapt,
            apksigner=args.apksigner,
        )
    except ReleaseRejected as exc:
        print(f"发布被拒绝：{exc}", file=sys.stderr)
        return 1
    print(
        f"已归档 {summary['application_id']} v{summary['version_name']}"
        f"({summary['version_code']}) → {summary['manifest_path']}\n"
        f"  storage_path={summary['storage_path']}\n"
        f"  sha256={summary['sha256']}\n"
        f"  signature_fingerprint={summary['signature_fingerprint']}"
    )
    print("下一步：uv run python -m scripts.import_release --manifest <上面的 manifest 路径>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
