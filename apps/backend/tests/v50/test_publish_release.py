"""PLT-008 制品发布脚本契约测试（产物反读 / 签名门禁 / 归档 / manifest / 单调递增）。

外部工具（aapt2 / apksigner）以 `runner` 注入替身，测试不依赖 Android SDK。
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import zipfile
from pathlib import Path

import pytest

from scripts import publish_release

pytestmark = pytest.mark.unit

PROD_PACKAGE = "com.zhaoxi.app"
DEV_PACKAGE = "com.zhaoxi.app.dev"
GOOD_FINGERPRINT = ":".join(f"{index:02X}" for index in range(32))
GOOD_DN = "CN=Unknown, OU=Unknown, O=Unknown, L=Unknown, ST=Unknown, C=Unknown"
WORK_PAYLOAD = b"PK\x03\x04-signed-apk-body"


def _module_imports(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _module_string_constants(module) -> set[str]:
    """模块内字符串字面量（**不含 docstring**）：解释「为何不读 pubspec」不该算依赖。"""
    tree = ast.parse(inspect.getsource(module))
    body = tree.body
    doc_node = (
        body[0].value
        if body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
        else None
    )
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node is not doc_node
    }


def _badging(package: str = PROD_PACKAGE, version_code: int = 21, version_name: str = "0.21.0") -> str:
    return (
        f"package: name='{package}' versionCode='{version_code}' "
        f"versionName='{version_name}' platformBuildVersionName='15'\n"
        "sdkVersion:'26'\n"
    )


def _certs(dn: str = GOOD_DN, fingerprint: str = GOOD_FINGERPRINT) -> str:
    hex_only = fingerprint.replace(":", "")
    return (
        f"Signer #1 certificate DN: {dn}\n"
        f"Signer #1 certificate SHA-256 digest: {hex_only.lower()}\n"
    )


def _apk(
    path: Path,
    *,
    include_arm64: bool = True,
    payload: bytes = WORK_PAYLOAD,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"binary-manifest")
        archive.writestr("classes.dex", payload)
        if include_arm64:
            archive.writestr(publish_release.REQUIRED_ABI_ENTRY, b"arm64-flutter-engine")
    return path


def _runner(
    *,
    badging: str | None = None,
    certs: str | None = None,
    missing_tool: str | None = None,
):
    def _run(command: list[str]) -> str:
        if missing_tool is not None and command[0] == missing_tool:
            raise publish_release.ReleaseRejected(f"缺少工具 {command[0]}")
        if command[1:2] == ["dump"]:
            return badging if badging is not None else _badging()
        return certs if certs is not None else _certs()

    return _run


@pytest.fixture
def repo_files(tmp_path):
    key_properties = tmp_path / "key.properties"
    key_properties.write_text("storeFile=zhaoxi-release.jks\n", encoding="utf-8")
    apk = _apk(tmp_path / "build" / "app-prod-release.apk")
    storage = tmp_path / "releases"
    return {"key_properties": key_properties, "apk": apk, "storage": storage}


def _publish(repo_files, **overrides):
    payload = {
        "apk_path": repo_files["apk"],
        "channel": "prod",
        "storage_dir": repo_files["storage"],
        "min_supported_version_code": 18,
        "key_properties": repo_files["key_properties"],
        "runner": _runner(),
    }
    payload.update(overrides)
    return publish_release.publish(**payload)


def test_parse_badging_extracts_version_and_package():
    parsed = publish_release.parse_badging(_badging(version_code=7, version_name="1.2.3"))
    assert parsed["application_id"] == PROD_PACKAGE
    assert parsed["version_code"] == 7
    assert parsed["version_name"] == "1.2.3"


def test_parse_badging_rejects_missing_package_line():
    with pytest.raises(publish_release.ReleaseRejected):
        publish_release.parse_badging("sdkVersion:'26'\n")


def test_normalize_fingerprint_is_uppercase_colon_separated():
    lower_hex = "0123456789abcdef" * 4
    expected = ":".join(lower_hex.upper()[index : index + 2] for index in range(0, 64, 2))
    normalized = publish_release.normalize_fingerprint(lower_hex)
    assert normalized == expected
    assert normalized.count(":") == 31


def test_normalize_fingerprint_rejects_wrong_length():
    with pytest.raises(publish_release.ReleaseRejected):
        publish_release.normalize_fingerprint("aabb")


def test_parse_apksigner_certs_reads_dn_and_digest():
    dn, fingerprint = publish_release.parse_apksigner_certs(_certs())
    assert dn == GOOD_DN
    assert fingerprint == GOOD_FINGERPRINT


def test_publish_archives_and_writes_manifest(repo_files):
    summary = _publish(repo_files)
    manifest_path = Path(summary["manifest_path"])
    assert manifest_path.is_file()
    assert manifest_path.parent == repo_files["storage"] / "prod" / "21" / "full"
    assert summary["storage_path"] == "prod/21/full/zhaoxi-0.21.0+21-prod.apk"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["platform"] == "android"
    assert manifest["channel"] == "prod"
    assert manifest["version_code"] == 21
    assert manifest["version_name"] == "0.21.0"
    assert manifest["min_supported_version_code"] == 18
    assert manifest["force_update"] is False
    assert manifest["artifact"]["type"] == "full"
    assert manifest["artifact"]["from_version_code"] is None
    assert manifest["commit"]
    assert manifest["published_at"].endswith("+00:00")


def test_manifest_version_and_sha_come_from_artifact(repo_files):
    summary = _publish(repo_files, runner=_runner(badging=_badging(version_code=42, version_name="9.9.9")))
    manifest = json.loads(Path(summary["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["version_code"] == 42
    archived = repo_files["storage"] / "prod" / "42" / "full" / "zhaoxi-9.9.9+42-prod.apk"
    assert manifest["artifact"]["size_bytes"] == archived.stat().st_size
    assert manifest["artifact"]["sha256"] == hashlib.sha256(archived.read_bytes()).hexdigest()


def test_publish_rejects_missing_key_properties(repo_files):
    absent_dir = repo_files["key_properties"].parent / "absent"
    with pytest.raises(publish_release.ReleaseRejected) as excinfo:
        _publish(repo_files, key_properties=absent_dir / "key.properties")
    assert "key.properties" in str(excinfo.value)


def test_publish_rejects_debug_dn(repo_files):
    runner = _runner(certs=_certs(dn="CN=Android Debug, O=Android, C=US"))
    with pytest.raises(publish_release.ReleaseRejected) as excinfo:
        _publish(repo_files, runner=runner)
    assert "debug 签名" in str(excinfo.value)


def test_publish_rejects_known_debug_digest(repo_files):
    debug_hex = next(iter(publish_release.KNOWN_DEBUG_SHA256_HEX))
    runner = _runner(certs=_certs(fingerprint=debug_hex))
    with pytest.raises(publish_release.ReleaseRejected) as excinfo:
        _publish(repo_files, runner=runner)
    assert "debug" in str(excinfo.value)


def test_publish_rejects_missing_apksigner(repo_files):
    with pytest.raises(publish_release.ReleaseRejected) as excinfo:
        _publish(repo_files, runner=_runner(missing_tool="apksigner"))
    assert "apksigner" in str(excinfo.value)


def test_publish_rejects_flavor_channel_mismatch(repo_files):
    runner = _runner(badging=_badging(package=DEV_PACKAGE))
    with pytest.raises(publish_release.ReleaseRejected) as excinfo:
        _publish(repo_files, runner=runner)
    assert "flavor" in str(excinfo.value)


def test_publish_rejects_missing_arm64_engine(tmp_path):
    key_properties = tmp_path / "key.properties"
    key_properties.write_text("storeFile=x\n", encoding="utf-8")
    apk = _apk(tmp_path / "apk" / "app.apk", include_arm64=False)
    with pytest.raises(publish_release.ReleaseRejected) as excinfo:
        publish_release.publish(
            apk,
            channel="prod",
            storage_dir=tmp_path / "releases",
            min_supported_version_code=1,
            key_properties=key_properties,
            runner=_runner(),
        )
    assert "arm64" in str(excinfo.value)


def test_publish_rejects_version_code_regression(repo_files):
    _publish(repo_files)
    second_runner = _runner(badging=_badging(version_code=20, version_name="0.20.0"))
    with pytest.raises(publish_release.ReleaseRejected) as excinfo:
        _publish(repo_files, runner=second_runner)
    assert "单调递增" in str(excinfo.value)


def test_publish_allows_republish_with_flag(repo_files):
    first = _publish(repo_files)
    second = _publish(
        repo_files,
        runner=_runner(badging=_badging(version_code=21, version_name="0.21.0")),
        allow_republish=True,
    )
    assert first["storage_path"] == second["storage_path"]
    manifests = list(repo_files["storage"].rglob(publish_release.MANIFEST_FILE_NAME))
    assert len(manifests) == 1


def test_publish_rejects_expect_version_code_mismatch(repo_files):
    with pytest.raises(publish_release.ReleaseRejected):
        _publish(repo_files, expect_version_code=99)


def test_publish_rejects_min_supported_above_version(repo_files):
    with pytest.raises(publish_release.ReleaseRejected):
        _publish(repo_files, min_supported_version_code=100)


def test_max_published_version_code_scans_channel(tmp_path):
    assert publish_release.max_published_version_code(tmp_path, "prod") is None
    (tmp_path / "prod" / "10").mkdir(parents=True)
    (tmp_path / "prod" / "12").mkdir(parents=True)
    (tmp_path / "dev" / "99").mkdir(parents=True)
    assert publish_release.max_published_version_code(tmp_path, "prod") == 12
    assert publish_release.max_published_version_code(tmp_path, "dev") == 99


def test_release_notes_from_file_preferred(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("  从文件读取的说明  \n", encoding="utf-8")
    assert publish_release.release_notes_text("inline", from_file=str(notes)) == "从文件读取的说明"
    assert publish_release.release_notes_text("inline") == "inline"


def test_main_returns_nonzero_on_rejection(repo_files, tmp_path, capsys):
    exit_code = publish_release.main(
        [
            "--apk",
            str(repo_files["apk"]),
            "--channel",
            "prod",
            "--storage-dir",
            str(repo_files["storage"]),
            "--min-supported-version-code",
            "1",
            "--aapt",
            "definitely-missing-aapt2",
        ]
    )
    assert exit_code == 1
    assert "发布被拒绝" in capsys.readouterr().err


def test_script_does_not_read_pubspec():
    literals = _module_string_constants(publish_release)
    assert not [value for value in literals if "pubspec" in value]


def test_script_does_not_import_backend_runtime():
    imported = _module_imports(publish_release)
    forbidden = {
        name
        for name in imported
        if name.startswith(("app.", "sqlalchemy", "tests."))
    }
    assert forbidden == set()
