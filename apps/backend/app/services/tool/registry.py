"""V2.4.0 ToolRegistry（architecture.md §4.2 / TOOL-002）：工具的声明与发现唯一权威。

模块级单例、运行期不增删（代码注册，V9 CapabilityRegistry 同款纪律）；
只做声明与发现——不执行、不做授权判断、不做参数校验（TOOL-003 / 004 / 005）。
注册期七项校验失败即抛错：注册是启动期行为，错误必须显式暴露，不降级不静默。
生命周期为三层纯函数式叠加（代码态基线 + 运行期禁用 + 熔断），覆盖层不写回声明；
运行期禁用有两条来源：settings 的 `v24_tool_disabled_ids`（配置态）与
`set_runtime_disabled()` / `clear_runtime_disabled()`（进程内存态，管理面风控入口，TOOL-004），
两者与熔断一起被 `effective_status()` 消费，重启即清零。
健康度为进程内存态，重启归零，`record_outcome()` 与熔断置位/解除（TOOL-003 写入面）
是仅有的写入面。
`ToolHealth.failure_rate_window` 沿用 TOOL-001 的滑动窗失败率（float）定义：
有界原始序列留在本模块私有结构中，只把算出的比率写进健康度。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.models.action import ActionSchema
from app.models.tool import (
    TOOL_DESCRIPTION_MAX_LENGTH,
    TOOL_FAILURE_KINDS,
    TOOL_FAILURE_KIND_VALUES,
    TOOL_NAME_MAX_LENGTH,
    TOOL_NAMESPACES,
    TOOL_WHEN_MAX_LENGTH,
    PermissionProfile,
    ToolBinding,
    ToolDefinition,
    ToolHealth,
    ToolLifecycle,
    ToolParameter,
    ToolSchema,
    ToolSurface,
    resolve_permission_level,
)
from app.services.action.registry import Capability, get_capability_registry

TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")

TOOL_HEALTH_WINDOW_SIZE = 10

_CODE_TERMINAL_STATES: frozenset[str] = frozenset({"deprecated", "removed"})

_REGISTRATION_CHECK_LABELS: dict[int, str] = {
    1: "校验 1｜id 格式",
    2: "校验 2｜id 唯一",
    3: "校验 3｜命名空间白名单",
    4: "校验 4｜capability 可解析",
    5: "校验 5｜schema 自洽",
    6: "校验 6｜permission 合法",
    7: "校验 7｜字段长度预算",
}


@dataclass(frozen=True)
class ToolDescriptor:
    """`describe()` 输出项：LLM / 决策层可读的工具描述投影（不落库）。"""

    tool_id: str
    name: str
    description: str
    when_to_use: str | None
    namespace: str
    params: dict[str, dict[str, Any]]
    side_effects: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class NamespaceIndex:
    """命名空间索引项：该命名空间下的工具与其中可用数量。"""

    namespace: str
    tool_ids: list[str]
    enabled_count: int


def _registration_error(check: int, reason: str) -> ValueError:
    return ValueError(f"工具注册校验失败｜{_REGISTRATION_CHECK_LABELS[check]}：{reason}")


def _validate_id_format(definition: ToolDefinition) -> None:
    if not TOOL_ID_PATTERN.fullmatch(definition.id):
        raise _registration_error(
            1,
            f"工具 id 非法: {definition.id}；要求点分命名空间格式"
            f"（如 builtin.reminder.create），仅允许小写字母/数字/下划线且 2~4 段",
        )


def _validate_id_unique(
    definition: ToolDefinition, registered: dict[str, ToolDefinition]
) -> None:
    if definition.id in registered:
        raise _registration_error(2, f"工具 id 重复注册: {definition.id}")


def _validate_namespace(definition: ToolDefinition) -> None:
    if definition.namespace not in TOOL_NAMESPACES:
        raise _registration_error(
            3,
            f"未声明的命名空间: {definition.namespace}；"
            f"合法命名空间: {', '.join(TOOL_NAMESPACES)}",
        )


def _validate_capability_resolvable(
    definition: ToolDefinition, capability: Capability | None = None
) -> None:
    registry = get_capability_registry()
    if not registry.has(definition.capability, definition.action):
        available = ", ".join(sorted(entry["name"] for entry in registry.describe()))
        raise _registration_error(
            4,
            f"CapabilityRegistry 中无法解析绑定 ({definition.capability}, "
            f"{definition.action})；已注册能力: {available}",
        )
    if capability is not None and capability.name != definition.capability:
        raise _registration_error(
            4,
            f"传入的能力实现 {capability.name} 与声明的 {definition.capability} 不一致",
        )


def _bound_action_schema(definition: ToolDefinition) -> ActionSchema:
    capability = get_capability_registry().get(definition.capability)
    schema = None if capability is None else capability.actions.get(definition.action)
    if schema is None:
        raise _registration_error(
            5,
            f"无法读取绑定 ({definition.capability}, {definition.action}) 的动作契约；"
            "注册前应先通过校验 4",
        )
    return schema


def _validate_schema_alignment(definition: ToolDefinition) -> None:
    schema = _bound_action_schema(definition)
    declared = {
        parameter.name
        for parameter in definition.input_schema.parameters
        if parameter.required
    }
    missing = [name for name in schema.required if name not in declared]
    if missing:
        raise _registration_error(
            5,
            f"input_schema 缺少必需参数: {', '.join(missing)}；"
            f"绑定动作 ({definition.capability}, {definition.action}) 的 required 为 "
            f"{schema.required or '[]'}",
        )


def _validate_permission_level(definition: ToolDefinition) -> None:
    try:
        resolve_permission_level(
            definition.permission.level,
            definition.namespace,
            definition.permission.override_reason,
        )
    except SettingsError as error:
        raise _registration_error(6, str(error)) from error


def _validate_field_budget(definition: ToolDefinition) -> None:
    budgets = (
        ("name", definition.name, TOOL_NAME_MAX_LENGTH),
        ("description", definition.description, TOOL_DESCRIPTION_MAX_LENGTH),
        ("when_to_use", definition.when_to_use, TOOL_WHEN_MAX_LENGTH),
    )
    for field_name, value, limit in budgets:
        if len(value) > limit:
            raise _registration_error(
                7, f"{field_name} 长度 {len(value)} 超出上限 {limit}"
            )


def _descriptor(definition: ToolDefinition, status: str) -> ToolDescriptor:
    return ToolDescriptor(
        tool_id=definition.id,
        name=definition.name,
        description=definition.description,
        when_to_use=definition.when_to_use or None,
        namespace=definition.namespace,
        params={
            parameter.name: {
                "type": parameter.type,
                "required": parameter.required,
                **({"enum": list(parameter.enum)} if parameter.enum else {}),
            }
            for parameter in definition.input_schema.parameters
        },
        side_effects=tuple(definition.side_effects),
        status=status,
    )


class ToolRegistry:
    """工具声明注册表：注册期七项校验 + 解析面 + 查询面 + 健康度读写面。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._bindings: dict[str, ToolBinding] = {}
        self._health: dict[str, ToolHealth] = {}
        self._windows: dict[str, list[bool]] = {}
        self._runtime_disabled: set[str] = set()
        self._namespaces: dict[str, list[str]] = {
            namespace: [] for namespace in TOOL_NAMESPACES
        }

    def register(
        self, definition: ToolDefinition, capability: Capability | None = None
    ) -> None:
        """注册声明并绑定实现；七项校验按序短路，任一失败即抛错。"""
        _validate_id_format(definition)
        _validate_id_unique(definition, self._tools)
        _validate_namespace(definition)
        _validate_capability_resolvable(definition, capability)
        _validate_schema_alignment(definition)
        _validate_permission_level(definition)
        _validate_field_budget(definition)
        self._tools[definition.id] = definition
        self._bindings[definition.id] = ToolBinding(
            tool_id=definition.id,
            capability=definition.capability,
            action=definition.action,
            definition=definition,
        )
        self._namespaces[definition.namespace].append(definition.id)
        self._namespaces[definition.namespace].sort()
        self._health[definition.id] = ToolHealth()
        self._windows[definition.id] = []

    def unregister(self, tool_id: str) -> None:
        """移除声明与健康度（测试与热修用）；未注册 id 为无操作。"""
        definition = self._tools.pop(tool_id, None)
        if definition is None:
            return
        self._bindings.pop(tool_id, None)
        self._health.pop(tool_id, None)
        self._windows.pop(tool_id, None)
        self._runtime_disabled.discard(tool_id)
        namespace_tools = self._namespaces.get(definition.namespace)
        if namespace_tools is not None and tool_id in namespace_tools:
            namespace_tools.remove(tool_id)

    def resolve(self, tool_id: str) -> ToolBinding | None:
        return self._bindings.get(tool_id)

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def has(self, tool_id: str, *, enabled_only: bool = True) -> bool:
        if tool_id not in self._tools:
            return False
        if not enabled_only:
            return True
        return self.effective_status(tool_id) == "enabled"

    def list(
        self,
        *,
        namespace: str | None = None,
        status: str | None = None,
        capability: str | None = None,
        tags: tuple[str, ...] | None = None,
    ) -> list[ToolDefinition]:
        """四维过滤（namespace → status → capability → tags），排序恒为 tool_id 字典序。"""
        definitions: list[ToolDefinition] = []
        for tool_id in sorted(self._tools):
            definition = self._tools[tool_id]
            if namespace is not None and definition.namespace != namespace:
                continue
            if status is not None and self.effective_status(tool_id) != status:
                continue
            if capability is not None and definition.capability != capability:
                continue
            if tags and not all(tag in definition.tags for tag in tags):
                continue
            definitions.append(definition)
        return definitions

    def namespaces(self) -> dict[str, NamespaceIndex]:
        return {
            namespace: NamespaceIndex(
                namespace=namespace,
                tool_ids=list(self._namespaces[namespace]),
                enabled_count=sum(
                    1
                    for tool_id in self._namespaces[namespace]
                    if self.effective_status(tool_id) == "enabled"
                ),
            )
            for namespace in TOOL_NAMESPACES
        }

    def describe(self, *, surface: ToolSurface | None = None) -> list[ToolDescriptor]:
        """工具描述投影：无 surface 取全部可用工具，有 surface 取其中可用工具（保序）。"""
        tool_ids = (
            sorted(self._tools) if surface is None else _surface_tool_ids(surface)
        )
        descriptors: list[ToolDescriptor] = []
        for tool_id in tool_ids:
            definition = self._tools.get(tool_id)
            if definition is None:
                continue
            status = self.effective_status(tool_id)
            if status != "enabled":
                continue
            descriptors.append(_descriptor(definition, status))
        return descriptors

    def effective_status(self, tool_id: str) -> ToolLifecycle:
        """生命周期三层叠加：代码态基线，运行期禁用与熔断为覆盖层；未注册视为 removed。"""
        definition = self._tools.get(tool_id)
        if definition is None:
            return "removed"
        code_state = definition.status
        if code_state in _CODE_TERMINAL_STATES:
            return code_state
        if tool_id in self._runtime_disabled:
            return "disabled"
        if tool_id in get_settings().disabled_tool_ids():
            return "disabled"
        health = self._health.get(tool_id)
        if health is not None and health.tripped:
            return "disabled"
        return code_state

    def set_runtime_disabled(self, tool_id: str) -> bool:
        """运行期禁用（风控，进程内存态）：未注册 id 返回 False 且不写入（E10）。"""
        if tool_id not in self._tools:
            return False
        self._runtime_disabled.add(tool_id)
        return True

    def clear_runtime_disabled(self, tool_id: str) -> bool:
        """解除运行期禁用；未注册 id 返回 False（未禁用者亦返回 True，幂等）。"""
        if tool_id not in self._tools:
            return False
        self._runtime_disabled.discard(tool_id)
        return True

    def runtime_disabled_ids(self) -> frozenset[str]:
        return frozenset(self._runtime_disabled)

    def health(self, tool_id: str | None = None) -> dict[str, ToolHealth]:
        """只读健康度快照（返回副本，调用方改写不影响注册表）。"""
        if tool_id is not None:
            record = self._health.get(tool_id)
            return {} if record is None else {tool_id: record.model_copy()}
        return {
            key: self._health[key].model_copy() for key in sorted(self._health)
        }

    def record_outcome(
        self, tool_id: str, *, ok: bool, failure_kind: str | None = None
    ) -> None:
        """健康度唯一写入面；未注册工具静默忽略（不打断执行链）。"""
        record = self._health.get(tool_id)
        if record is None:
            return
        if failure_kind is not None and failure_kind not in TOOL_FAILURE_KIND_VALUES:
            raise ValueError(
                f"未知失败类型: {failure_kind}；合法值集: {', '.join(TOOL_FAILURE_KINDS)}"
            )
        window = self._windows[tool_id]
        window.append(ok)
        if len(window) > TOOL_HEALTH_WINDOW_SIZE:
            del window[: len(window) - TOOL_HEALTH_WINDOW_SIZE]
        now = datetime.now()
        if ok:
            record.consecutive_failures = 0
            record.last_success_at = now
        else:
            record.consecutive_failures += 1
            record.last_failure_at = now
        record.failure_rate_window = sum(
            1 for outcome in window if not outcome
        ) / len(window)

    def mark_tripped(self, tool_id: str) -> None:
        """熔断置位（TOOL-003 健康度 tracker 的写入面）；未注册 id 为无操作。"""
        record = self._health.get(tool_id)
        if record is None:
            return
        record.tripped = True

    def clear_tripped(self, tool_id: str) -> None:
        """熔断解除 / 冷却半开；`consecutive_failures` 由调用方保留（半开后下次失败立即重熔）。"""
        record = self._health.get(tool_id)
        if record is None:
            return
        record.tripped = False


def _surface_tool_ids(surface: ToolSurface) -> list[str]:
    ordered: list[str] = []
    for tool_id in surface.tool_ids:
        if tool_id not in ordered:
            ordered.append(tool_id)
    return ordered


def _parameter(
    name: str,
    type_: str,
    *,
    required: bool = False,
    description: str = "",
    enum: tuple[Any, ...] = (),
    format_: str = "",
    default: Any = None,
    min_value: float | int | None = None,
    max_value: float | int | None = None,
    source_hint: str = "",
) -> ToolParameter:
    return ToolParameter(
        name=name,
        type=type_,
        required=required,
        description=description,
        enum=enum,
        format=format_,
        default=default,
        min=min_value,
        max=max_value,
        source_hint=source_hint,
    )


def _builtin_definitions() -> tuple[ToolDefinition, ...]:
    """V9 六能力 → 10 条声明（TOOL-002 §2.4 映射表，只声明不改任何能力实现）。"""
    return (
        ToolDefinition(
            id="builtin.reminder.create",
            name="创建提醒",
            description="在指定时间点创建一条提醒并落 WorldEvent，到期触发与记忆沉淀继承世界语义。",
            when_to_use="用户要求在未来某个时间点提醒某事时使用",
            when_not_to_use="只需要当下口头回应、不涉及未来触发时不要使用",
            namespace="builtin",
            capability="reminder",
            action="create",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "content",
                        "string",
                        required=True,
                        description="提醒内容",
                        source_hint="user_message",
                    ),
                    _parameter(
                        "due_at",
                        "datetime",
                        required=True,
                        description="提醒触发时间",
                        format_="iso8601",
                        source_hint="user_message",
                    ),
                    _parameter(
                        "importance",
                        "enum",
                        description="重要程度",
                        enum=("low", "normal", "high"),
                        default="normal",
                    ),
                ],
                semantic_validators=("future_datetime",),
            ),
            permission=PermissionProfile(level="normal", scope=("world",)),
            side_effects=("write_world",),
            idempotency="keyed",
            priority=10,
            tags=("reminder", "world"),
            observability_fields=("content", "due_at", "importance"),
        ),
        ToolDefinition(
            id="builtin.reminder.cancel",
            name="取消提醒",
            description="取消一条已创建的提醒（按事件 id 或可定位描述匹配），取消结果落世界事件。",
            when_to_use="用户表示某条提醒不再需要、要求撤销时使用",
            when_not_to_use="用户只是询问提醒内容时不要使用",
            namespace="builtin",
            capability="reminder",
            action="cancel",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "target",
                        "string",
                        required=True,
                        description="目标提醒的事件 id 或可定位描述",
                        source_hint="user_message",
                    )
                ]
            ),
            permission=PermissionProfile(level="normal", scope=("world",)),
            side_effects=("write_world",),
            idempotency="keyed",
            priority=20,
            tags=("reminder", "world"),
            observability_fields=("target",),
        ),
        ToolDefinition(
            id="builtin.memory.save",
            name="保存记忆",
            description="把用户明确陈述的事实写入长期记忆，经 R1~R8 政策校验后落库，来源为用户陈述。",
            when_to_use="用户明确要求记住某事、或陈述了值得长期保留的事实时使用",
            when_not_to_use="用户只是随口提及、未表达长期保留意图时不要使用",
            namespace="builtin",
            capability="memory",
            action="save",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "fact",
                        "string",
                        required=True,
                        description="要长期保留的事实（陈述句）",
                        source_hint="user_message",
                    ),
                    _parameter(
                        "memory_type",
                        "enum",
                        description="记忆类型",
                        enum=("user_fact", "preference", "event"),
                    ),
                    _parameter(
                        "importance",
                        "number",
                        description="重要性 0~1",
                        min_value=0,
                        max_value=1,
                    ),
                ]
            ),
            permission=PermissionProfile(level="normal", scope=("memory",)),
            side_effects=("write_memory",),
            idempotency="keyed",
            priority=30,
            tags=("memory",),
            observability_fields=("fact", "memory_type", "importance"),
        ),
        ToolDefinition(
            id="world.object.create",
            name="创建世界物品",
            description="在世界中创建一件物品并登记归属与位置，物品身份由世界状态机管理。",
            when_to_use="用户委托把某件物品放入世界时使用",
            when_not_to_use="物品已在世界中、只需移动或使用时不要重复创建",
            namespace="world",
            capability="world_action",
            action="create",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "object",
                        "string",
                        required=True,
                        description="物品名称",
                        source_hint="user_message",
                    ),
                    _parameter("quantity", "number", description="数量", min_value=1),
                    _parameter(
                        "location",
                        "string",
                        description="目标地点",
                        format_="location_id",
                    ),
                ]
            ),
            permission=PermissionProfile(level="normal", scope=("world",)),
            side_effects=("write_world",),
            idempotency="keyed",
            priority=40,
            tags=("world", "object"),
            observability_fields=("object", "quantity", "location"),
        ),
        ToolDefinition(
            id="world.object.move",
            name="移动世界物品",
            description="把世界中已存在的物品迁移到目标地点，先解析实体再迁移，不凭空造事实。",
            when_to_use="用户要求把某件物品放到另一个地点时使用",
            when_not_to_use="目标物品不在世界中时不要使用（应先创建）",
            namespace="world",
            capability="world_action",
            action="move",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "object",
                        "string",
                        required=True,
                        description="物品名称",
                        source_hint="user_message",
                    ),
                    _parameter(
                        "location",
                        "string",
                        required=True,
                        description="目标地点",
                        format_="location_id",
                        source_hint="user_message",
                    ),
                ],
                semantic_validators=("location_exists",),
            ),
            permission=PermissionProfile(level="normal", scope=("world",)),
            side_effects=("write_world",),
            idempotency="keyed",
            priority=50,
            tags=("world", "object"),
            observability_fields=("object", "location"),
        ),
        ToolDefinition(
            id="world.object.use",
            name="使用世界物品",
            description="对世界中已存在的物品执行使用动作，返回世界侧观察事实供回复取材。",
            when_to_use="用户要求使用或消耗某件已存在物品时使用",
            when_not_to_use="物品不存在或只是询问物品信息时不要使用",
            namespace="world",
            capability="world_action",
            action="use",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "object",
                        "string",
                        required=True,
                        description="物品名称",
                        source_hint="user_message",
                    ),
                    _parameter("action", "string", description="使用动作细分"),
                ],
                semantic_validators=("object_in_inventory",),
            ),
            permission=PermissionProfile(level="normal", scope=("world",)),
            side_effects=("write_world",),
            idempotency="keyed",
            priority=60,
            tags=("world", "object"),
            observability_fields=("object", "action"),
        ),
        ToolDefinition(
            id="world.env.query",
            name="查询环境状态",
            description="查询时间/天气/温度/光照等环境切片（只读，simulated 数据源，零写入）。",
            when_to_use="回复需要环境事实（时间、天气、光照）作为素材时使用",
            when_not_to_use="需要改变世界状态时不要使用（本工具只读）",
            namespace="world",
            capability="environment_query",
            action="query",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "dimension",
                        "enum",
                        description="环境维度",
                        enum=("weather", "temperature", "time", "lighting"),
                    )
                ]
            ),
            permission=PermissionProfile(
                level="safe",
                scope=("world",),
                override_reason="只读环境查询无副作用，按只读工具降级到命名空间下限之下",
            ),
            side_effects=("read",),
            idempotency="natural",
            priority=70,
            tags=("world", "environment", "read"),
            observability_fields=("dimension",),
        ),
        ToolDefinition(
            id="builtin.search.query",
            name="检索信息",
            description="对外部信息做检索查询，当前为接口预留占位（TOOL-010 接入真实数据源）。",
            when_to_use="需要外部事实、用户询问超出世界与记忆范围的信息时使用",
            when_not_to_use="答案已在世界状态或记忆中时不要使用",
            namespace="builtin",
            capability="search",
            action="query",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "query",
                        "string",
                        required=True,
                        description="检索关键词或问题",
                        source_hint="user_message",
                    )
                ]
            ),
            permission=PermissionProfile(
                level="safe",
                scope=("self",),
                override_reason="只读检索无副作用，按只读工具降级到命名空间下限之下",
            ),
            side_effects=("read",),
            idempotency="natural",
            priority=80,
            tags=("search", "read"),
            observability_fields=("query",),
        ),
        ToolDefinition(
            id="builtin.notification.send",
            name="发送通知",
            description="向用户发送一条通知消息（接口预留占位，MVP 落行动 note，TOOL-010 落地）。",
            when_to_use="需要主动把信息推送给用户、且不需要外部通道时使用",
            when_not_to_use="只是对话内回复时不要使用",
            namespace="builtin",
            capability="notification",
            action="send",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "content",
                        "string",
                        required=True,
                        description="通知正文",
                        source_hint="user_message",
                    )
                ]
            ),
            permission=PermissionProfile(
                level="sensitive",
                scope=("self",),
                confirm="first_time",
                requires_online=True,
            ),
            side_effects=("send_external",),
            idempotency="keyed",
            priority=90,
            tags=("notification",),
            observability_fields=("content",),
        ),
        ToolDefinition(
            id="channel.feishu.send",
            name="飞书通道发送",
            description="经飞书通道向绑定用户发送消息（TOOL-010 落地，本版本仅占位声明，状态 disabled）。",
            when_to_use="需要经飞书通道触达用户时使用（TOOL-010 启用后生效）",
            namespace="channel",
            capability="notification",
            action="send",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "content",
                        "string",
                        required=True,
                        description="消息正文",
                        source_hint="user_message",
                    )
                ]
            ),
            permission=PermissionProfile(
                level="sensitive",
                scope=("channel:feishu",),
                confirm="first_time",
                requires_online=True,
            ),
            status="disabled",
            side_effects=("send_external",),
            idempotency="keyed",
            priority=100,
            tags=("channel", "feishu"),
            observability_fields=("content",),
        ),
    )


def register_builtin_tools(registry: ToolRegistry) -> None:
    """按 §2.4 映射表逐条注册；仅在总闸开启时被 `get_tool_registry()` 调用。"""
    capabilities = get_capability_registry()
    for definition in _builtin_definitions():
        registry.register(definition, capabilities.get(definition.capability))


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry | None:
    """模块级单例：总闸 off 返回 None（调用方走 V9 原路径），on 时惰性构建一次。"""
    global _registry
    if not get_settings().v24_tool_system_enabled:
        return None
    if _registry is None:
        registry = ToolRegistry()
        register_builtin_tools(registry)
        _registry = registry
    return _registry
