"""静态依赖边界守门（FEISHU-006 §6.2，R1~R5，常驻 Fast Test）。

AST 扫描实现（非正则），fail-closed：新增依赖必须显式进入 allowlist 才能通过。
不 import 被测模块本身，只解析源码。
"""

import ast
import sys
from pathlib import Path

import pytest

APP_DIR = Path("app")

CHANNELS_ALLOWLIST_PREFIXES = (
    "app.core",
    "app.channels",
    "app.services.identity.channel",
    "app.services.observability.collector",
    # R-7'：通道只依赖独立叶子门面，不绑定 agent_runtime / chat_pipeline 包内路径。
    # T-33：`app.services.agent_service` 壳退役后，前台入口经本门面转发。
    "app.application.channel_gateway",
)

CHANNELS_APP_DENY_EXACT = (
    "app.application.chat_pipeline",
    "app.application.post_process",
    "app.core.db",
)

CHANNELS_APP_DENY_SUBSTRINGS = (
    "autonomy",
    "life_loop",
    "scheduler",
    "proactive_executor",
    "trigger_evaluator",
    "autonomy_policy",
)

CHANNELS_THIRD_PARTY_DENY_ROOTS = (
    "httpx",
    "requests",
    "redis",
    "celery",
    "kafka",
    "pika",
    "aiohttp",
)

CORE_SCAN_DIRS = (
    "application",
    "services",
    "repositories",
    "character",
    "chains",
    "models",
    "prompts",
    "core",
)

CORE_FULL_DENY_DIRS = ("repositories", "character", "chains", "core")


def _module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_of(path: Path) -> str:
    return ".".join(path.parent.parts)


def _resolve_from(module: str | None, level: int, package: str) -> str:
    if not level:
        return module or ""
    base = package.split(".")
    for _ in range(level - 1):
        if base:
            base.pop()
    resolved = ".".join(base)
    if module:
        return f"{resolved}.{module}" if resolved else module
    return resolved


def _collect_import_groups(path: Path) -> list[tuple[int, str, list[str]]]:
    """返回 [(行号, 被导入模块, 别名限定名列表)]。

    `from pkg import name` 会同时产生 pkg 与 pkg.name 两级路径，供
    allowlist / denylist 按最具体路径判定。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _package_of(path)
    groups: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                groups.append((node.lineno, alias.name, []))
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from(node.module, node.level, package)
            names = [f"{resolved}.{alias.name}" if resolved else alias.name for alias in node.names]
            groups.append((node.lineno, resolved, names))
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            dynamic = (
                isinstance(func, ast.Name) and func.id == "__import__"
            ) or (
                isinstance(func, ast.Attribute) and func.attr == "import_module"
            )
            if dynamic:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    groups.append((node.lineno, arg.value, []))
    return groups


def _python_files(*rel_dirs: str) -> list[Path]:
    files: list[Path] = []
    for rel in rel_dirs:
        directory = APP_DIR / rel
        if directory.exists():
            files.extend(sorted(directory.rglob("*.py")))
    return files


def _scan_channels() -> list[str]:
    violations: list[str] = []
    for path in _python_files("channels"):
        for lineno, module, names in _collect_import_groups(path):
            candidates = [candidate for candidate in (module, *names) if candidate]
            app_candidates = [c for c in candidates if c.startswith("app.")]
            if any(
                candidate in CHANNELS_APP_DENY_EXACT
                or any(banned in candidate.lower() for banned in CHANNELS_APP_DENY_SUBSTRINGS)
                for candidate in app_candidates
            ):
                violations.append(f"{path}:{lineno} 违规 import: {module or names}")
                continue
            if app_candidates and not any(
                candidate.startswith(CHANNELS_ALLOWLIST_PREFIXES)
                for candidate in app_candidates
            ):
                violations.append(f"{path}:{lineno} 未在 allowlist（fail-closed）: {module or names}")
                continue
            for candidate in candidates:
                root = candidate.split(".")[0]
                if root in CHANNELS_THIRD_PARTY_DENY_ROOTS:
                    violations.append(f"{path}:{lineno} 违规第三方 import: {candidate}")
    return violations


def _scan_core() -> list[str]:
    violations: list[str] = []
    for path in _python_files(*CORE_SCAN_DIRS):
        full_deny = any(
            str(path).replace("\\", "/").startswith(f"app/{rel}/")
            for rel in CORE_FULL_DENY_DIRS
        )
        for lineno, module, names in _collect_import_groups(path):
            effective = [
                candidate
                for candidate in (module, *names)
                if candidate.startswith("app.channels.")
            ]
            if not effective:
                continue
            violating = [
                candidate
                for candidate in effective
                if candidate != "app.channels.base"
                and not candidate.startswith("app.channels.base.")
            ]
            if full_deny or violating:
                violations.append(f"{path}:{lineno} 违规 import: {effective}")
    return violations


def test_direction1_channels_imports_within_allowlist():
    violations = _scan_channels()
    assert violations == []


def test_direction2_core_never_imports_channel_impl():
    violations = _scan_core()
    assert violations == []


def test_direction2_r2_channel_identity_service_may_import_base():
    service_path = APP_DIR / "services" / "identity" / "channel.py"
    flat = [
        name
        for _, module, names in _collect_import_groups(service_path)
        for name in ([module] + names)
        if name
    ]
    assert "app.channels.base" in flat
    violations = [v for v in _scan_core() if "identity.channel" in v]
    assert violations == []


def test_direction2_api_and_main_excluded_from_scan():
    scanned = {str(p) for p in _python_files(*CORE_SCAN_DIRS)}
    assert not any("/api/" in p for p in scanned)
    assert not any(p.endswith("app/main.py") or p == "app\\main.py" for p in scanned)


def test_direction3_base_py_stdlib_only():
    base_path = APP_DIR / "channels" / "base.py"
    for lineno, module, _names in _collect_import_groups(base_path):
        root = module.split(".")[0]
        assert not module.startswith("app."), (
            f"{base_path}:{lineno} base.py 不得 import app.*: {module}"
        )
        assert root in sys.stdlib_module_names, (
            f"{base_path}:{lineno} base.py 只允许标准库: {module}"
        )


def test_negative_scanner_flags_fake_violations(tmp_path):
    bad_service = tmp_path / "bad_service.py"
    bad_service.write_text(
        "from app.channels.feishu import client\n"
        "import httpx\n",
        encoding="utf-8",
    )
    good_service = tmp_path / "good_service.py"
    good_service.write_text(
        "from app.channels.base import RecipientRef\n"
        "from app.core.settings import get_settings\n",
        encoding="utf-8",
    )
    flagged = []
    for path in (bad_service, good_service):
        for lineno, module, names in _collect_import_groups(path):
            for candidate in [module, *names]:
                if not candidate:
                    continue
                if candidate.startswith("app.channels.") and not candidate.startswith(
                    "app.channels.base"
                ):
                    flagged.append(f"{path}:{lineno} 违规 import: {candidate}")
                elif candidate.split(".")[0] in CHANNELS_THIRD_PARTY_DENY_ROOTS:
                    flagged.append(f"{path}:{lineno} 违规第三方 import: {candidate}")
    assert any("app.channels.feishu" in v for v in flagged)
    assert any("httpx" in v for v in flagged)
    assert not any("good_service" in v for v in flagged)


def test_negative_base_scanner_flags_injected_dependencies(tmp_path):
    fake_base = tmp_path / "fake_base.py"
    fake_base.write_text(
        "import httpx\n"
        "from app.core.settings import get_settings\n",
        encoding="utf-8",
    )
    flagged = []
    for lineno, module, _names in _collect_import_groups(fake_base):
        if module.startswith("app."):
            flagged.append((lineno, module))
        elif module.split(".")[0] not in sys.stdlib_module_names:
            flagged.append((lineno, module))
    modules = [module for _, module in flagged]
    assert "httpx" in modules
    assert "app.core.settings" in modules


@pytest.mark.parametrize("dir_name", CORE_SCAN_DIRS)
def test_direction2_per_directory_no_impl_import(dir_name):
    violations = [
        v for v in _scan_core() if f"app/{dir_name}/" in v.replace("\\", "/")
    ]
    assert violations == []
