"""settings 字段名与 env 键的一致性守卫。

环境变量名 = 字段名大写（`_shared.py` 无 `env_prefix` / alias 层）。字段改名后
旧 env 名会被 `extra="ignore"` 静默吞掉——用例照常通过、闸门却没开。故测试侧任何
`setenv` 字面量都必须对应真实字段，否则立刻失败而非假通过。
"""

import re
from pathlib import Path

from app.core.settings import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = BACKEND_ROOT / "tests"

SETENV_LITERAL = re.compile(r'setenv\(\s*"([A-Z][A-Z0-9_]*)"')


def _known_env_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


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
