"""V2.4.0 受限 DSL（architecture.md §10.3 / TOOL-011 §2.2、§4.4）。

自定义工具只能用**数据**组合既有 Capability 动作：声明形如
`[{capability, action, params_map}]`——没有表达式求值、没有控制流、没有 IO 原语。
这是安全红线，不是能力限制：

| 允许 | 禁止 |
|---|---|
| 组合白名单内的既有动作 | 条件分支 / 循环（复杂度与可审计性） |
| 参数映射（`{params.x}` 占位）与字面量默认值 | HTTP 直连 / 文件系统访问 / 任意代码（红线） |
| — | 读取记忆内容（本版本，隐私面 Q3 待裁决） |

白名单 = V9 六个内置能力的动作。`channel_feishu`（外发）与 `external_api`（声明驱动 HTTP）
**不在白名单内**：用户自定义工具不能把外发通道或外部 HTTP 再包一层，否则等价于绕过
§9.5 的凭据与域名白名单机制。`steps` 上限 3 步（§2.2）。

`side_effects` 只由步骤并集**推导**（`derive_side_effects`），声明值不参与判定——
"声明只读、实际写"不可能成立（E11）。

纪律：本模块**没有任何执行能力**，不 import 网络 / 文件 / 进程 / 动态导入相关模块，
也不存在 `eval` / `exec` / `open` 调用点；纯函数、零 IO。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.models.tool import TOOL_SIDE_EFFECT_KINDS

MAX_STEPS = 3

STEP_KEYS: frozenset[str] = frozenset({"capability", "action", "params_map"})

PARAMS_MAP_KEY = "params_map"

PARAM_PLACEHOLDER_PATTERN = re.compile(r"^\{params\.([a-z][a-z0-9_]*)\}$")

PARAM_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: (capability, action) 白名单：既有 Capability 的动作，无外发、无外部 HTTP。
ALLOWED_ACTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("reminder", "create"),
        ("reminder", "cancel"),
        ("memory", "save"),
        ("world_action", "create"),
        ("world_action", "move"),
        ("world_action", "use"),
        ("environment_query", "query"),
        ("search", "query"),
        ("notification", "send"),
    }
)

#: 步骤 → 副作用并集（推导权威，声明值不参与判定）。
ACTION_SIDE_EFFECTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("reminder", "create"): ("write_world",),
    ("reminder", "cancel"): ("write_world",),
    ("memory", "save"): ("write_memory",),
    ("world_action", "create"): ("write_world",),
    ("world_action", "move"): ("write_world",),
    ("world_action", "use"): ("write_world",),
    ("environment_query", "query"): ("read",),
    ("search", "query"): ("read",),
    ("notification", "send"): ("send_external",),
}

#: 禁止出现的能力名（红线显式点名，便于给出可读错误）。
FORBIDDEN_CAPABILITY_NAMES: frozenset[str] = frozenset(
    {
        "bash",
        "builtins",
        "code",
        "ctypes",
        "exec",
        "eval",
        "file",
        "filesystem",
        "fs",
        "http",
        "http_client",
        "https",
        "import",
        "importlib",
        "os",
        "pathlib",
        "pickle",
        "process",
        "python",
        "requests",
        "shell",
        "shutil",
        "socket",
        "subprocess",
        "sys",
        "tempfile",
        "urllib",
    }
)

FORBIDDEN_ACTION_NAMES: frozenset[str] = frozenset(
    {
        "compile",
        "download",
        "eval",
        "exec",
        "execute",
        "import",
        "open",
        "popen",
        "read_file",
        "request",
        "run",
        "shell",
        "spawn",
        "system",
        "upload",
        "write_file",
    }
)

#: 参数值里的红线特征（出现即拒；值本身不会被求值，此处只做卫生扫描）。
FORBIDDEN_VALUE_TOKENS: tuple[str, ...] = (
    "http://",
    "https://",
    "file://",
    "ftp://",
    "ws://",
    "wss://",
    "__import__",
    "subprocess",
    "os.system",
    "eval(",
    "exec(",
    "open(",
    "import ",
)

RED_LINE_LABEL = "安全红线"


def allowed_actions() -> frozenset[tuple[str, str]]:
    return ALLOWED_ACTIONS


def _forbidden_step_keys(keys: set[str]) -> list[str]:
    return sorted(key for key in keys if key not in STEP_KEYS)


def _validate_params_map(index: int, params_map: Any) -> list[str]:
    if params_map is None:
        return []
    if not isinstance(params_map, Mapping):
        return [f"steps[{index}].{PARAMS_MAP_KEY} 必须是键值映射"]
    errors: list[str] = []
    for key, value in params_map.items():
        name = str(key)
        if not PARAM_NAME_PATTERN.fullmatch(name):
            errors.append(f"steps[{index}].{PARAMS_MAP_KEY} 键名非法: {name}")
        if isinstance(value, bool) or isinstance(value, (int, float)):
            continue
        if value is None:
            continue
        if not isinstance(value, str):
            errors.append(
                f"steps[{index}].{PARAMS_MAP_KEY}.{name} 只允许字面量或 "
                "{params.<name>} 占位符（无表达式求值）"
            )
            continue
        hits = [token for token in FORBIDDEN_VALUE_TOKENS if token in value]
        if hits:
            errors.append(
                f"steps[{index}].{PARAMS_MAP_KEY}.{name} 含{RED_LINE_LABEL}特征: "
                f"{', '.join(hits)}"
            )
            continue
        if PARAM_PLACEHOLDER_PATTERN.fullmatch(value):
            continue
        if "{" in value or "}" in value:
            errors.append(
                f"steps[{index}].{PARAMS_MAP_KEY}.{name} 占位符非法（仅支持 "
                "{params.<name>}）: {value}"
            )
            continue
    return errors


def _validate_step(index: int, step: Any) -> list[str]:
    if not isinstance(step, Mapping):
        return [f"steps[{index}] 必须是键值映射"]
    keys = {str(key) for key in step}
    errors: list[str] = []
    forbidden = _forbidden_step_keys(keys)
    if forbidden:
        errors.append(
            f"steps[{index}] 含未允许字段（{RED_LINE_LABEL}：不得携带可执行载荷）: "
            f"{', '.join(forbidden)}"
        )
    capability = str(step.get("capability", "") or "").strip()
    action = str(step.get("action", "") or "").strip()
    if not capability or not action:
        errors.append(f"steps[{index}] 缺少 capability 或 action")
    elif capability in FORBIDDEN_CAPABILITY_NAMES or action in FORBIDDEN_ACTION_NAMES:
        errors.append(
            f"steps[{index}] 命中禁止能力（{RED_LINE_LABEL}）: ({capability}, {action})"
        )
    elif (capability, action) not in ALLOWED_ACTIONS:
        errors.append(
            f"steps[{index}] 动作不在白名单内: ({capability}, {action})；"
            f"合法动作: {', '.join(f'{c}.{a}' for c, a in sorted(ALLOWED_ACTIONS))}"
        )
    errors.extend(_validate_params_map(index, step.get(PARAMS_MAP_KEY)))
    return errors


def validate_steps(steps: Any) -> list[str]:
    """步骤校验（返回错误列表，空列表表示通过）；纯函数、零 IO。"""
    if not isinstance(steps, (list, tuple)) or not steps:
        return ["steps 必须是非空列表"]
    if len(steps) > MAX_STEPS:
        return [f"steps 数量 {len(steps)} 超出上限 {MAX_STEPS}"]
    errors: list[str] = []
    for index, step in enumerate(steps):
        errors.extend(_validate_step(index, step))
    return errors


def derive_side_effects(steps: Any) -> tuple[str, ...]:
    """副作用并集推导（唯一权威）：声明值不参与，"只读声明 + 写步骤"不可能成立。"""
    derived: set[str] = set()
    if isinstance(steps, (list, tuple)):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            key = (
                str(step.get("capability", "") or "").strip(),
                str(step.get("action", "") or "").strip(),
            )
            derived.update(ACTION_SIDE_EFFECTS.get(key, ()))
    return tuple(kind for kind in TOOL_SIDE_EFFECT_KINDS if kind in derived)


def required_params(steps: Any) -> tuple[str, ...]:
    """步骤占位符引用的参数名（去重、保序）：自定义工具对外参数的下限。"""
    names: list[str] = []
    if not isinstance(steps, (list, tuple)):
        return ()
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        params_map = step.get(PARAMS_MAP_KEY)
        if not isinstance(params_map, Mapping):
            continue
        for value in params_map.values():
            if not isinstance(value, str):
                continue
            match = PARAM_PLACEHOLDER_PATTERN.fullmatch(value)
            if match is None:
                continue
            name = match.group(1)
            if name not in names:
                names.append(name)
    return tuple(names)


def render_params_map(
    params_map: Mapping[str, Any] | None, params: Mapping[str, Any]
) -> dict[str, Any]:
    """参数映射渲染：占位符取调用参数，字面量原样；缺参渲染为空串（不抛错）。"""
    rendered: dict[str, Any] = {}
    for key, value in (params_map or {}).items():
        name = str(key)
        if isinstance(value, str):
            match = PARAM_PLACEHOLDER_PATTERN.fullmatch(value)
            if match is not None:
                resolved = params.get(match.group(1))
                if resolved is None:
                    rendered[name] = ""
                elif isinstance(resolved, bool):
                    rendered[name] = "true" if resolved else "false"
                else:
                    rendered[name] = str(resolved)
                continue
        rendered[name] = value
    return rendered


class ToolDSL:
    """受限 DSL 门面（§4.4）：动作白名单 + 步骤校验 + 副作用推导。"""

    def allowed_actions(self) -> frozenset[tuple[str, str]]:
        return ALLOWED_ACTIONS

    def validate_steps(self, steps: Any) -> list[str]:
        return validate_steps(steps)

    def derive_side_effects(self, steps: Any) -> tuple[str, ...]:
        return derive_side_effects(steps)


_default_dsl: ToolDSL | None = None


def get_tool_dsl() -> ToolDSL:
    global _default_dsl
    if _default_dsl is None:
        _default_dsl = ToolDSL()
    return _default_dsl
