"""V2.4.0 内置工具声明（architecture.md §4.2.4 / TOOL-010 §2.2、§4.1）。

内置工具的**完整声明**唯一落点（TOOL-002 的十行声明自 `registry.py` 迁入本模块，
`registry.register_builtin_tools` 只做委托）：schema 细节（长度预算与 enum）、
observations 键映射（`TOOL_OBSERVATION_KEYS`）、语义校验器绑定、记忆边界键
（`memory_policy_key`）在这里逐条对齐 §2.2 表；**执行语义零改动**——V9 六个能力实现体
不被本模块触碰，`world.object.*` / `builtin.reminder.*` 的 payload 契约原样保留。

两处本任务新增的可用性语义（§2.3）：

- `builtin.search.query`（路线 B，见任务报告"search 路线裁决"）：**保持 `unavailable`**，
  补齐 `failure_kind=unavailable` 与角色语气话术（`TOOL_FAILURE_TEXT`），并在工具面按
  `TOOL_UNAVAILABLE_TOOL_IDS` **默认裁剪**，避免反复触发必然失败的工具。工具仍注册、
  仍可 `resolve`（直调得可判定失败，不是空壳）。
- `channel.feishu.send`：TOOL-002 的 `disabled` 占位改为**可用性派生状态**——
  `channel_tools_enabled()`（总闸 + 通道子闸 + `feishu_enabled`）成立时 `enabled`
  并绑定 `channel_feishu` 能力，否则 `disabled` 且不进工具面（§6.3 E4）。

`channel.feishu.send` 绑定 `channel_feishu` 而非 `notification`：工具面必须能把它与
"行动 note"区分开（一个外发、一个只留字条），共享 `(capability, action)` 会让
`ToolSelector` 与执行面无法分流。该能力只在通道可用时进入全局 `CapabilityRegistry`，
故默认配置下 V9 仍是六个能力（`tests/unit` 与 `tests/v9` 零改动）。
"""

from __future__ import annotations

from typing import Any

from app.character.asuna.tool import TOOL_OBSERVATION_KEYS
from app.models.tool import (
    PermissionProfile,
    ToolDefinition,
    ToolParameter,
    ToolSchema,
)
from app.services.action.registry import get_capability_registry
from app.services.tool.channel_tools import (
    CHANNEL_CAPABILITY_NAME,
    CHANNEL_SCOPE,
    CHANNEL_SEND_ACTION,
    CHANNEL_SEND_TOOL_ID,
    CHANNEL_TEXT_MAX_CHARS,
    channel_tools_enabled,
    get_channel_capability,
)

REMINDER_CONTENT_MAX_CHARS = 40
REMINDER_TARGET_MAX_CHARS = 40
MEMORY_FACT_MAX_CHARS = 120
OBJECT_NAME_MAX_CHARS = 40
OBJECT_CATEGORIES: tuple[str, ...] = (
    "food",
    "drink",
    "tool",
    "furniture",
    "clothing",
    "device",
    "misc",
)
SEARCH_QUERY_MAX_CHARS = 60
NOTIFICATION_CONTENT_MAX_CHARS = 200
LEDGER_NOTE_MAX_CHARS = 80
LEDGER_MERCHANT_MAX_CHARS = 40
LEDGER_REASON_MAX_CHARS = 80
LEDGER_IDEMPOTENCY_MIN_LENGTH = 8

IMPORTANCE_VALUES: tuple[str, ...] = ("low", "normal", "high")
MEMORY_TYPES: tuple[str, ...] = ("user_fact", "preference", "event")
ENVIRONMENT_DIMENSIONS: tuple[str, ...] = ("weather", "temperature", "time", "lighting")
LEDGER_DIRECTIONS: tuple[str, ...] = ("expense", "income", "transfer")
LEDGER_SOURCES: tuple[str, ...] = ("conversation", "action", "manual", "import")
LEDGER_PERIODS: tuple[str, ...] = ("month", "week")

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
    max_length: int | None = None,
    min_length: int | None = None,
    source_hint: str = "",
) -> ToolParameter:
    return ToolParameter(
        name=name,
        type=type_,
        required=required,
        description=description,
        enum=enum,
        default=default,
        min=min_value,
        max=max_value,
        max_length=max_length,
        min_length=min_length,
        format=format_,
        source_hint=source_hint,
    )


def _channel_status(settings: Any) -> str:
    return "enabled" if channel_tools_enabled(settings) else "disabled"


def _definitions(settings: Any = None) -> tuple[ToolDefinition, ...]:
    """§2.2 表逐条声明；通道工具状态由 `channel_tools_enabled(settings)` 派生。"""
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
                        max_length=REMINDER_CONTENT_MAX_CHARS,
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
                        enum=IMPORTANCE_VALUES,
                        default="normal",
                    ),
                ],
                semantic_validators=("future_datetime", "content_within_budget"),
            ),
            permission=PermissionProfile(level="normal", scope=("world",)),
            side_effects=("write_world",),
            idempotency="keyed",
            priority=10,
            tags=("reminder", "world"),
            memory_policy_key="builtin.reminder.create",
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
                        max_length=REMINDER_TARGET_MAX_CHARS,
                        source_hint="user_message",
                    )
                ]
            ),
            permission=PermissionProfile(level="normal", scope=("world",)),
            side_effects=("write_world",),
            idempotency="keyed",
            priority=20,
            tags=("reminder", "world"),
            memory_policy_key="builtin.reminder.cancel",
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
                        max_length=MEMORY_FACT_MAX_CHARS,
                        source_hint="user_message",
                    ),
                    _parameter(
                        "memory_type",
                        "enum",
                        description="记忆类型",
                        enum=MEMORY_TYPES,
                        default="user_fact",
                    ),
                    _parameter(
                        "importance",
                        "number",
                        description="重要性 0~1",
                        min_value=0,
                        max_value=1,
                    ),
                ],
                semantic_validators=("content_within_budget",),
            ),
            permission=PermissionProfile(level="normal", scope=("memory",)),
            side_effects=("write_memory",),
            idempotency="keyed",
            priority=30,
            tags=("memory",),
            memory_policy_key="builtin.memory.save",
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
                        max_length=OBJECT_NAME_MAX_CHARS,
                        source_hint="user_message",
                    ),
                    _parameter(
                        "category",
                        "enum",
                        description="物品类别（缺省由名称推断）",
                        enum=OBJECT_CATEGORIES,
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
            memory_policy_key="world.object.create",
            observability_fields=("object", "category", "quantity", "location"),
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
                        max_length=OBJECT_NAME_MAX_CHARS,
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
                semantic_validators=("object_in_inventory", "location_exists"),
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
                        max_length=OBJECT_NAME_MAX_CHARS,
                        source_hint="user_message",
                    ),
                    _parameter("action", "string", description="使用动作细分"),
                    _parameter(
                        "items",
                        "array",
                        description="批量消耗清单（object 物品参照 + quantity 数量）",
                    ),
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
                        enum=ENVIRONMENT_DIMENSIONS,
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
            description="对外部信息做检索查询；当前无可用的检索来源，调用即得明确降级结果。",
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
                        max_length=SEARCH_QUERY_MAX_CHARS,
                        source_hint="user_message",
                    )
                ],
                semantic_validators=("content_within_budget",),
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
            description="留一条行动 note 并在回复里自然提及（不外发、走既有到期汇报通道）。",
            when_to_use="需要把信息留给用户、且不需要经外部通道时使用",
            when_not_to_use="需要真正外发到用户手机时不要使用（应选通道工具）",
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
                        max_length=NOTIFICATION_CONTENT_MAX_CHARS,
                        source_hint="user_message",
                    )
                ],
                semantic_validators=("content_within_budget",),
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
            memory_policy_key="builtin.notification.send",
            observability_fields=("content",),
        ),
        ToolDefinition(
            id=CHANNEL_SEND_TOOL_ID,
            name="飞书通道发送",
            description="经飞书通道向已授权收件人发送消息（复用既有出站契约与文本切分）。",
            when_to_use="需要经飞书通道真正触达用户时使用",
            when_not_to_use="只想留个想法、不真正外发时不要使用",
            namespace="channel",
            capability=CHANNEL_CAPABILITY_NAME,
            action=CHANNEL_SEND_ACTION,
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "content",
                        "string",
                        required=True,
                        description="消息正文",
                        max_length=CHANNEL_TEXT_MAX_CHARS,
                        source_hint="user_message",
                    ),
                    _parameter(
                        "recipient",
                        "string",
                        required=True,
                        description="收件人外部身份（须在已授权名单内）",
                        source_hint="channel_identity",
                    ),
                ],
                semantic_validators=("recipient_authorized", "content_within_budget"),
            ),
            permission=PermissionProfile(
                level="sensitive",
                scope=(CHANNEL_SCOPE,),
                confirm="first_time",
                requires_online=True,
                audit=True,
            ),
            status=_channel_status(settings),
            side_effects=("send_external",),
            idempotency="keyed",
            priority=100,
            tags=("channel", "feishu"),
            memory_policy_key="channel.feishu.send",
            observability_fields=("content", "recipient"),
        ),
        ToolDefinition(
            id="builtin.ledger.record",
            name="记一笔账",
            description="把一笔结构化收支写入账本（整数分、append-only、幂等），拒绝自由文本入参。",
            when_to_use="用户给出明确金额与方向、需要落账时使用",
            when_not_to_use="金额缺失或只是闲聊消费话题时不要使用",
            namespace="builtin",
            capability="ledger",
            action="record",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "amount_minor",
                        "integer",
                        required=True,
                        description="金额（整数分，必须为正）",
                        min_value=1,
                    ),
                    _parameter(
                        "direction",
                        "enum",
                        required=True,
                        description="收支方向",
                        enum=LEDGER_DIRECTIONS,
                    ),
                    _parameter(
                        "source",
                        "enum",
                        required=True,
                        description="账目来源",
                        enum=LEDGER_SOURCES,
                    ),
                    _parameter(
                        "idempotency_key",
                        "string",
                        required=True,
                        description="幂等键（至少 8 位）",
                        min_length=LEDGER_IDEMPOTENCY_MIN_LENGTH,
                    ),
                    _parameter("currency", "string", description="币种", default="CNY"),
                    _parameter("category_id", "string", description="类目 id"),
                    _parameter("account_id", "string", description="账户 id"),
                    _parameter(
                        "occurred_at",
                        "datetime",
                        description="发生时间",
                        format_="iso8601",
                    ),
                    _parameter(
                        "merchant",
                        "string",
                        description="商户",
                        max_length=LEDGER_MERCHANT_MAX_CHARS,
                    ),
                    _parameter(
                        "note",
                        "string",
                        description="备注",
                        max_length=LEDGER_NOTE_MAX_CHARS,
                    ),
                    _parameter("source_ref", "string", description="来源引用"),
                ]
            ),
            permission=PermissionProfile(level="normal", scope=("ledger",)),
            side_effects=("irreversible",),
            idempotency="keyed",
            priority=35,
            tags=("ledger", "write"),
            observability_fields=("amount_minor", "direction", "source"),
        ),
        ToolDefinition(
            id="builtin.ledger.query",
            name="查询账本",
            description="按期间聚合查询账本（只读，数字只来自结构化字段，零 LLM）。",
            when_to_use="用户询问花了多少、收入多少等账目汇总时使用",
            when_not_to_use="需要修改或撤销账目时不要使用",
            namespace="builtin",
            capability="ledger",
            action="query",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "period",
                        "enum",
                        required=True,
                        description="统计期间",
                        enum=LEDGER_PERIODS,
                    ),
                    _parameter("category_id", "string", description="类目 id"),
                    _parameter("account_id", "string", description="账户 id"),
                    _parameter("limit", "integer", description="条目上限", min_value=1),
                ]
            ),
            permission=PermissionProfile(
                level="safe",
                scope=("ledger",),
                override_reason="只读账本聚合无副作用，按只读工具降级到命名空间下限之下",
            ),
            side_effects=("read",),
            idempotency="natural",
            priority=37,
            tags=("ledger", "read"),
            observability_fields=("period",),
        ),
        ToolDefinition(
            id="builtin.ledger.revise",
            name="冲正账目",
            description="对已入账条目做冲正（append-only 反向条目），原行永不改写。",
            when_to_use="用户指出某笔记错、要求撤销或订正时使用",
            when_not_to_use="只是查询账目时不要使用",
            namespace="builtin",
            capability="ledger",
            action="revise",
            input_schema=ToolSchema(
                parameters=[
                    _parameter(
                        "entry_id",
                        "string",
                        required=True,
                        description="被冲正条目 id",
                    ),
                    _parameter(
                        "reason",
                        "string",
                        required=True,
                        description="冲正原因",
                        max_length=LEDGER_REASON_MAX_CHARS,
                    ),
                    _parameter(
                        "idempotency_key",
                        "string",
                        required=True,
                        description="幂等键（至少 8 位）",
                        min_length=LEDGER_IDEMPOTENCY_MIN_LENGTH,
                    ),
                ]
            ),
            permission=PermissionProfile(level="normal", scope=("ledger",)),
            side_effects=("irreversible",),
            idempotency="keyed",
            priority=36,
            tags=("ledger", "write"),
            observability_fields=("entry_id", "reason"),
        ),
    )


def definitions(settings: Any = None) -> tuple[ToolDefinition, ...]:
    """§4.1 `definitions()`：供快照测试与注册使用的声明全集（顺序即 priority 顺序）。"""
    return _definitions(settings)


def observation_keys(tool_id: str) -> dict[str, str]:
    """§4.3 `keys_for(tool_id)`：`{payload_key: observation_key}`；未声明返回空映射。"""
    return dict(TOOL_OBSERVATION_KEYS.get(tool_id, {}))


def _capability_for(definition: ToolDefinition):
    """能力实现：优先全局注册表；通道能力在通道关闭时以单例充当声明期校验依据。"""
    capability = get_capability_registry().get(definition.capability)
    if capability is not None:
        return capability
    if definition.capability == CHANNEL_CAPABILITY_NAME:
        return get_channel_capability()
    return None


def register_all(registry) -> None:
    """§4.1 `register_all(registry)`：逐条注册（七项校验仍在 `ToolRegistry.register` 内）。"""
    for definition in definitions():
        registry.register(definition, _capability_for(definition))
