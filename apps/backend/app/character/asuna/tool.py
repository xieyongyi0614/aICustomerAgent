"""亚丝娜工具资产（V2.4.0 TOOL-004 §2.2 工具面投影 / TOOL-005 §4.3 确认话术与确认词表
/ TOOL-008 §2.2 工具结果记忆内容模板）。

纯数据：无 IO、无 LLM、无状态；投影逻辑在 `app/services/tool/surface.py`，
确认判定与话术装配在 `app/services/tool/permission.py` 与 `confirmation.py`，
记忆分层与候选构造在 `app/services/tool/memory_policy.py`。
资产只回答"哪些 Profile / 时段 / 场景 / 关系阶段该裁掉什么"（投影）、
"哪些说法算点头或摇头"（确认词表）、"话术长什么样"（话术模板）与
"沉淀进记忆时这句话怎么写"（记忆内容模板），不回答"怎么裁"与"怎么判"。
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
