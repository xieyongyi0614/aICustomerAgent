"""V2.4.0 Tool System 域模型（architecture.md §5 / TOOL-001）。

纯数据定义与纯函数：ToolDefinition / ToolParameter / ToolSchema / PermissionProfile /
ToolBinding / ToolInvocation / ToolExecution / ToolResult / ToolEffect /
ToolObservation / ToolSurface / ToolHealth + 生命周期状态机与权限等级下限判定。
不绑定数据库、HTTP 与 LLM；非法状态迁移返回 None（V8/V9 状态机同款纪律）。
"""

import re
from dataclasses import dataclass, fields as dataclass_fields
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.settings._shared import SettingsError
from app.models.action import ActionIntent

ToolLifecycle = Literal["enabled", "disabled", "deprecated", "removed"]

TOOL_LIFECYCLES: tuple[str, ...] = ("enabled", "disabled", "deprecated", "removed")

ToolExecutionStatus = Literal[
    "succeeded",
    "failed",
    "timeout",
    "unavailable",
    "denied",
    "invalid",
    "pending_confirmation",
]

TOOL_EXECUTION_STATUSES: tuple[str, ...] = (
    "succeeded",
    "failed",
    "timeout",
    "unavailable",
    "denied",
    "invalid",
    "pending_confirmation",
)

ToolFailureKind = Literal[
    "transient", "permanent", "timeout", "unavailable", "denied", "invalid"
]

TOOL_FAILURE_KINDS: tuple[str, ...] = (
    "transient",
    "permanent",
    "timeout",
    "unavailable",
    "denied",
    "invalid",
)

ToolEffectKind = Literal["world", "memory", "relationship", "note", "external"]

TOOL_EFFECT_KINDS: tuple[str, ...] = (
    "world",
    "memory",
    "relationship",
    "note",
    "external",
)

PermissionLevel = Literal["safe", "normal", "sensitive", "dangerous"]

PERMISSION_LEVELS: tuple[str, ...] = ("safe", "normal", "sensitive", "dangerous")

TOOL_LIFECYCLE_VALUES: frozenset[str] = frozenset(get_args(ToolLifecycle))
TOOL_EXECUTION_STATUS_VALUES: frozenset[str] = frozenset(get_args(ToolExecutionStatus))
TOOL_FAILURE_KIND_VALUES: frozenset[str] = frozenset(get_args(ToolFailureKind))
TOOL_EFFECT_KIND_VALUES: frozenset[str] = frozenset(get_args(ToolEffectKind))
PERMISSION_LEVEL_VALUES: frozenset[str] = frozenset(get_args(PermissionLevel))

TOOL_NAMESPACES: tuple[str, ...] = ("builtin", "channel", "world", "ext.api", "user")

TOOL_SIDE_EFFECT_KINDS: tuple[str, ...] = (
    "read",
    "write_world",
    "write_memory",
    "send_external",
    "irreversible",
)

TOOL_IDEMPOTENCY_KINDS: tuple[str, ...] = ("natural", "keyed", "none")

TOOL_CONFIRM_POLICIES: tuple[str, ...] = (
    "never",
    "first_time",
    "always",
    "out_of_scope",
)

TOOL_NAME_MAX_LENGTH = 20
TOOL_DESCRIPTION_MAX_LENGTH = 120
TOOL_WHEN_MAX_LENGTH = 80
TOOL_PARAMETER_DESCRIPTION_MAX_LENGTH = 60
TOOL_RESULT_ERROR_MAX_LENGTH = 80
TOOL_EFFECT_DETAIL_MAX_LENGTH = 200

_TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")

_PERMISSION_LEVEL_RANK: dict[str, int] = {
    "safe": 0,
    "normal": 1,
    "sensitive": 2,
    "dangerous": 3,
}

_NAMESPACE_PERMISSION_FLOOR: dict[str, PermissionLevel] = {
    "builtin": "normal",
    "world": "normal",
    "channel": "sensitive",
    "ext.api": "sensitive",
    "user": "dangerous",
}

_LIFECYCLE_TRANSITIONS: dict[str, dict[str, str]] = {
    "enabled": {"disable": "disabled", "deprecate": "deprecated"},
    "disabled": {"enable": "enabled", "deprecate": "deprecated"},
    "deprecated": {"retire": "removed"},
    "removed": {},
}


def transition_tool_lifecycle(
    status: ToolLifecycle, event: str
) -> ToolLifecycle | None:
    """工具生命周期四态状态机（architecture.md §4.2.3）。

    enabled ⇄ disabled；enabled / disabled → deprecated；deprecated → removed。
    removed 为终态；非法迁移返回 None（不改写调用方状态）。
    """
    if status not in _LIFECYCLE_TRANSITIONS:
        return None
    return _LIFECYCLE_TRANSITIONS[status].get(event)


def permission_level_rank(level: PermissionLevel) -> int:
    if level not in _PERMISSION_LEVEL_RANK:
        raise SettingsError(f"未知权限等级: {level}")
    return _PERMISSION_LEVEL_RANK[level]


def namespace_permission_floor(namespace: str) -> PermissionLevel:
    floor = _NAMESPACE_PERMISSION_FLOOR.get(namespace)
    if floor is None:
        raise SettingsError(
            f"未知工具命名空间: {namespace}；合法命名空间: {', '.join(TOOL_NAMESPACES)}"
        )
    return floor


def resolve_permission_level(
    declared: PermissionLevel,
    namespace: str,
    override_reason: str | None,
) -> PermissionLevel:
    """命名空间权限下限判定（architecture.md §9.2）。

    达标放行；低于下限且带 override_reason 则放行（降级事实留在画像里）；
    低于下限且无理由则拒绝——等级只能调高不能调低。
    """
    floor = namespace_permission_floor(namespace)
    if permission_level_rank(declared) >= permission_level_rank(floor):
        return declared
    if override_reason:
        return declared
    raise SettingsError(
        f"命名空间 {namespace} 的权限下限为 {floor}，声明等级 {declared} 低于下限"
        "且未提供 override_reason（等级只能调高不能调低）"
    )


class ToolParameter(BaseModel):
    name: str
    type: str
    required: bool = False
    description: str = Field(default="", max_length=TOOL_PARAMETER_DESCRIPTION_MAX_LENGTH)
    enum: tuple[Any, ...] = ()
    default: Any = None
    min: float | int | None = None
    max: float | int | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str = ""
    format: str = ""
    sensitive: bool = False
    source_hint: str = ""


class ToolSchema(BaseModel):
    parameters: list[ToolParameter] = []
    strict: bool = True
    semantic_validators: tuple[str, ...] = ()

    def json_shape(self) -> dict[str, Any]:
        return {
            "strict": self.strict,
            "semantic_validators": list(self.semantic_validators),
            "parameters": [
                {
                    "name": parameter.name,
                    "type": parameter.type,
                    "required": parameter.required,
                }
                for parameter in self.parameters
            ],
        }


class PermissionProfile(BaseModel):
    level: PermissionLevel
    scope: tuple[str, ...] = ()
    confirm: str = "never"
    rate_limit: dict[str, Any] | None = None
    requires_online: bool = False
    audit: bool = False
    scope_grant_ref: str | None = None
    override_reason: str | None = None


class ToolDefinition(BaseModel):
    id: str
    name: str = Field(max_length=TOOL_NAME_MAX_LENGTH)
    description: str = Field(max_length=TOOL_DESCRIPTION_MAX_LENGTH)
    when_to_use: str = Field(default="", max_length=TOOL_WHEN_MAX_LENGTH)
    when_not_to_use: str = Field(default="", max_length=TOOL_WHEN_MAX_LENGTH)
    namespace: str
    capability: str
    action: str
    input_schema: ToolSchema
    output_schema: ToolSchema | None = None
    permission: PermissionProfile
    status: ToolLifecycle = "enabled"
    version: str = "1.0.0"
    side_effects: tuple[str, ...] = ()
    idempotency: str = "natural"
    timeout_seconds: float | None = None
    error_map: dict[str, str] = {}
    tags: tuple[str, ...] = ()
    priority: int = 100
    memory_policy_key: str | None = None
    observability_fields: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _validate_tool_id(cls, value: str) -> str:
        if not _TOOL_ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"工具 id 非法: {value}；要求点分命名空间格式（如 builtin.reminder.create），"
                "仅允许小写字母/数字/下划线且至少两段"
            )
        return value

    @field_validator("error_map")
    @classmethod
    def _validate_error_map(cls, value: dict[str, str]) -> dict[str, str]:
        for error_name, failure_kind in value.items():
            if failure_kind not in TOOL_FAILURE_KIND_VALUES:
                raise ValueError(
                    f"error_map[{error_name}] 的 failure_kind 非法: {failure_kind}；"
                    f"合法值集: {', '.join(TOOL_FAILURE_KINDS)}"
                )
        return value

    @model_validator(mode="after")
    def _enforce_permission_invariants(self):
        resolve_permission_level(
            self.permission.level, self.namespace, self.permission.override_reason
        )
        if self.is_irreversible() or self.permission.level == "dangerous":
            self.permission.audit = True
        return self

    def is_read_only(self) -> bool:
        return self.side_effects == ("read",)

    def is_irreversible(self) -> bool:
        return "irreversible" in self.side_effects

    def effective_timeout(self, global_default: float) -> float:
        if self.timeout_seconds is None:
            return global_default
        return self.timeout_seconds


class ToolBinding(BaseModel):
    tool_id: str
    capability: str
    action: str
    definition: ToolDefinition


class ToolInvocation(BaseModel):
    tool_id: str
    params: dict[str, Any] = {}
    rationale: str = ""
    source: str = "conversation"
    intent: ActionIntent
    goal_id: str | None = None
    dedupe_key: str = ""
    run_id: str | None = None
    surface_hash: str | None = None


class ToolEffect(BaseModel):
    kind: ToolEffectKind
    ref: str
    detail: str = Field(default="", max_length=TOOL_EFFECT_DETAIL_MAX_LENGTH)
    reversible: bool = False


class ToolObservation(BaseModel):
    untrusted: bool = False
    source_tool: str = ""
    facts: dict[str, Any] = {}


@dataclass(frozen=True)
class PermissionDecision:
    """权限裁决（形状由 TOOL-005 §2.2 冻结；P2-2 起定义在模型层）。

    模型层**零服务依赖**（依赖方向 services → models 不可逆），而 `ToolExecution.permission`
    的类型化视图正是本裁决，故契约归位模型层；`services/tool/permission.py` 原样再导出，
    既有导入路径不变。
    """

    decision: str
    level: PermissionLevel
    reason: str
    confirm_prompt: str | None = None
    scope_required: tuple[str, ...] = ()
    confirm_kind: str | None = None


class ValidationReport(BaseModel):
    """校验产出（architecture.md §4.4）：错误分类 + 规范化参数（P2-2 起定义在模型层）。"""

    passed: bool
    structural: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}


class ToolResult(BaseModel):
    status: ToolExecutionStatus
    effects: list[ToolEffect] = []
    observations: dict[str, Any] = {}
    failure_kind: ToolFailureKind | None = None
    error: str | None = Field(default=None, max_length=TOOL_RESULT_ERROR_MAX_LENGTH)
    usage: dict[str, Any] = {}
    redacted: list[str] = []
    raw_error: str | None = None


class ToolExecution(BaseModel):
    index: int
    tool_id: str
    capability: str
    action: str
    status: ToolExecutionStatus
    params: dict[str, Any] = {}
    permission: dict[str, Any] = {}
    validation: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    started_at: datetime | None = None
    duration_ms: int | None = None

    def result_model(self) -> ToolResult | None:
        """`result` 的类型化视图（P2-2）：dict 与模型实例都能还原，失败返回 `None`。

        只读便利访问器：**字段名与 JSON 序列化形状不变**（落库与 outbox 读面不受影响）。
        落库形态含 `payload` 等非 `ToolResult` 键（TOOL-010 兼容双写），多余键被忽略。
        """
        return _coerce_model(ToolResult, self.result)

    def validation_model(self) -> ValidationReport | None:
        """`validation` 的类型化视图（P2-2）；`None` / 形状不合 → `None`，不抛错。"""
        return _coerce_model(ValidationReport, self.validation)

    def permission_model(self) -> PermissionDecision | None:
        """`permission` 的类型化视图（P2-2）；`None` / 形状不合 → `None`，不抛错。

        `PermissionDecision` 是 frozen dataclass（非 pydantic），按字段名过滤后构造：
        `ToolExecution.permission` 里的 `confirmed` 不在其字段集内，被安全丢弃。
        """
        return _coerce_model(PermissionDecision, self.permission)


def _coerce_model(model_type: Any, value: Any) -> Any | None:
    """dict / 模型实例 → 模型实例；不匹配或构造失败一律返回 `None`（不抛错、不记日志）。"""
    if value is None:
        return None
    if isinstance(value, model_type):
        return value
    if not isinstance(value, dict):
        return None
    try:
        validator = getattr(model_type, "model_validate", None)
        if callable(validator):
            return validator(value)
        field_names = {item.name for item in dataclass_fields(model_type)}
        return model_type(
            **{key: item for key, item in value.items() if key in field_names}
        )
    except Exception:
        return None


class ToolSurface(BaseModel):
    run_kind: str
    tool_ids: tuple[str, ...] = ()
    excluded: tuple[dict[str, Any], ...] = ()
    surface_hash: str = ""


class ToolHealth(BaseModel):
    consecutive_failures: int = 0
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    failure_rate_window: float = 0.0
    tripped: bool = False
