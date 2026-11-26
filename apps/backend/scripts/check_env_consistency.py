"""离线校验 `.env` / `.env.example` 与 `Settings` 字段的一致性。

**背景**：启动期 `unknown_versioned_env_keys()` 守卫已于 2026-09-28 删除，
叠加 `BaseSettings(extra="ignore")`（`core/settings/_shared.py`） →
部署侧写错的 env 键**完全静默**：既不影响启动，也不产生告警。
本脚本把这项检查降级为**按需离线检查**（不进启动路径，不重新引入启动耦合）。

检查三项（任一不合即非 0 退出）：

1. **死键**（`.env` 里有、`Settings` 无对应字段）—— 写了不生效，最危险的一类；
2. **缺失键**（`Settings` 有字段、`.env.example` 未列出）—— 模板不全，新同学不知道要配；
3. **大小写不符**（键非「字段名大写」形态）—— 无 alias 层，大小写错即等价死键。

用法：
    uv run python -m scripts.check_env_consistency
    uv run python -m scripts.check_env_consistency --env apps/backend/.env
    uv run python -m scripts.check_env_consistency --strict   # 有缺失键也非 0 退出

说明：`.env` 的**死键**视为错误；`.env.example` 的**缺失键**默认只警告
（模板与实现天然有滞后），加 `--strict` 才强制。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.settings import Settings

_VALID_KEYS: frozenset[str] = frozenset(
    name.upper() for name in Settings.model_fields
)

_LIST_LIMIT = 30


def _parse_keys(path: Path) -> dict[str, int]:
    """读 env 文件的键 → 行号（忽略注释、空行、无 `=` 的行）。"""
    keys: dict[str, int] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return keys
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys[key] = lineno
    return keys


def _report(title: str, items: list[tuple[str, int]], hint: str) -> bool:
    if not items:
        return True
    print(f"\n[{title}] {len(items)} 项")
    for key, lineno in sorted(items)[:_LIST_LIMIT]:
        print(f"  {key}  (第 {lineno} 行)")
    if len(items) > _LIST_LIMIT:
        print(f"  … 其余 {len(items) - _LIST_LIMIT} 项省略（用 --all 展开）")
    print(f"  → {hint}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="待检查的 .env 路径（默认 .env）")
    parser.add_argument(
        "--example", default=".env.example", help="模板路径（默认 .env.example）"
    )
    parser.add_argument(
        "--strict", action="store_true", help="模板缺失键也视为错误（非 0 退出）"
    )
    parser.add_argument(
        "--all", action="store_true", help="完整列出所有项（默认每类最多 30 项）"
    )
    args = parser.parse_args()

    global _LIST_LIMIT
    if args.all:
        _LIST_LIMIT = 10**9

    env_path = Path(args.env)
    example_path = Path(args.example)

    env_keys = _parse_keys(env_path)
    example_keys = _parse_keys(example_path)

    print(f"Settings 字段：{len(_VALID_KEYS)}")
    print(f"{env_path}：{len(env_keys)} 键")
    print(f"{example_path}：{len(example_keys)} 键")

    if not env_keys and not example_keys:
        print("\n未找到任何 env 文件，跳过检查。")
        return 0

    dead: list[tuple[str, int]] = []
    miscased: list[tuple[str, int]] = []
    for key, lineno in env_keys.items():
        if key in _VALID_KEYS:
            continue
        if key.upper() in _VALID_KEYS:
            miscased.append((key, lineno))
        else:
            dead.append((key, lineno))

    missing_example = [
        (key, 0) for key in sorted(_VALID_KEYS) if key not in example_keys
    ]

    dead_ok = _report(
        "死键（.env 有、Settings 无字段 → 写了不生效）",
        dead,
        "删除这些键，或确认字段名（无 alias 层，env 名 = 字段名大写）",
    )
    miscased_ok = _report(
        "大小写不符（等价死键）",
        miscased,
        "改为全大写（env 名 = 字段名大写）",
    )
    example_ok = _report(
        "模板缺失（Settings 有、.env.example 未列出）",
        missing_example,
        "补进 .env.example，或确认该字段无需在模板中暴露",
    )

    if dead_ok and miscased_ok:
        print("\n.env 无死键。")
    if example_ok:
        print(".env.example 已覆盖全部字段。")

    ok = dead_ok and miscased_ok and (example_ok or not args.strict)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
