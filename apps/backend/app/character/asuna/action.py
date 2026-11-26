"""亚丝娜行动资产（V9-001；V2.4.0 TOOL-006 §2.3 增补自治参数模板）。

行动"设定"与行动"状态"分离：本模块只含词表、参数表、能力映射、
记忆模板、关系信号映射、完成时宣称模式表与自治参数模板，全部为数据定义；
检出 / 闸门 / 执行逻辑属 services 与 application 层。
自治参数模板只回答"没人在线时打算做什么、缺参怎么按工具声明补齐"（纯函数），
不回答"什么时候产行动"（`autonomy_policy`）与"怎么执行"（`action_engine`）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.tool import ToolBinding, ToolSchema

# 触发词表（planner.md §1.1）：action_type → 触发模式列表。
# 纪律：祈使优先（触发词 + 用户主语"我/帮我/替我"才命中）；问句守卫由检出器执行。
ACTION_TRIGGER_LEXICON: dict[str, tuple[str, ...]] = {
    "create_reminder": (
        "提醒我",
        "记得提醒",
        "设个提醒",
        "设个闹钟",
        "到点叫我",
        "别让我忘",
        "帮我记一下时间",
    ),
    "cancel_reminder": (
        "不用提醒了",
        "取消提醒",
        "别提醒了",
        "算了别提醒",
    ),
    "remember_fact": (
        "记住",
        "帮我记着",
        "帮我记住",
        "我生日是",
        "我的生日是",
    ),
    "create_object": (
        "帮我买",
        "去买",
        "帮我准备一个",
        "帮我拿一个",
        "给我买",
    ),
    "move_object": (
        "帮我放到",
        "帮我放进",
        "把…放到",
        "收到…里",
    ),
    "use_object": (
        "帮我切开",
        "帮我吃掉",
        "帮我热一下",
        "热一下",
        "煮",
        "炒",
        "煎",
        "蒸",
        "炖",
        "加个",
        "加俩",
        "加两",
        "加点",
        "来个",
        "来点",
        "多加",
    ),
    "query_environment": (
        "今天天气",
        "外面多少度",
        "现在几点了",
        "现在天气怎么样",
    ),
    "query_search": (
        "帮我搜一下",
        "帮我查一下",
    ),
    "send_notification": (
        "通知我",
        "发消息提醒我",
    ),
    "record_ledger_entry": (
        "记账",
        "记一笔",
        "记下",
        "花了",
        "付了",
        "买了",
    ),
    "revise_ledger_entry": (
        "记错了",
        "撤掉",
        "撤销这笔",
        "冲正",
        "订正",
    ),
    "query_ledger": (
        "查一下账",
        "这个月花了多少",
        "本月消费",
    ),
}

# 词表优先级：一轮至多一个 intent，多条命中取优先级最高者（planner.md §1.1 纪律 3）。
ACTION_LEXICON_PRIORITY: tuple[str, ...] = (
    "cancel_reminder",
    "revise_ledger_entry",
    "record_ledger_entry",
    "create_reminder",
    "remember_fact",
    "create_object",
    "move_object",
    "use_object",
    "query_ledger",
    "query_environment",
    "query_search",
    "send_notification",
)

# 自带祈使语气的触发词（中文无主语祈使句，如"加俩个蛋"）：命中即视为祈使，
# 不再要求句中出现"我/帮我"等主语标记。
SELF_IMPERATIVE_TRIGGERS: frozenset[str] = frozenset(
    {
        "加个",
        "加俩",
        "加两",
        "加点",
        "来个",
        "来点",
        "多加",
    }
)

# 各行动类型的必需参数表（planner.md §1.2）。
REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "create_reminder": ("content", "due_at"),
    "cancel_reminder": ("target",),
    "remember_fact": ("fact",),
    "create_object": ("object",),
    "move_object": ("object", "location"),
    "use_object": ("object",),
    "query_environment": (),
    "query_search": ("query",),
    "send_notification": ("content",),
    "record_ledger_entry": ("amount_minor", "direction", "source", "idempotency_key"),
    "revise_ledger_entry": ("entry_id", "reason", "idempotency_key"),
    "query_ledger": ("period",),
}

# 能力映射（planner.md §3）：ActionType → (capability, action)。
ACTION_CAPABILITY_MAP: dict[str, tuple[str, str]] = {
    "create_reminder": ("reminder", "create"),
    "cancel_reminder": ("reminder", "cancel"),
    "remember_fact": ("memory", "save"),
    "create_object": ("world_action", "create"),
    "move_object": ("world_action", "move"),
    "use_object": ("world_action", "use"),
    "query_environment": ("environment_query", "query"),
    "query_search": ("search", "query"),
    "send_notification": ("notification", "send"),
    "record_ledger_entry": ("ledger", "record"),
    "revise_ledger_entry": ("ledger", "revise"),
    "query_ledger": ("ledger", "query"),
}

# 工具身份映射（V2.4.0 TOOL-004 §2.3）：ActionType → 工具 id 候选元组（一词多工具）。
# 与 ACTION_CAPABILITY_MAP 并列：总闸 off 时只读旧表，on 时经 ToolRegistry.resolve 取绑定。
ACTION_TOOL_MAP: dict[str, tuple[str, ...]] = {
    "create_reminder": ("builtin.reminder.create",),
    "cancel_reminder": ("builtin.reminder.cancel",),
    "remember_fact": ("builtin.memory.save",),
    "create_object": ("world.object.create",),
    "move_object": ("world.object.move",),
    "use_object": ("world.object.use",),
    "query_environment": ("world.env.query",),
    "query_search": ("builtin.search.query",),
    "send_notification": ("builtin.notification.send", "channel.feishu.send"),
    "record_ledger_entry": ("builtin.ledger.record",),
    "revise_ledger_entry": ("builtin.ledger.revise",),
    "query_ledger": ("builtin.ledger.query",),
}

# 记账意图词表（PLA-009）：动词/短语 + 金额结构组合判定；反例见 detector。
LEDGER_RECORD_TRIGGERS: tuple[str, ...] = (
    "记账",
    "记一笔",
    "记下",
    "花了",
    "花费",
    "花掉",
    "付了",
    "付款",
    "支付了",
    "买了",
    "买",
    "消费",
    "入账",
    "收到",
    "报销",
    "充了",
    "充值",
    "交了",
    "缴了",
    "吃了",
    "喝了",
    "打了车",
)
LEDGER_REVISE_TRIGGERS: tuple[str, ...] = (
    "记错",
    "记错了",
    "撤掉",
    "撤销",
    "冲正",
    "订正",
    "那笔不对",
    "这笔不对",
    "改一下账",
)
LEDGER_QUERY_TRIGGERS: tuple[str, ...] = (
    "查一下账",
    "查账",
    "这个月花了多少",
    "本月消费",
    "本月花了",
)
LEDGER_INCOME_MARKERS: tuple[str, ...] = (
    "收到",
    "报销",
    "工资",
    "奖金",
    "转入",
    "收入",
    "进账",
)
LEDGER_FALSE_POSITIVE_MARKERS: tuple[str, ...] = (
    "我记得",
    "记住我",
    "记忆里",
    "回忆",
    "记账本",
)

# 物品类目推断（world-integration.md §1 create_object 行）。
OBJECT_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "food": ("牛奶", "面包", "西瓜", "鸡蛋", "蛋糕", "水果", "菜"),
    "drink": ("咖啡", "茶", "果汁", "可乐", "水"),
    "tool": ("刀", "工具", "电池", "灯泡"),
    "furniture": ("椅子", "桌子", "架子"),
    "clothing": ("衣服", "外套", "围巾", "鞋子"),
    "device": ("手机", "耳机", "充电器"),
}


def infer_object_category(name: str) -> str:
    text = name.strip()
    for category, keywords in OBJECT_CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "misc"


# 记忆模板（memory-policy.md §5）：记忆是角色视角的叙事，不是日志。
ACTION_MEMORY_TEMPLATES: dict[str, str] = {
    "create_reminder": "用户请我提醒他：{content}",
    "cancel_reminder": "用户不想再被提醒：{target}",
    "remember_fact": "用户告诉我：{fact}",
    "create_object": "用户请我准备：{object}",
}

# 生日关键词（memory-policy.md §2 create_reminder 生日加权行）。
REMINDER_BIRTHDAY_KEYWORDS: tuple[str, ...] = ("生日", "birthday")

# 关系信号映射（relationship-impact.md §2，刻意收缩为两格）。
# (action_type, source, result_status) → (event_type, magnitude)；无行即不投递。
ACTION_RELATIONSHIP_MAP: dict[tuple[str, str, str], tuple[str, str]] = {
    ("create_reminder", "conversation", "succeeded"): ("user_help", "normal"),
    ("cancel_reminder", "conversation", "succeeded"): ("user_help", "normal"),
    ("remember_fact", "conversation", "succeeded"): ("user_help", "normal"),
    ("create_reminder", "autonomy", "succeeded"): ("user_care", "weak"),
    ("cancel_reminder", "autonomy", "succeeded"): ("user_care", "weak"),
    ("remember_fact", "autonomy", "succeeded"): ("user_care", "weak"),
    ("create_reminder", "plan", "succeeded"): ("user_care", "weak"),
    ("cancel_reminder", "plan", "succeeded"): ("user_care", "weak"),
    ("remember_fact", "plan", "succeeded"): ("user_care", "weak"),
}

# 完成时宣称模式表（tool-integration.md §5 ActionOverclaimRule，角色资产）。
COMPLETION_CLAIM_PATTERNS: tuple[str, ...] = (
    "已经设好",
    "已设好",
    "已经提醒",
    "已提醒",
    "已经记住",
    "已记住",
    "已经买好",
    "已买好",
    "已经准备好了",
    "已经完成",
    "已经帮你",
    "已经放好",
    "已经取消",
)

# 查询维度（query_environment 参数细分）。
ENVIRONMENT_QUERY_DIMENSIONS: tuple[str, ...] = ("weather", "temperature", "time", "lighting")

# 自治产行动映射（autonomy-integration.md §4）：自治裁决意图 → 可执行 ActionType。
# 分支由 autonomy_action_enabled 门控，默认关——开关开启且命中才求值，否则零路径。
PROACTIVE_ACTION_MAP: dict[str, str] = {
    "check_in": "create_reminder",
}


@dataclass(frozen=True)
class AutonomyParamTemplate:
    """自治产行动参数模板（TOOL-006 §2.3）：静态值 + 相对当前时刻的时间偏移（分钟）。"""

    values: dict[str, Any] = field(default_factory=dict)
    offsets_minutes: dict[str, int] = field(default_factory=dict)


# V9 固定模板（autonomy-integration.md §4）：工具层不可用时逐字节回退到此形态。
AUTONOMY_ACTION_PARAM_TEMPLATES: dict[str, AutonomyParamTemplate] = {
    "create_reminder": AutonomyParamTemplate(
        values={"content": "休息一下"},
        offsets_minutes={"due_at": 30},
    ),
}

# 参数的来源标记：声明为 `default` 者，缺省值一律取 `ToolParameter.default`
# （含显式 null），与 `user_message` 等"必须来自用户输入"的标记区分（TOOL-006 §4.4）。
SOURCE_HINT_DEFAULT = "default"


def fill_declared_defaults(
    params: Mapping[str, Any], schema: ToolSchema
) -> dict[str, Any]:
    """按工具 `input_schema` 的 `default` / `source_hint` 补齐缺参（不覆盖既有键）。

    声明了 `default` 或缺省来源标记为 `default` 的缺参取声明值；
    其余缺参（含 `user_message` 来源）保持缺失——由检出器 / 参数校验层负责补问。
    """
    filled = dict(params)
    for parameter in schema.parameters:
        if parameter.name in filled:
            continue
        if parameter.default is None and parameter.source_hint != SOURCE_HINT_DEFAULT:
            continue
        filled[parameter.name] = parameter.default
    return filled


def build_autonomy_action_params(
    action_type: str, now: datetime, binding: ToolBinding | None
) -> dict[str, Any]:
    """自治产行动参数模板（TOOL-006 §4.4）：无模板返回空参。

    `binding` 为 None（总闸 off / 工具不在自治工具面内）→ 回退 V9 固定模板（既有行为）；
    `binding` 存在 → 固定模板 + 按该工具 `input_schema` 补齐声明缺参。
    """
    template = AUTONOMY_ACTION_PARAM_TEMPLATES.get(action_type)
    if template is None:
        return {}
    params: dict[str, Any] = dict(template.values)
    for name, offset_minutes in template.offsets_minutes.items():
        params[name] = (now + timedelta(minutes=offset_minutes)).isoformat()
    if binding is None:
        return params
    return fill_declared_defaults(params, binding.definition.input_schema)
