"""V2.4.0 自定义工具注册（architecture.md §10.3 / TOOL-011 §2.2、§2.3、§4.3）。

自定义工具是**受限 DSL 的组合体**：声明 `steps` 只能引用白名单内的既有动作（`dsl.py`），
注册后落地为一个 `ToolDefinition` + 一个**只跑这组步骤**的能力实现，因此仍走统一执行器
（权限闸 / 校验 / 超时 / 异常归一全部生效，无旁路）。

四条强制纪律（声明无法覆盖）：

| 纪律 | 落点 |
|---|---|
| 注册面常开 | 原 `tool_system_enabled` + `tool_user_defined_enabled` 双闸已随 V2.4.0 转正删除；注册只受下述三条纪律与 DSL 白名单约束 |
| 强制 `level=dangerous` | 声明等级被忽略；`dangerous` 由模型校验器连带置 `audit=True` |
| 强制不沉淀记忆 | `memory_policy_key` 恒等于 tool_id（`user.` 前缀 → TOOL-008 硬纪律不沉淀） |
| `side_effects` 由步骤并集推导 | `dsl.derive_side_effects` 为唯一权威，声明值不参与判定（E11） |

失败语义：**拒绝且不留痕**——校验全通过后才写注册表；写入过程任一异常回滚已完成的部分。
注册是**进程内存态**（§3 反模式警示：不建表），重启即丢失，需由注册请求重建（E13）。

执行体只组合既有 `CapabilityExecutor` 调用既有能力，**不 import 任何网络 / 文件 / 进程模块**，
也不存在 `eval` / `exec` / `open` 调用点。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.settings import get_settings
from app.models.action import ActionSchema, ActionStep, CapabilityResult
from app.models.tool import (
    TOOL_DESCRIPTION_MAX_LENGTH,
    TOOL_NAME_MAX_LENGTH,
    TOOL_WHEN_MAX_LENGTH,
    PermissionProfile,
    ToolDefinition,
    ToolParameter,
    ToolSchema,
)
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import (
    CapabilityRegistry,
    ExecutionContext,
    get_capability_registry,
)
from app.services.tool.dsl import (
    PARAMS_MAP_KEY,
    RED_LINE_LABEL,
    derive_side_effects,
    render_params_map,
    required_params,
)
from app.services.tool.dsl import validate_steps as dsl_validate_steps
from app.services.tool.registry import TOOL_ID_PATTERN, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

USER_NAMESPACE = "user"

USER_TOOL_ID_PREFIX = "user."

USER_TOOL_ACTION = "run"

USER_TOOL_CONFIRM = "first_time"

USER_TOOL_SCOPE: tuple[str, ...] = ("self",)

FORCED_LEVEL = "dangerous"

DEFAULT_STEP_TIMEOUT_SECONDS = 10.0

ALLOWED_DECLARATION_KEYS: frozenset[str] = frozenset(
    {
        "tool_id",
        "name",
        "description",
        "when_to_use",
        "when_not_to_use",
        "steps",
        "input_schema",
        "side_effects",
        "tags",
    }
)

PARAMETER_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"name", "type", "required", "description", "max_length", "enum", "format", "default"}
)

AGGREGATE_PAYLOAD_KEYS: tuple[str, ...] = (
    "world_event_id",
    "memory_id",
    "note_id",
    "external_sent",
    "external_message_id",
)

RETRYABLE_FAILURE_KINDS: tuple[str, ...] = ("transient", "timeout")

_STATUS_FAILURE_KINDS: dict[str, str] = {
    "timeout": "timeout",
    "unavailable": "unavailable",
    "failed": "transient",
}


class UserToolRejected(ValueError):
    """注册被拒（不留痕）：承载逐条错误，供端点与调用方原样回报。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("自定义工具注册被拒绝: " + "；".join(self.errors))


@dataclass(frozen=True)
class ValidationReport:
    """`validate` 产出（§4.3）：错误列表 + 推导出的副作用与步骤。"""

    passed: bool
    errors: list[str] = field(default_factory=list)
    tool_id: str | None = None
    side_effects: tuple[str, ...] = ()
    steps: tuple[dict[str, Any], ...] = ()
    declared_side_effects: tuple[str, ...] = ()
    parameters: tuple[ToolParameter, ...] = ()
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": list(self.errors),
            "tool_id": self.tool_id,
            "side_effects": list(self.side_effects),
            "declared_side_effects": list(self.declared_side_effects),
        }


def _plain_text(declaration: Mapping[str, Any], key: str) -> str:
    value = declaration.get(key)
    return value.strip() if isinstance(value, str) else ""


def _text(
    declaration: Mapping[str, Any], key: str, errors: list[str], *, required: bool
) -> str:
    value = declaration.get(key)
    if value is None:
        if required:
            errors.append(f"缺少必需字段: {key}")
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        errors.append(f"{key} 必须是非空字符串")
        return ""
    return value.strip()


def _check_budget(key: str, value: str, limit: int, errors: list[str]) -> None:
    if value and len(value) > limit:
        errors.append(f"{key} 长度 {len(value)} 超出上限 {limit}")


def _parse_parameters(
    declaration: Mapping[str, Any], errors: list[str]
) -> tuple[ToolParameter, ...]:
    schema = declaration.get("input_schema")
    if schema is None:
        return ()
    if not isinstance(schema, Mapping):
        errors.append("input_schema 必须是键值映射")
        return ()
    value = schema.get("parameters")
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        errors.append("input_schema.parameters 必须是列表")
        return ()
    parameters: list[ToolParameter] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            errors.append("input_schema.parameters[] 必须是键值映射")
            continue
        unknown = sorted({str(key) for key in item} - PARAMETER_ALLOWED_KEYS)
        if unknown:
            errors.append(
                f"input_schema.parameters[] 含未允许字段（{RED_LINE_LABEL}）: "
                f"{', '.join(unknown)}"
            )
            continue
        name = str(item.get("name", "") or "").strip()
        if not name:
            errors.append("input_schema.parameters[].name 不得为空")
            continue
        if name in seen:
            errors.append(f"参数重复声明: {name}")
            continue
        seen.add(name)
        enum_value = item.get("enum") or ()
        if enum_value and not isinstance(enum_value, (list, tuple)):
            errors.append(f"参数 {name} 的 enum 必须是列表")
            continue
        try:
            parameters.append(
                ToolParameter(
                    name=name,
                    type=str(item.get("type", "string") or "string"),
                    required=bool(item.get("required", False)),
                    description=str(item.get("description", "") or ""),
                    enum=tuple(enum_value),
                    default=item.get("default"),
                    max_length=item.get("max_length"),
                    format=str(item.get("format", "") or ""),
                )
            )
        except Exception as error:
            errors.append(f"参数 {name} 声明非法: {error.__class__.__name__}")
    return tuple(parameters)


def _derive_parameters(
    parameters: tuple[ToolParameter, ...], steps: tuple[dict[str, Any], ...], errors: list[str]
) -> tuple[ToolParameter, ...]:
    """对外参数声明：以声明为准，步骤占位符必须被声明覆盖；未声明则由占位符推导。"""
    placeholders = required_params(steps)
    if not parameters:
        return tuple(
            ToolParameter(name=name, type="string", required=True) for name in placeholders
        )
    declared = {parameter.name for parameter in parameters}
    missing = [name for name in placeholders if name not in declared]
    if missing:
        errors.append(
            "步骤引用了未在 input_schema 声明的参数: "
            + ", ".join(missing)
            + "（strict 校验会拒绝该参数）"
        )
    return parameters


def _tags(declaration: Mapping[str, Any], errors: list[str]) -> tuple[str, ...]:
    value = declaration.get("tags")
    if value is None:
        return ("user_defined",)
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        errors.append("tags 必须是字符串或字符串列表")
        return ("user_defined",)
    return tuple(str(item) for item in value) or ("user_defined",)


def _declared_side_effects(declaration: Mapping[str, Any], errors: list[str]) -> tuple[str, ...]:
    """声明值只用于**回报差异**（推导覆盖声明），不参与判定。"""
    value = declaration.get("side_effects")
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        errors.append("side_effects 必须是列表")
        return ()
    return tuple(str(item) for item in value)


class UserToolCapability:
    """自定义工具的执行体：顺序跑本工具的步骤，逐步经既有 `CapabilityExecutor`。

    - 能力名 = `tool_id`：`(capability, action)` 在统一执行器内唯一可解析（无旁路、无猜测）。
    - 第一步失败即短路返回，不做后续步骤（与 V9 计划语义一致）。
    - 子步骤的既有 payload 键（world_event_id / memory_id / note_id / external_sent）聚合到
      顶层，使归一层仍能产出 `effects` 与 observations。
    """

    def __init__(
        self,
        tool_id: str,
        name: str,
        steps: tuple[dict[str, Any], ...],
        required: tuple[str, ...],
        *,
        settings: Any = None,
        executor: CapabilityExecutor | None = None,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self.name = tool_id
        self.description = f"用户自定义工具：{name}"
        self.actions = {USER_TOOL_ACTION: ActionSchema(required=list(required))}
        self._tool_id = tool_id
        self._steps = tuple(dict(step) for step in steps)
        self._settings = settings
        self._executor = executor
        self._capability_registry = capability_registry

    def validate(self, action: str, params: dict) -> list[str]:
        if action != USER_TOOL_ACTION:
            return [f"未知动作: {action}"]
        return self.actions[USER_TOOL_ACTION].validate(params)

    async def execute(
        self, action: str, params: dict, ctx: ExecutionContext
    ) -> CapabilityResult:
        settings = self._settings if self._settings is not None else getattr(ctx, "settings", None)
        if action != USER_TOOL_ACTION:
            return self._failure("failed", "permanent", f"未知动作: {action}", [])
        results: list[dict[str, Any]] = []
        for index, step in enumerate(self._steps):
            step_params = render_params_map(step.get(PARAMS_MAP_KEY), params)
            raw = await self._capability_executor(settings).run(
                ActionStep(
                    index=index,
                    capability=str(step.get("capability", "")),
                    action=str(step.get("action", "")),
                    params=step_params,
                ),
                ctx,
            )
            results.append(
                {
                    "index": index,
                    "capability": str(step.get("capability", "")),
                    "action": str(step.get("action", "")),
                    "status": raw.status,
                    "payload": dict(raw.payload) if isinstance(raw.payload, dict) else {},
                    "error": raw.error,
                }
            )
            if raw.status != "succeeded":
                kind = self._failure_kind(raw)
                return self._failure(
                    "timeout" if kind == "timeout" else "failed",
                    kind,
                    raw.error or "步骤执行失败",
                    results,
                )
        return self._success(results)

    def _capability_executor(self, settings: Any) -> CapabilityExecutor:
        if self._executor is not None:
            return self._executor
        resolved = settings if settings is not None else get_settings()
        timeout = float(
            getattr(resolved, "action_execution_timeout_seconds", DEFAULT_STEP_TIMEOUT_SECONDS)
            or DEFAULT_STEP_TIMEOUT_SECONDS
        )
        registry = (
            self._capability_registry
            if self._capability_registry is not None
            else get_capability_registry()
        )
        return CapabilityExecutor(registry, timeout)

    @staticmethod
    def _failure_kind(raw: CapabilityResult) -> str:
        payload = raw.payload if isinstance(raw.payload, dict) else {}
        declared = payload.get("failure_kind")
        if isinstance(declared, str) and declared:
            return declared
        return _STATUS_FAILURE_KINDS.get(raw.status, "transient")

    @staticmethod
    def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
        aggregated: dict[str, Any] = {}
        for key in AGGREGATE_PAYLOAD_KEYS:
            for item in results:
                value = item["payload"].get(key)
                if value:
                    aggregated[key] = value
                    break
        return aggregated

    def _success(self, results: list[dict[str, Any]]) -> CapabilityResult:
        payload: dict[str, Any] = {
            "steps": results,
            "step_count": len(results),
            "failure_kind": None,
            **self._aggregate(results),
        }
        return CapabilityResult(status="succeeded", payload=payload)

    def _failure(
        self,
        status: str,
        failure_kind: str,
        error: str,
        results: list[dict[str, Any]],
    ) -> CapabilityResult:
        payload: dict[str, Any] = {
            "steps": results,
            "step_count": len(results),
            "failed_step": results[-1]["index"] if results else None,
            "failure_kind": failure_kind,
            "retryable": failure_kind in RETRYABLE_FAILURE_KINDS,
            **self._aggregate(results),
        }
        return CapabilityResult(status=status, payload=payload, error=str(error)[:200])


class UserToolRegistrar:
    """自定义工具注册面（§4.3）：校验 → 强制纪律 → 注册；失败不留痕。"""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        settings: Any = None,
        capability_registry: CapabilityRegistry | None = None,
        executor: CapabilityExecutor | None = None,
    ) -> None:
        self._fixed_registry = registry
        self._fixed_capability_registry = capability_registry
        self._settings = settings
        self._executor = executor
        self._registered: dict[str, dict[str, Any]] = {}

    def tool_registry(self) -> ToolRegistry | None:
        return self._fixed_registry if self._fixed_registry is not None else get_tool_registry()

    def capability_registry(self) -> CapabilityRegistry:
        if self._fixed_capability_registry is not None:
            return self._fixed_capability_registry
        return get_capability_registry()

    def list_registered(self) -> list[str]:
        return sorted(self._registered)

    def view(self, tool_id: str) -> dict[str, Any] | None:
        """端点投影：声明 + 推导副作用 + 强制纪律的生效值。"""
        entry = self._registered.get(tool_id)
        if entry is None:
            return None
        registry = self.tool_registry()
        return {
            "tool_id": tool_id,
            "name": entry["name"],
            "description": entry["description"],
            "namespace": USER_NAMESPACE,
            "capability": tool_id,
            "action": USER_TOOL_ACTION,
            "level": FORCED_LEVEL,
            "confirm": USER_TOOL_CONFIRM,
            "scope": list(USER_TOOL_SCOPE),
            "memory_deposit": False,
            "side_effects": list(entry["side_effects"]),
            "declared_side_effects": list(entry["declared_side_effects"]),
            "side_effects_derived": entry["side_effects"] != entry["declared_side_effects"],
            "steps": [dict(step) for step in entry["steps"]],
            "parameters": [parameter.name for parameter in entry["parameters"]],
            "status": (
                "unknown" if registry is None else registry.effective_status(tool_id)
            ),
        }

    def validate(self, declaration: Any) -> ValidationReport:
        if not isinstance(declaration, Mapping):
            return ValidationReport(passed=False, errors=["declaration 必须是键值映射"])
        errors: list[str] = []
        unknown = sorted({str(key) for key in declaration} - ALLOWED_DECLARATION_KEYS)
        if unknown:
            errors.append(
                f"声明含未允许字段（{RED_LINE_LABEL}：不得携带可执行载荷）: {', '.join(unknown)}"
            )
        tool_id = self._check_tool_id(declaration, errors)
        name = _text(declaration, "name", errors, required=True)
        description = _text(declaration, "description", errors, required=True)
        when_to_use = _text(declaration, "when_to_use", errors, required=False)
        when_not_to_use = _text(declaration, "when_not_to_use", errors, required=False)
        _check_budget("name", name, TOOL_NAME_MAX_LENGTH, errors)
        _check_budget("description", description, TOOL_DESCRIPTION_MAX_LENGTH, errors)
        _check_budget("when_to_use", when_to_use, TOOL_WHEN_MAX_LENGTH, errors)
        _check_budget("when_not_to_use", when_not_to_use, TOOL_WHEN_MAX_LENGTH, errors)
        tags = _tags(declaration, errors)
        declared_side_effects = _declared_side_effects(declaration, errors)
        steps_value = declaration.get("steps")
        step_errors = dsl_validate_steps(steps_value)
        errors.extend(step_errors)
        steps: tuple[dict[str, Any], ...] = ()
        if not step_errors:
            steps = tuple(dict(step) for step in steps_value)
            errors.extend(self._check_capabilities(steps))
        parameters = _parse_parameters(declaration, errors)
        if steps:
            parameters = _derive_parameters(parameters, steps, errors)
        side_effects = derive_side_effects(steps)
        return ValidationReport(
            passed=not errors,
            errors=errors,
            tool_id=tool_id,
            side_effects=side_effects,
            steps=steps,
            declared_side_effects=declared_side_effects,
            parameters=parameters,
            tags=tags,
        )

    def _check_tool_id(self, declaration: Mapping[str, Any], errors: list[str]) -> str | None:
        value = declaration.get("tool_id")
        if not isinstance(value, str) or not value.strip():
            errors.append("缺少必需字段: tool_id")
            return None
        tool_id = value.strip()
        if not tool_id.startswith(USER_TOOL_ID_PREFIX):
            errors.append(f"tool_id 必须以 {USER_TOOL_ID_PREFIX} 为前缀: {tool_id}")
            return tool_id
        if not TOOL_ID_PATTERN.fullmatch(tool_id):
            errors.append(f"tool_id 不符合点分命名空间格式: {tool_id}")
            return tool_id
        if tool_id in self._registered:
            errors.append(f"tool_id 已注册（先注销再注册）: {tool_id}")
        registry = self.tool_registry()
        if registry is not None and registry.get(tool_id) is not None:
            errors.append(f"tool_id 已被注册表占用: {tool_id}")
        return tool_id

    def _check_capabilities(self, steps: tuple[dict[str, Any], ...]) -> list[str]:
        """E12：步骤引用的 capability / action 必须真实存在（不注册"看起来能跑"的壳）。"""
        registry = self.capability_registry()
        errors: list[str] = []
        for index, step in enumerate(steps):
            capability = str(step.get("capability", ""))
            action = str(step.get("action", ""))
            if not registry.has(capability, action):
                errors.append(
                    f"steps[{index}] 引用不存在的 capability 动作: ({capability}, {action})"
                )
        return errors

    def _definition(self, declaration: Mapping[str, Any], report: ValidationReport) -> ToolDefinition:
        return ToolDefinition(
            id=report.tool_id or "",
            name=_plain_text(declaration, "name"),
            description=_plain_text(declaration, "description"),
            when_to_use=_plain_text(declaration, "when_to_use"),
            when_not_to_use=_plain_text(declaration, "when_not_to_use"),
            namespace=USER_NAMESPACE,
            capability=report.tool_id or "",
            action=USER_TOOL_ACTION,
            input_schema=ToolSchema(parameters=list(report.parameters)),
            permission=PermissionProfile(
                level=FORCED_LEVEL, scope=USER_TOOL_SCOPE, confirm=USER_TOOL_CONFIRM
            ),
            side_effects=report.side_effects,
            idempotency="keyed",
            tags=report.tags,
            memory_policy_key=report.tool_id,
            observability_fields=tuple(parameter.name for parameter in report.parameters),
        )

    def register(self, declaration: Any) -> str:
        """校验 → 强制纪律 → 注册；任一环节失败即拒绝且不留痕。"""
        report = self.validate(declaration)
        if not report.passed or report.tool_id is None:
            raise UserToolRejected(report.errors)
        tool_id = report.tool_id
        registry = self.tool_registry()
        capability_registry = self.capability_registry()
        if capability_registry.has(tool_id):
            raise UserToolRejected([f"能力名已被占用，拒绝覆盖: {tool_id}"])
        try:
            definition = self._definition(declaration, report)
        except Exception as error:
            raise UserToolRejected(
                [f"工具定义构造失败: {error.__class__.__name__}"]
            ) from error
        capability = UserToolCapability(
            tool_id,
            definition.name,
            report.steps,
            tuple(parameter.name for parameter in report.parameters if parameter.required),
            settings=self._settings,
            executor=self._executor,
            capability_registry=self._fixed_capability_registry,
        )
        try:
            capability_registry.register(capability)
            try:
                registry.register(definition, capability)
            except Exception:
                capability_registry.unregister(tool_id)
                raise
        except UserToolRejected:
            raise
        except Exception as error:
            logger.warning("自定义工具注册失败，未留下任何痕迹: tool_id=%s", tool_id)
            raise UserToolRejected(
                [f"注册失败: {error.__class__.__name__}: {error}"]
            ) from error
        self._registered[tool_id] = {
            "name": definition.name,
            "description": definition.description,
            "steps": report.steps,
            "side_effects": report.side_effects,
            "declared_side_effects": report.declared_side_effects,
            "parameters": report.parameters,
            "capability": capability,
        }
        logger.info(
            "自定义工具已注册: tool_id=%s steps=%d side_effects=%s",
            tool_id,
            len(report.steps),
            list(report.side_effects),
        )
        return tool_id

    def unregister(self, tool_id: str) -> None:
        """注销（进程内存态）：未注册 id 为无操作，不抛错（E14）。

        两处同时移除：工具声明（执行面立即 `unavailable`）与能力实现体（注销即不留痕）。
        """
        self._registered.pop(tool_id, None)
        registry = self.tool_registry()
        if registry is not None:
            registry.unregister(tool_id)
        self.capability_registry().unregister(tool_id)


_registrar: UserToolRegistrar | None = None


def get_user_tool_registrar() -> UserToolRegistrar:
    global _registrar
    if _registrar is None:
        _registrar = UserToolRegistrar()
    return _registrar


def reset_user_tool_registrar() -> None:
    """进程态归零（测试与热修用）：注销全部已注册工具并丢弃记账。"""
    registrar = get_user_tool_registrar()
    for tool_id in list(registrar.list_registered()):
        registrar.unregister(tool_id)
    global _registrar
    _registrar = None
