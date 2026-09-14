"""亚丝娜工具资产（V2.4.0 TOOL-004 §2.2 工具面投影 / TOOL-005 §4.3 确认话术与确认词表
/ TOOL-008 §2.2 工具结果记忆内容模板 / TOOL-010 §2.2 语义文案、观察键、不可用话术）。

纯数据：无 IO、无 LLM、无状态；投影逻辑在 `app/services/tool/surface.py`，
确认判定与话术装配在 `app/services/tool/permission.py` 与 `confirmation.py`，
记忆分层与候选构造在 `app/services/tool/memory_policy.py`，
观察键映射与效果归一的消费方是 `app/services/tool/normalizer.py`。
资产只回答"哪些 Profile / 时段 / 场景 / 关系阶段该裁掉什么"（投影）、
"哪些说法算点头或摇头"（确认词表）、"话术长什么样"（话术模板）、
"沉淀进记忆时这句话怎么写"（记忆内容模板）、"这个工具在角色眼里是什么"（语义文案）、
"结果里哪些字段值得留成事实"（观察键）与"做不成的时候我怎么说"（失败话术），
不回答"怎么裁""怎么判""怎么执行"。
"""

from dataclasses import dataclass

RUN_KIND_FOREGROUND_CHAT = "foreground_chat"
RUN_KIND_AUTONOMOUS_TICK = "autonomous_tick"
RUN_KIND_EVENT_DRIVEN = "event_driven"


@dataclass(frozen=True)
class SurfaceRule:
    """Run Profile 维度规则（§2.2）：整命名空间 / 标签 / 副作用集剔除与上限覆盖。"""

    run_kind: str
    exclude_namespaces: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()
    exclude_side_effects: tuple[str, ...] = ()
    max_tools: int | None = None
    reason: str = ""


SURFACE_RULES: dict[str, SurfaceRule] = {
    RUN_KIND_FOREGROUND_CHAT: SurfaceRule(
        run_kind=RUN_KIND_FOREGROUND_CHAT,
        reason="foreground_chat 前台对话：工具面不按 Profile 维度裁剪",
    ),
    RUN_KIND_AUTONOMOUS_TICK: SurfaceRule(
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        exclude_namespaces=("channel",),
        reason="autonomous_tick 无用户在线，不投放通道类工具",
    ),
    RUN_KIND_EVENT_DRIVEN: SurfaceRule(
        run_kind=RUN_KIND_EVENT_DRIVEN,
        exclude_side_effects=("write_world", "write_memory", "send_external", "irreversible"),
        reason="event_driven 只保留只读工具",
    ),
}

DEFAULT_SURFACE_RULE = SurfaceRule(
    run_kind="",
    reason="未注册 Run Profile：不做 Profile 维度裁剪",
)

LATE_NIGHT_PARTS: tuple[str, ...] = ("late_night",)

LATE_NIGHT_EXCLUDE_NAMESPACES: tuple[str, ...] = ("channel",)
LATE_NIGHT_EXCLUDE_TAGS: tuple[str, ...] = ("social",)

NEUTRAL_TONE_BIAS = "neutral"

RELAXED_TONE_BIASES: tuple[str, ...] = ("casual", "intimate", "playful", "relaxed")

FOCUSED_TONE_BIASES: tuple[str, ...] = ("focused", "formal", "work")

AMBIENT_TAG = "ambient"

SCENE_EXCLUDE_TAGS_BY_TONE: dict[str, tuple[str, ...]] = {
    tone: (AMBIENT_TAG,) for tone in FOCUSED_TONE_BIASES
}

RELATIONSHIP_STAGE_ORDER: tuple[str, ...] = (
    "stranger",
    "friend",
    "close_friend",
    "partner",
)

INTIMATE_TAG = "intimate"

INTIMATE_MIN_STAGE = "friend"

WORLD_NAMESPACE = "world"

CHANNEL_NAMESPACE = "channel"

TOOL_SEMANTIC_TEXT_MAX_CHARS = 120

TOOL_SEMANTIC_TEXT: dict[str, str] = {
    "builtin.reminder.create": "在将来的某个时刻叫住你，把这件事再说一遍给你听。",
    "builtin.reminder.cancel": "把之前答应过的那条提醒收回来，不再到点打扰你。",
    "builtin.memory.save": "把你说过、要我长期记住的事写进我的长期记忆里。",
    "world.object.create": "在世界里替你准备好一件东西，并把它放在该在的地方。",
    "world.object.move": "把你手里那件东西挪到另一个地方去。",
    "world.object.use": "拿起已有的东西用一次，看看会发生什么。",
    "world.env.query": "看看现在几点、天色如何、外面是什么天气。",
    "builtin.search.query": "向外面的世界打听一件事（我还没有可用的消息来源）。",
    "builtin.notification.send": "在手边留一张字条，等你回来时亲口对你说。",
    "channel.feishu.send": "经飞书给你递一句话，这条会真的送到你手上。",
}

TOOL_OBSERVATION_KEYS: dict[str, dict[str, str]] = {
    "builtin.reminder.create": {
        "world_event_id": "world.event_id",
        "due_at": "time.due_at",
    },
    "builtin.reminder.cancel": {"cancelled": "world.cancelled_count"},
    "builtin.memory.save": {"memory_id": "memory.id"},
    "world.object.create": {
        "object_id": "world.object_id",
        "location_id": "world.location_id",
    },
    "world.object.move": {
        "object_id": "world.object_id",
        "location_id": "world.location_id",
    },
    "world.object.use": {
        "object_id": "world.object_id",
        "location_id": "world.location_id",
    },
    "world.env.query": {
        "weather": "env.weather",
        "part_of_day": "env.part_of_day",
        "location": "env.location",
    },
    "builtin.search.query": {
        "result_count": "search.result_count",
        "untrusted": "search.untrusted",
        "results": "search.results",
    },
    "builtin.notification.send": {"note_created": "note.created"},
    "channel.feishu.send": {"external_message_id": "external.message_id"},
}

TOOL_UNAVAILABLE_TOOL_IDS: tuple[str, ...] = ("builtin.search.query",)

TOOL_UNAVAILABLE_REASON = "unavailable:source_not_configured"

TOOL_FAILURE_TEXT_MAX_CHARS = 60

TOOL_FAILURE_TEXT: dict[str, str] = {
    "builtin.search.query": "我还打听不到外面的消息，只能拿我知道的和你说。",
    "channel.feishu.send": "这条我没能送出去，等下再试一次好吗？",
    "builtin.notification.send": "这条我没能替你记下来，你再说一次好吗？",
}

CHANNEL_FAILURE_TEXT: dict[str, str] = {
    "not_found": "我没找到对应的收件人，这条消息没送出去。",
    "auth": "我这边通道的钥匙失效了，这条没能送出去。",
    "rate_limited": "发得太急被通道挡了一下，等下我再试。",
    "timeout": "通道那头一直没回我，这条先不算送出去。",
    "server_error": "通道那头出了点状况，这条我先留着。",
    "client_error": "通道没收下这条，我待会儿再试一次。",
    "disabled": "通道现在是关着的，这条我送不出去。",
    "invalid_request": "这条的格式通道不认，没送出去。",
    "unknown": "送消息时出了点意外，我没算它成功。",
}

# 外部 API 工具失败话术（TOOL-011 §4.2）：键为失败原因分类，工具 id 由清单动态声明，
# 故按 reason_kind 而非 tool_id 归档。只谈"没办成"，不透出域名 / 凭据 / 状态码细节。
EXT_API_FAILURE_TEXT: dict[str, str] = {
    "credential_missing": "我还没拿到这个服务的钥匙，这次先不查了。",
    "host_not_allowed": "这个地址不在我能去的名单里，我没有发出去。",
    "manifest_unresolved": "我暂时不知道要对接哪个外部服务，这次先算了。",
    "external_api_disabled": "外部服务现在是关着的，我这次查不了。",
    "network_error": "外面那头没接上，这次没查到结果。",
    "http_status": "外部服务这次没给我结果，我先按落空处理。",
    "request_timeout": "外面那头一直没回我，这次先不算数。",
    "unexpected_error": "查外部消息时出了点意外，我没算它成功。",
}

TOOL_SURFACE_RULES: dict[str, SurfaceRule] = SURFACE_RULES


def known_tone_biases() -> frozenset[str]:
    """已注册的场景语气（含中性档）：未知语气按保守处理（不做场景维度裁剪）。"""
    return frozenset(
        {NEUTRAL_TONE_BIAS, *RELAXED_TONE_BIASES, *FOCUSED_TONE_BIASES}
    )


def relationship_stage_rank(stage: str) -> int | None:
    """关系阶段序数；未知阶段返回 None（保守：不裁剪）。"""
    try:
        return RELATIONSHIP_STAGE_ORDER.index(stage)
    except ValueError:
        return None


def intimate_min_stage_rank() -> int:
    return RELATIONSHIP_STAGE_ORDER.index(INTIMATE_MIN_STAGE)


@dataclass(frozen=True)
class ConfirmPromptTemplate:
    """确认话术模板（TOOL-005 §2.3）：有素材与无素材两态，均为角色语气。"""

    with_subject: str
    without_subject: str


CONFIRM_PROMPT_MAX_CHARS = 60

CONFIRM_SUBJECT_MAX_CHARS = 20

CONFIRM_PROMPT_FALLBACK = "这件事需要你点头我才敢做，可以吗？"

CONFIRM_PROMPT_TEMPLATES: dict[str, ConfirmPromptTemplate] = {
    "channel.feishu.send": ConfirmPromptTemplate(
        with_subject="要我现在把「{subject}」发出去吗？",
        without_subject="要我现在把这条消息发出去吗？",
    ),
    "builtin.notification.send": ConfirmPromptTemplate(
        with_subject="要我把「{subject}」发给你吗？",
        without_subject="要我现在给你发条消息吗？",
    ),
}

CONFIRM_PROMPT_DEFAULT = ConfirmPromptTemplate(
    with_subject="要我现在就去做「{subject}」吗？你说好我才动手。",
    without_subject="这件事我想先跟你确认一下，可以吗？",
)

TOOL_CONFIRM_PROMPTS: dict[str, ConfirmPromptTemplate] = CONFIRM_PROMPT_TEMPLATES

CONFIRM_APPROVE_LEXICON: tuple[str, ...] = (
    "好",
    "行",
    "可以",
    "发吧",
    "嗯",
    "对",
    "确认",
    "就这样",
    "帮我发",
    "好的",
)

CONFIRM_DENY_LEXICON: tuple[str, ...] = (
    "不用了",
    "算了",
    "别发",
    "取消",
    "不要",
    "先不发",
    "不可以",
    "不行",
    "先别",
    "别",
)

CONFIRM_WORD_MAX_CONTENT_CHARS = 12

CONFIRM_LEXICON_MIN_WORDS = 5

TOOL_MEMORY_TEMPLATES: dict[str, str] = {
    "builtin.reminder.create": "用户请我提醒他：{content}",
    "builtin.reminder.cancel": "用户不想再被提醒：{target}",
    "builtin.memory.save": "用户告诉我：{fact}",
    "world.object.create": "用户请我准备：{object}",
    "builtin.notification.send": "我主动提醒了用户：{content}",
    "channel.feishu.send": "我主动给用户发了消息：{content}",
}

TOOL_MEMORY_FAILURE_TEMPLATE = "上次没能帮用户完成：{content}"


def render(policy_key: str, params: dict, *, failed: bool = False) -> str:
    """记忆内容渲染（TOOL-008 §4.3）：`failed=True` 用未完成语义，无模板或缺参返回空串。"""
    template = TOOL_MEMORY_TEMPLATES.get(policy_key)
    if template is None:
        return ""
    values = {key: str(value) for key, value in params.items()}
    try:
        content = template.format(**values)
    except (KeyError, IndexError):
        return ""
    if failed:
        return TOOL_MEMORY_FAILURE_TEMPLATE.format(content=content)
    return content
