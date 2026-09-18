"""settings 字段名与开关标记的一致性守卫。

两条纪律的自动化形式：

1. 环境变量名 = 字段名大写（`_shared.py` 无 `env_prefix` / alias 层）。字段改名后
   旧 env 名会被 `extra="ignore"` 静默吞掉——用例照常通过、闸门却没开。故测试侧任何
   `setenv` 字面量都必须对应真实字段，否则立刻失败而非假通过。
2. `RESERVED_*_SUB_FLAGS` 的语义是「开启不产生行为变化」。一旦某个 RESERVED 开关
   被接进门控分支，标记即失准，须先修正标记再谈删除。
"""

import re
from pathlib import Path

from app.core.settings import Settings, unknown_versioned_env_keys
from app.core.settings.action_execution import RESERVED_V26_SUB_FLAGS
from app.core.settings.world_simulation import RESERVED_V23_SUB_FLAGS

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = BACKEND_ROOT / "tests"
APP_ROOT = BACKEND_ROOT / "app"

SETENV_LITERAL = re.compile(r'setenv\(\s*"([A-Z][A-Z0-9_]*)"')
RESERVED_FLAGS = (*RESERVED_V23_SUB_FLAGS, *RESERVED_V26_SUB_FLAGS)


def _known_env_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def _gate_sites(flag: str) -> list[str]:
    """`app/` 中真正把 flag 当条件读的位置。

    排除调试快照名列表这类非门控提及——它们不产生行为分支。
    """
    sites: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "core/settings" in path.as_posix():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if flag not in line:
                continue
            if re.match(r"^\s*(if|elif)\b", line) or "getattr(" in line:
                sites.append(f"{path.relative_to(BACKEND_ROOT).as_posix()}:{lineno}")
    return sites


class TestEnvKeyGuard:
    def test_setenv_literals_reference_real_fields(self):
        known = _known_env_keys()
        unknown = [
            f"{path.relative_to(BACKEND_ROOT).as_posix()}:{lineno} -> {name}"
            for path in sorted(TESTS_ROOT.rglob("*.py"))
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            )
            for name in SETENV_LITERAL.findall(line)
            if name not in known
        ]
        assert unknown == [], (
            "setenv 字面量不对应任何 settings 字段（字段是否已改名？）：\n"
            + "\n".join(unknown)
        )

    def test_unknown_versioned_env_keys_reports_ghost(self):
        environ = {
            "V99_GHOST_ENABLED": "true",
            "V2_MEMORY_ENABLED": "true",
            "PATH": "/usr/bin",
        }
        assert unknown_versioned_env_keys(environ) == ["V99_GHOST_ENABLED"]

    def test_unknown_versioned_env_keys_ignores_non_versioned(self):
        assert unknown_versioned_env_keys({"SOME_OTHER_SETTING": "1"}) == []


class TestReservedFlagMarker:
    def test_reserved_flags_have_no_gate_sites(self):
        offenders = {flag: _gate_sites(flag) for flag in RESERVED_FLAGS}
        offenders = {flag: sites for flag, sites in offenders.items() if sites}
        assert offenders == {}, (
            "以下开关标记为 RESERVED（开启不产生行为变化），但已接进门控分支，"
            f"标记失准须先修正：{offenders}"
        )

    def test_scene_expansion_is_wired_and_not_reserved(self):
        assert "v23_scene_expansion_enabled" not in RESERVED_V23_SUB_FLAGS
        assert _gate_sites("v23_scene_expansion_enabled")
