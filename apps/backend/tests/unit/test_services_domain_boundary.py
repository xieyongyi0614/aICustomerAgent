"""services 域间边界守卫（T-32，常驻 Fast Test）。

规则来源：`apps/backend/AGENTS.md`「services 域间边界」（T-10 立规，2026-10-09）——
`services/<domain>` 不得直接 import 另一个域的内部模块，只能经契约面
（`port.py` / `contracts.py` / `engine_port.py`）访问。

**策略：渐进式**。仓库现状有 237 条既有跨域内部依赖（60 个域对），一次清零风险过高。
故把现状冻结进 `tests/support/domain_boundary_baseline.py`，本守卫只对**新增**违规
fail-closed —— 新增跨域内部依赖必须显式改走契约面，或（不推荐）走评审后手工登记基线。

扫描实现见 `tests/support/domain_boundary.py`（AST，非正则；不 import 被测模块）。
"""

import pytest

from tests.support.domain_boundary import (
    BACKEND_ROOT,
    SERVICES_DIR,
    Violation,
    collect_imports,
    diff_against_baseline,
    scan,
)
from tests.support.domain_boundary_baseline import BASELINE_VIOLATIONS

#: 域对聚合时的目标域下标（`app.services.<domain>`）。
_DOMAIN_INDEX = 2


def test_services_dir_resolves_independent_of_cwd():
    """扫描根由 `__file__` 锚定，不依赖 CWD（优于 `Path('app')` 的写法）。"""
    assert SERVICES_DIR.is_dir(), SERVICES_DIR
    assert (BACKEND_ROOT / "app" / "services").is_dir()
    assert SERVICES_DIR.name == "services"


def test_no_new_cross_domain_internal_imports():
    """核心断言：当前违规集不得超出基线（fail-closed）。"""
    current = scan()
    added, _removed = diff_against_baseline(current, BASELINE_VIOLATIONS)
    if not added:
        return

    lines = "\n".join(f"  + {v.render()}" for v in added)
    raise AssertionError(
        f"\n{'=' * 72}\n"
        f"[域间边界违规] 新增 {len(added)} 处跨域内部依赖\n"
        f"{lines}\n"
        f"{'-' * 72}\n"
        f"规则（AGENTS.md / T-10）：services/<domain> 不得直接 import 另一域内部模块，\n"
        f"只能经该域契约面（port.py / contracts.py / engine_port.py）。\n"
        f"修法：\n"
        f"  1) 目标域已有契约面 → 改为 `from app.services.<target> import port` 后经它调用；\n"
        f"  2) 确需新面 → 在目标域新增 port.py / contracts.py，而非直连内部模块；\n"
        f"  3) ⚠️ 不要为了变绿把新增项塞进 BASELINE_VIOLATIONS。\n"
        f"基线文件：tests/support/domain_boundary_baseline.py\n"
        f"{'=' * 72}"
    )


def test_baseline_entries_still_exist_or_report_stale():
    """基线中的条目若已被修好，提示可以删除该条（保持基线收紧）。"""
    current = scan()
    _added, removed = diff_against_baseline(current, BASELINE_VIOLATIONS)
    if not removed:
        return

    lines = "\n".join(f"  - {v.render()}" for v in removed)
    raise AssertionError(
        f"\n{'=' * 72}\n"
        f"[基线陈旧] 有 {len(removed)} 条基线违规已不复存在\n"
        f"{lines}\n"
        f"{'-' * 72}\n"
        f"这是**好事**（跨域依赖被收敛了），但基线需要同步收紧：\n"
        f"请从 tests/support/domain_boundary_baseline.py 删除上述条目，\n"
        f"以免它们掩盖未来重新引入的同类依赖。\n"
        f"{'=' * 72}"
    )


def test_violation_records_are_deduplicated():
    """同一 (文件, 目标模块) 只记一条 —— key 不含行号。"""
    current = scan()
    keys = [v.key() for v in current]
    assert len(keys) == len(set(keys))


def test_contract_faces_are_not_flagged():
    """契约面（port/contracts/engine_port）文件自身及经其导入的路径不计违规。"""
    current = scan()
    for violation in current:
        leaf = violation.target.split(".")[-1]
        assert leaf not in {"port", "contracts", "engine_port"}, violation.render()
        assert not violation.source.endswith(("port.py", "contracts.py", "engine_port.py")), (
            violation.render()
        )


def test_reexport_bypass_is_detected():
    """__init__.py re-export 绕行与直连子模块同罪（T-32 决策）。

    `ledger` 的 `__init__.py` 有 re-export ⇒ `from app.services.ledger import record_entry`
    实际取到内部符号，须计入。断言基线里确实出现了这种「二级路径」条目。
    """
    two_level = {
        v.target
        for v in scan()
        if len(v.target.split(".")) == 3 and v.target.split(".")[2] not in {"port", "contracts", "engine_port"}
    }
    assert two_level, "预期基线中存在经 __init__ re-export 的二级路径违规"


# --- 负向测试：证明扫描器真的会 fail-closed --------------------------------


def _scan_fixture_tree(tmp_path, files: dict[str, str]) -> list[Violation]:
    """在临时目录里复刻最小 services 树并跑扫描逻辑（不依赖真实仓库）。

    与 `domain_boundary.scan()` 同逻辑，但根目录指向 `tmp_path`；
    用于负向测试（证明扫描器真的会 fail-closed）。
    """
    services = tmp_path / "app" / "services"
    for rel, content in files.items():
        target = services / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    contract_stems = {"port", "contracts", "engine_port"}
    violations: set[tuple[str, str]] = set()
    for path in sorted(services.rglob("*.py")):
        rel_parts = path.relative_to(services).parts
        if len(rel_parts) < 2:
            continue
        source_domain = rel_parts[0]
        source_rel = path.relative_to(tmp_path).as_posix()
        if path.stem in contract_stems:
            continue
        for item in collect_imports(path):
            exempt_package_root = item.named_contract_face()
            for candidate in item.candidates():
                if not candidate.startswith("app.services."):
                    continue
                parts = candidate.split(".")
                if len(parts) < 3:
                    continue
                target_domain = parts[_DOMAIN_INDEX]
                if target_domain == source_domain:
                    continue
                leaf = parts[3] if len(parts) > 3 else None
                if leaf in contract_stems:
                    continue
                if leaf is None:
                    if exempt_package_root:
                        continue
                    init = services / target_domain / "__init__.py"
                    has_reexport = init.exists() and any(
                        line.startswith(("from ", "import "))
                        for line in init.read_text(encoding="utf-8").splitlines()
                    )
                    if not has_reexport:
                        continue
                violations.add((source_rel, candidate))
    return sorted(Violation.from_key(k) for k in violations)


def test_negative_scanner_flags_direct_submodule_import(tmp_path):
    """`from app.services.tool import registry` ⇒ 违规。"""
    results = _scan_fixture_tree(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "beta/__init__.py": "",
            "alpha/consumer.py": "from app.services.beta import registry\n",
        },
    )
    assert any(v.target == "app.services.beta.registry" for v in results), results


def test_negative_scanner_flags_reexport_bypass(tmp_path):
    """目标域 __init__ 有 re-export 时，二级路径也算违规。"""
    results = _scan_fixture_tree(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "beta/__init__.py": "from app.services.beta.service import record_entry\n",
            "alpha/consumer.py": "from app.services.beta import record_entry\n",
        },
    )
    assert any(v.target == "app.services.beta.record_entry" for v in results), results


def test_negative_scanner_allows_same_domain_import(tmp_path):
    """同域内部 import 不受限。"""
    results = _scan_fixture_tree(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "alpha/consumer.py": "from app.services.alpha import helper\n",
        },
    )
    assert results == []


def test_negative_scanner_allows_contract_face(tmp_path):
    """经 port.py / contracts.py 跨域 ⇒ 合法。"""
    results = _scan_fixture_tree(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "beta/__init__.py": "from app.services.beta.service import record_entry\n",
            "beta/port.py": "",
            "alpha/consumer.py": "from app.services.beta import port\n",
        },
    )
    assert results == [], results


def test_negative_scanner_allows_empty_init_package_reference(tmp_path):
    """目标域 __init__ 为空时，包根引用不构成内部依赖。"""
    results = _scan_fixture_tree(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "beta/__init__.py": "",
            "alpha/consumer.py": "from app.services import beta\n",
        },
    )
    assert results == [], results


@pytest.mark.parametrize("source_line", [
    '__import__("app.services.beta.registry")',
    'import importlib\nimportlib.import_module("app.services.beta.registry")',
])
def test_negative_scanner_flags_dynamic_import(tmp_path, source_line):
    """动态导入（`__import__` / `importlib.import_module`）同样被检出。"""
    results = _scan_fixture_tree(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "beta/__init__.py": "",
            "alpha/consumer.py": f"{source_line}\n",
        },
    )
    assert any(v.target == "app.services.beta.registry" for v in results), results
