"""services 域间边界扫描器（T-32）：静态解析 `app/services/<domain>` 的跨域 import。

规则来源：`apps/backend/AGENTS.md`「services 域间边界」（T-10 立规，2026-10-09）。

**规则**：`services/<domain>` 不得直接 import 另一个域 `services/<other>` 的**内部模块**，
只能经该域对外契约面（`port.py` / `contracts.py` / `engine_port.py`）访问。
域内文件互相 import 不受限。

判定细节（fail-closed）：

1. **直接子模块导入** —— `from app.services.tool import channel_tools`
   （或 `app.services.tool.channel_tools`）⇒ 违规。
2. **`__init__.py` re-export 绕行** —— `from app.services.ledger import record_entry`。
   当且仅当目标域的 `__init__.py` 有 re-export（`ledger` / `observability` / `car` /
   `governance` / `grounding` / `app_release`）时，该导入实际取到内部模块 ⇒ 违规。
   若目标域 `__init__.py` 为空 / 仅 docstring（如 `world` / `memory` / `tool` / `action`），
   则 `app.services.<domain>` 只是包引用，不含具体内部依赖 ⇒ 放行。
   ⚠️ 例外：同语句**显式点名**契约面时（`from app.services.X import port`），
   其包根候选 `app.services.X` 豁免——否则会把合法的契约面访问误判为 re-export 绕行。
3. **契约面** —— 目标路径叶子为 `port` / `contracts` / `engine_port` ⇒ 合法。
   契约面文件自身的跨域 import 亦豁免（其存在意义就是转发）。
4. `app/services/__init__.py` 等顶层文件不受域间约束。

**基线机制**：仓库现状存在大量既有违规（232 条 / 58 个域对）。守卫不追求一次清零，
而是把现状冻结成基线（key = `源文件 -> 目标模块`，**不含行号**，故行号漂移不误报），
只对**新增**违规 fail-closed。基线见 `tests/support/domain_boundary_baseline.py`。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

CONTRACT_STEMS = frozenset({"port", "contracts", "engine_port"})

SERVICES_PACKAGE = "app.services"

#: 仓库根（`apps/backend/`）——由本文件位置锚定，不依赖 CWD。
BACKEND_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = BACKEND_ROOT / "app" / "services"


@dataclass(frozen=True, order=True)
class Violation:
    """一条跨域内部依赖。key 不含行号 → 行号漂移不产生假红。

    与基线清单的 `tuple[str, str]` 之间用 `key()` / `from_key()` 互转，
    避免 `Violation` 与 `tuple` 混比导致的静默不匹配。
    """

    source: str  # 相对 apps/backend 的源文件路径，如 app/services/action/planner.py
    target: str  # 被导入的目标模块，如 app.services.tool.registry

    def key(self) -> tuple[str, str]:
        """转为基线清单用的裸元组。"""
        return (self.source, self.target)

    @classmethod
    def from_key(cls, key: tuple[str, str]) -> "Violation":
        return cls(source=key[0], target=key[1])

    def render(self) -> str:
        return f"{self.source} -> {self.target}"


def _module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_of(path: Path) -> str:
    return ".".join(path.parent.parts)


def _resolve_from(module: str | None, level: int, package: str) -> str:
    """解析相对 import 的绝对模块名（与 test_feishu_boundary 同算法）。"""
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


@dataclass(frozen=True)
class ImportedName:
    """一条 import 语句解析结果。

    `module` 是被导入的模块路径；对 `from pkg import a, b` 而言，
    `module = pkg` 且 `names = ("a", "b")`——保留 `names` 是为了判断
    「这条语句是否显式点名了契约面」，从而豁免其包根候选。
    """

    lineno: int
    module: str
    names: tuple[str, ...] = ()

    def candidates(self) -> list[str]:
        """展开成候选模块路径（包根 + 各具名子路径）。"""
        out = [self.module]
        out.extend(f"{self.module}.{name}" for name in self.names)
        return out

    def named_contract_face(self) -> bool:
        """语句是否显式点名了契约面（如 `from app.services.X import port`）。"""
        return any(name in CONTRACT_STEMS for name in self.names)


def collect_imports(path: Path) -> list[ImportedName]:
    """返回该文件的全部 import 语句（含动态导入）。

    覆盖 `import x` / `from x import y` / `__import__("x")` /
    `importlib.import_module("x")`。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _package_of(path)
    out: list[ImportedName] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(ImportedName(lineno=node.lineno, module=alias.name))
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from(node.module, node.level, package)
            if not resolved:
                continue
            out.append(
                ImportedName(
                    lineno=node.lineno,
                    module=resolved,
                    names=tuple(alias.name for alias in node.names),
                )
            )
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            dynamic = (isinstance(func, ast.Name) and func.id == "__import__") or (
                isinstance(func, ast.Attribute) and func.attr == "import_module"
            )
            if dynamic:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.append(ImportedName(lineno=node.lineno, module=arg.value))
    return out


def collect_import_candidates(path: Path) -> list[tuple[int, str]]:
    """兼容旧签名：返回 [(行号, 被导入模块候选)]（已展平）。"""
    return [
        (item.lineno, candidate)
        for item in collect_imports(path)
        for candidate in item.candidates()
    ]


def _domain_of(path: Path) -> str | None:
    """返回该文件所属域；顶层文件（`app/services/*.py`）返回 None。"""
    rel = path.relative_to(SERVICES_DIR)
    return rel.parts[0] if len(rel.parts) >= 2 else None


def _init_reexports(domain: str) -> bool:
    """目标域 `__init__.py` 是否 re-export 内部符号（决定二级路径是否算内部访问）。"""
    init = SERVICES_DIR / domain / "__init__.py"
    if not init.exists():
        return False
    tree = ast.parse(init.read_text(encoding="utf-8"))
    return any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))


def _python_files() -> list[Path]:
    return sorted(SERVICES_DIR.rglob("*.py"))


def scan() -> list[Violation]:
    """扫描全部 services 域，返回当前违规集（已去重、已排序）。"""
    violations: set[Violation] = set()
    for path in _python_files():
        source_domain = _domain_of(path)
        if source_domain is None:
            continue  # app/services/__init__.py 等顶层文件
        source_rel = path.relative_to(BACKEND_ROOT).as_posix()
        if _module_name(path).split(".")[-1] in CONTRACT_STEMS:
            continue  # 契约面文件自身豁免（其存在意义即转发）
        for item in collect_imports(path):
            # 语句显式点名契约面（`from app.services.X import port`）：
            # 其包根候选 `app.services.X` 不应因 X.__init__ 有 re-export 而被误判。
            exempt_package_root = item.named_contract_face()
            for candidate in item.candidates():
                if not candidate.startswith(f"{SERVICES_PACKAGE}."):
                    continue
                parts = candidate.split(".")
                if len(parts) < 3:
                    continue
                target_domain = parts[2]
                if target_domain == source_domain:
                    continue
                leaf = parts[3] if len(parts) > 3 else None
                if leaf in CONTRACT_STEMS:
                    continue  # 经契约面 ⇒ 合法
                if leaf is None:
                    if exempt_package_root:
                        continue  # 同语句已点名契约面，包根候选豁免
                    if not _init_reexports(target_domain):
                        continue  # 包根引用且无 re-export ⇒ 不含内部依赖
                violations.add(Violation(source=source_rel, target=candidate))
    return sorted(violations)


def diff_against_baseline(
    current: list[Violation], baseline: frozenset[tuple[str, str]]
) -> tuple[list[Violation], list[Violation]]:
    """返回 (新增违规, 已消失的基线项)。

    新增 = current - baseline（须 fail-closed）；
    消失 = baseline - current（基线陈旧，提示可收紧，不 fail）。

    `baseline` 是裸元组集合（便于在基线文件里以纯字面量维护）；
    内部统一转成 `Violation` 再比，避免类型混比造成全量假红。
    """
    current_set = frozenset(v.key() for v in current)
    added = sorted(Violation.from_key(k) for k in current_set - baseline)
    removed = sorted(Violation.from_key(k) for k in baseline - current_set)
    return added, removed
