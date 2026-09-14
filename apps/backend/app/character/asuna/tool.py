"""亚丝娜工具面投影资产（V2.4.0 TOOL-004 §2.2；architecture.md §4.1 投影规则表）。

纯数据：无 IO、无 LLM、无状态；投影逻辑在 `app/services/tool/surface.py`。
资产只回答"哪些 Profile / 时段 / 场景 / 关系阶段该裁掉什么"，
不回答"怎么裁"（那是 `ToolSurfacePolicy` 的职责）。
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
