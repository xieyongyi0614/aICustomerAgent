"""PLAN-001 Step 3 / Step 5.3：Planning 包的静态扫描断言（零越位路径）。

三条断言（Task Detail §8）：

1. `app/services/planning/` 零导入角色优先级资产、零重复实现 `GOAL_TIER` 排序。
2. `app/services/planning/` 零直构 ORM 行对象、零直接写语句触达 `character_goals`。
3. `app/services/planning/` 对 `goal_repository` 的调用名集合 ⊆ §6.1 ∪ §6.2 白名单。

配套「扫描器自测」：用合成源码验证扫描器真的能抓到违规（否则断言退化为空断言）。
"""

from app.services.planning import goal_contract

from . import _plan_scan as scan

PLANNING_MODULES = scan.planning_modules()

DECLARATION_MODULE = scan.PLANNING_PACKAGE_DIR / "goal_contract.py"

ALLOWED_CHARACTER_IMPORT_MODULES = (
    "app.character.asuna.action",
    "app.character.asuna.scene_profiles",
)
"""PLAN-003 / PLAN-004 契约演进：逐一枚举允许的角色资产导入（**均非优先级资产**）。

- `app.character.asuna.scene_profiles`（PLAN-003）：Task Detail §4.1.3 要求
  `PlanContext.scene` 取 `scene_profile_for`。
- `app.character.asuna.action`（PLAN-004）：Task Detail §4.1.1 / §5.6 要求能力 ↔ 工具反查
  复用 `ACTION_TOOL_MAP` / `ACTION_CAPABILITY_MAP`——它们是这两张映射表的**唯一声明处**。

PLAN-001 的 `character_priority_asset_import` 禁令针对**优先级资产**（`asuna/goals.py` 等）；
此处按模块逐条枚举放行，**不得扩成前缀**（改动留痕见 `goal_contract` 模块文档 §9 与
`app/services/planning/decompose.py` 模块文档「契约演进留痕」）。
"""


def _mismatches(check, tokens):
    found = {}
    for path in PLANNING_MODULES:
        hits = check(path, tokens)
        if hits:
            found[str(path.name)] = hits
    return found


def test_package_modules_are_discoverable():
    names = scan.module_names()
    assert "app.services.planning" in names
    assert "app.services.planning.goal_contract" in names
    assert "goal_contract.py" in [path.name for path in PLANNING_MODULES]


def test_step3_no_character_priority_asset_imports():
    offenders = {
        scan.module_name(path): sorted(
            module
            for module in scan.imported_modules(path)
            if (
                module == scan.FORBIDDEN_CHARACTER_IMPORT_PREFIX
                or module.startswith(scan.FORBIDDEN_CHARACTER_IMPORT_PREFIX + ".")
            )
            and module not in ALLOWED_CHARACTER_IMPORT_MODULES
        )
        for path in PLANNING_MODULES
    }
    assert not {name: hits for name, hits in offenders.items() if hits}


def test_step3_character_asset_allowlist_is_explicitly_enumerated():
    """放行面必须逐模块枚举（防「一次放行一个前缀」的隐性扩大）。

    PLAN-003 落地 1 项（场景画像），PLAN-004 落地 1 项（能力 ↔ 工具映射表声明处）：
    扩容由任务显式写入本断言，增量即「范围越界已评审」的证据。
    """
    assert ALLOWED_CHARACTER_IMPORT_MODULES == (
        "app.character.asuna.action",
        "app.character.asuna.scene_profiles",
    )
    assert all(
        module.count(".") >= 2 and not module.endswith("asuna")
        for module in ALLOWED_CHARACTER_IMPORT_MODULES
    )


def test_step3_code_contains_no_tier_or_orm_row_names():
    assert not _mismatches(scan.code_violations, scan.FORBIDDEN_CODE_NAMES)
    assert not _mismatches(scan.code_violations, scan.FORBIDDEN_CODE_FRAGMENTS)


def test_step3_code_has_no_second_priority_algorithm_entry_point():
    assert not _mismatches(scan.code_violations, ("compute_priority",))


def test_step3_orm_imports_are_absent_or_limited_to_session_local():
    offenders = {}
    for path in PLANNING_MODULES:
        imported = scan.import_from_names(path).get("app.core.db", set())
        extra = sorted(imported - {"SessionLocal"})
        if extra:
            offenders[scan.module_name(path)] = extra
    assert not offenders


def test_step3_no_sqlalchemy_write_constructors():
    offenders = {}
    for path in PLANNING_MODULES:
        names = scan.simple_call_names(path) & set(scan.FORBIDDEN_SQLALCHEMY_WRITE_CALLS)
        imported = scan.import_from_names(path).get("sqlalchemy", set())
        if names or imported:
            offenders[scan.module_name(path)] = sorted(names | imported)
    assert not offenders


def test_step3_no_character_table_sql_literals():
    assert not _mismatches(scan.literal_violations, scan.FORBIDDEN_SQL_LITERAL_FRAGMENTS)


def test_step3_goal_repository_call_set_is_within_declared_whitelist():
    allowed = set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS)
    offenders = {
        scan.module_name(path): sorted(scan.goal_repository_call_names(path) - allowed)
        for path in PLANNING_MODULES
        if scan.goal_repository_call_names(path) - allowed
    }
    assert not offenders


def test_step3_whitelist_excludes_goal_mutations_outside_the_contract():
    allowed = set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS)
    for name in ("expire_goal", "cancel_goal", "seed_goals", "create_goal"):
        assert name not in allowed


def test_step5_no_step_ordering_key_by_priority_or_tier():
    offenders = {
        path.name: [
            key
            for key in scan.sort_key_sources(path)
            if any(
                fragment in key for fragment in scan.FORBIDDEN_SORT_KEY_FRAGMENTS
            )
        ]
        for path in PLANNING_MODULES
    }
    assert {name: keys for name, keys in offenders.items() if keys} == {}


def test_step5_declaration_module_has_no_functions_and_no_calls():
    assert scan.function_definitions(DECLARATION_MODULE) == []
    assert scan.call_nodes(DECLARATION_MODULE) == []


def test_i6_priority_algorithm_is_defined_once_repo_wide():
    definitions = [
        path.relative_to(scan.REPO_ROOT).as_posix()
        for path in (scan.REPO_ROOT / "app").rglob("*.py")
        if "def compute_priority" in path.read_text(encoding="utf-8")
    ]
    assert definitions == ["app/services/goal/arbitration.py"]


def test_scanner_flags_synthetic_violations(tmp_path):
    source = (
        "import sqlalchemy\n"
        "from app.core.db import GoalRow\n"
        "from app.repositories import goal_repository\n"
        "from app.character.asuna import goals\n"
        "TIER = GOAL_TIER\n"
        "def route(goal, specs, session):\n"
        "    session.execute(update(GoalRow).values(status='done'))\n"
        "    goal_repository.expire_goal(goal.id)\n"
        "    return sorted(specs, key=lambda spec: goal.priority)\n"
    )
    path = tmp_path / "_synthetic_violation_sample.py"
    path.write_text(source, encoding="utf-8")
    assert scan.imported_modules(path) >= {
        "app.core.db",
        "app.repositories",
        "app.character.asuna",
    }
    assert scan.code_violations(path, scan.FORBIDDEN_CODE_NAMES) == ["GoalRow", "GOAL_TIER"]
    assert scan.code_violations(path, ("session.execute",)) == ["session.execute"]
    assert scan.simple_call_names(path) & set(scan.FORBIDDEN_SQLALCHEMY_WRITE_CALLS) == {
        "update"
    }
    assert scan.goal_repository_call_names(path) == {"expire_goal"}
    assert scan.goal_repository_call_names(path) - set(
        goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS
    ) == {"expire_goal"}
    keys = scan.sort_key_sources(path)
    assert keys == ["lambda spec: goal.priority"]
    assert any(fragment in keys[0] for fragment in scan.FORBIDDEN_SORT_KEY_FRAGMENTS)
    assert scan.function_definitions(path) == ["route"]
    assert scan.call_nodes(path)


def test_scanner_ignores_docstring_and_comment_mentions(tmp_path):
    source = (
        '"""契约声明：禁止直构 GoalRow 与直写 character_goals，禁止按 GOAL_TIER 排序。"""\n'
        "# 注释里的 GoalRow / GOAL_TIER / character_goals 不是违规\n"
        "CONTRACT = 'goal_exhausted'\n"
    )
    path = tmp_path / "_synthetic_docstring_sample.py"
    path.write_text(source, encoding="utf-8")
    assert scan.code_violations(path, scan.FORBIDDEN_CODE_NAMES) == []
    assert scan.literal_violations(path, scan.FORBIDDEN_SQL_LITERAL_FRAGMENTS) == []
    assert scan.string_literals(path) == {"goal_exhausted"}
    assert scan.function_definitions(path) == []
