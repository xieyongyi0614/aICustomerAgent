"""V7.5 评估上下文收集器（evaluation-model.md §4 / architecture.md §2①）。

从 PostProcessContext 与既有仓储切片构造 EvaluationContext 与有界 context digest；
只读、零写操作，任一切片缺失容错（None/空值，不抛）。
"""

import logging
from dataclasses import dataclass, field

from app.application.post_process import PostProcessContext
from app.core.settings import get_settings
from app.models.behavior_strategy import ActionBudget
from app.services import behavior_engine

logger = logging.getLogger(__name__)

DIGEST_USER_MESSAGE_CHARS = 200
DIGEST_REPLY_CHARS = 400
DIGEST_RECENT_CHARS = 120
DIGEST_MEMORY_CHARS = 40
DIGEST_RECENT_MESSAGES = 6
DIGEST_MEMORIES = 5

RECENT_TURNS_FOR_WINDOW = 6


@dataclass
class RecentMessage:
    role: str
    content: str
    mood_after: str | None = None


@dataclass
class EmotionSlice:
    mood_before: str | None = None
    mood_after: str | None = None
    intensity: float | None = None
    event: str | None = None
    magnitude: str | None = None
    cause: str | None = None


@dataclass
class BehaviorSlice:
    max_action_desc: int = 0
    physical_contact: str = "none"
    emotion_expression: str = "natural"
    strategy: str = ""
    observed_action_count: int = 0
    observed_contact_level: str = "none"


@dataclass
class StateSlice:
    mood: str | None = None
    energy: float | None = None
    stage: str | None = None
    intimacy: float | None = None


@dataclass
class MemoryRef:
    id: str
    type: str
    content: str


@dataclass
class ProactiveSlice:
    action_id: str = ""
    trigger_type: str = ""
    intention: str = ""
    reason: str = ""
    delivered_at: object | None = None
    payload_text: str = ""


@dataclass
class EvaluationContext:
    subject: str
    subject_id: str
    session_id: str
    user_id: str
    character_id: str = "asuna"
    mode: str = "default"
    stage: str = "friend"
    user_message: str = ""
    reply: str = ""
    recent_messages: list[RecentMessage] = field(default_factory=list)
    injected_memories: list[MemoryRef] = field(default_factory=list)
    emotion: EmotionSlice = field(default_factory=EmotionSlice)
    behavior: BehaviorSlice | None = None
    behavior_history: list[list[str]] = field(default_factory=list)
    state: StateSlice = field(default_factory=StateSlice)
    proactive: ProactiveSlice | None = None
    request_id: str = ""
    fidelity: str = "live"


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return text[:limit]


def collect_turn_context(ctx: PostProcessContext) -> EvaluationContext:
    settings = get_settings()
    context = EvaluationContext(
        subject="turn",
        subject_id=str(getattr(ctx.trace, "turn_id", None) or ctx.current_turn or ""),
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        mode=getattr(ctx.state, "mode", "default"),
        stage=getattr(ctx.state.relationship_state, "stage", "friend"),
        user_message=_clip(ctx.user_input, DIGEST_USER_MESSAGE_CHARS),
        reply=_clip(ctx.ai_reply, DIGEST_REPLY_CHARS),
        request_id=getattr(ctx.trace, "request_id", "") or "",
    )
    context.recent_messages = _collect_recent_messages(ctx)
    context.injected_memories = _collect_injected_memories(ctx.state)
    context.emotion = _collect_emotion(ctx)
    context.state = _collect_state(ctx.user_id, ctx.state)
    if ctx.behavior is not None:
        context.behavior = _collect_behavior(ctx)
        context.behavior_history = _collect_behavior_history(ctx.session_id, settings)
    return context


def _collect_recent_messages(ctx: PostProcessContext) -> list[RecentMessage]:
    try:
        from app.services import conversation_service

        history = conversation_service.load_window(ctx.session_id)
    except Exception:
        logger.exception("近期消息切片读取失败，digest 降级")
        return []
    emotion_rows = []
    try:
        from app.repositories import emotion_history_repository

        emotion_rows = emotion_history_repository.list_recent(ctx.user_id, limit=RECENT_TURNS_FOR_WINDOW)
    except Exception:
        logger.exception("情绪史切片读取失败，mood 配对降级")
    moods = [row.mood_after for row in emotion_rows]
    recent: list[RecentMessage] = []
    ai_index = 0
    for message in reversed(history):
        mood_after = None
        if message.role == "ai" and ai_index < len(moods):
            mood_after = moods[ai_index]
            ai_index += 1
        recent.append(
            RecentMessage(
                role=message.role,
                content=_clip(message.content, DIGEST_RECENT_CHARS),
                mood_after=mood_after,
            )
        )
        if len(recent) >= DIGEST_RECENT_MESSAGES:
            break
    recent.reverse()
    return recent


def _collect_injected_memories(state) -> list[MemoryRef]:
    memories = getattr(state, "memories", None) or []
    refs = []
    for memory in memories[:DIGEST_MEMORIES]:
        refs.append(
            MemoryRef(
                id=str(getattr(memory, "id", "")),
                type=str(getattr(memory, "type", "")),
                content=_clip(getattr(memory, "content", ""), DIGEST_MEMORY_CHARS),
            )
        )
    return refs


def _collect_emotion(ctx: PostProcessContext) -> EmotionSlice:
    try:
        from app.repositories import character_state_repository, emotion_history_repository

        rows = emotion_history_repository.list_recent(ctx.user_id, limit=1)
        state = character_state_repository.get_state(ctx.user_id)
        latest = rows[0] if rows else None
        event = ctx.analysis.emotion_event if ctx.analysis is not None else None
        return EmotionSlice(
            mood_before=getattr(latest, "mood_before", None),
            mood_after=getattr(latest, "mood_after", None),
            intensity=getattr(state, "intensity", None),
            event=getattr(event, "type", None),
            magnitude=getattr(event, "magnitude", None),
            cause=getattr(event, "cause", None) or None,
        )
    except Exception:
        logger.exception("情绪切片读取失败，digest 降级")
        return EmotionSlice()


def _collect_state(user_id: str, state) -> StateSlice:
    try:
        from app.repositories import relationship_repository

        relationship = relationship_repository.get_relationship(user_id)
    except Exception:
        logger.exception("关系切片读取失败，digest 降级")
        relationship = None
    character = getattr(state, "character_state", None)
    return StateSlice(
        mood=getattr(character, "mood", None),
        energy=getattr(character, "energy", None),
        stage=getattr(relationship, "stage", None) or getattr(state.relationship_state, "stage", None),
        intimacy=getattr(relationship, "intimacy", None),
    )


def _collect_behavior(ctx: PostProcessContext) -> BehaviorSlice:
    directive = ctx.behavior
    budget: ActionBudget = directive.budget
    observation = behavior_engine.observe_budget(ctx.ai_reply, budget)
    return BehaviorSlice(
        max_action_desc=budget.max_action_desc,
        physical_contact=budget.physical_contact,
        emotion_expression=budget.emotion_expression,
        strategy=directive.strategy.strategy,
        observed_action_count=observation["action_count"],
        observed_contact_level=observation["contact_level"],
    )


def _collect_behavior_history(session_id: str, settings) -> list[list[str]]:
    """近窗每轮动作类别（behavior-evaluation.md §3.3 轻量重放，仅计数不重跑管线）。"""
    try:
        from app.services import conversation_service
        from app.services.evaluation_rules import lexicons

        history = conversation_service.load_window(session_id)
        ai_messages = [m.content for m in history if m.role == "ai" and m.content]
        window = ai_messages[-settings.evaluation_behavior_monotony_window :]
        return [lexicons.classify_actions(text) for text in window]
    except Exception:
        logger.exception("行为历史切片读取失败，单调窗降级")
        return []


def build_digest(context: EvaluationContext) -> dict:
    digest = {
        "user_message": context.user_message,
        "reply": context.reply,
        "recent_messages": [
            {"role": m.role, "content": m.content, "mood_after": m.mood_after}
            for m in context.recent_messages
        ],
        "injected_memories": [
            {"id": m.id, "type": m.type, "content": m.content}
            for m in context.injected_memories
        ],
        "emotion": {
            "mood_before": context.emotion.mood_before,
            "mood_after": context.emotion.mood_after,
            "intensity": context.emotion.intensity,
            "event": context.emotion.event,
            "magnitude": context.emotion.magnitude,
            "cause": context.emotion.cause,
        },
        "state": {
            "mood": context.state.mood,
            "energy": context.state.energy,
            "stage": context.state.stage,
            "intimacy": context.state.intimacy,
        },
        "proactive": _proactive_digest(context.proactive),
    }
    if context.behavior is not None:
        digest["behavior"] = {
            "max_action_desc": context.behavior.max_action_desc,
            "observed_action_count": context.behavior.observed_action_count,
            "contact_level": context.behavior.observed_contact_level,
            "strategy": context.behavior.strategy,
            "emotion_expression": context.behavior.emotion_expression,
        }
    return _truncate_digest(digest, get_settings().evaluation_max_digest_chars)


def _proactive_digest(proactive: ProactiveSlice | None) -> dict | None:
    if proactive is None:
        return None
    return {
        "action_id": proactive.action_id,
        "trigger_type": proactive.trigger_type,
        "intention": proactive.intention,
        "reason": proactive.reason,
        "delivered_at": str(proactive.delivered_at) if proactive.delivered_at else None,
        "payload_text": _clip(proactive.payload_text, DIGEST_REPLY_CHARS),
    }


_LOW_PRIORITY_KEYS = ("injected_memories", "recent_messages")


def _truncate_digest(digest: dict, max_chars: int) -> dict:
    import json

    def _size() -> int:
        return len(json.dumps(digest, ensure_ascii=False))

    lists = {key: list(digest.get(key) or []) for key in _LOW_PRIORITY_KEYS}
    while _size() > max_chars and any(lists.values()):
        for key in _LOW_PRIORITY_KEYS:
            if lists[key]:
                lists[key].pop()
                digest[key] = lists[key]
                break
    while _size() > max_chars and len(digest.get("reply", "")) > 50:
        digest["reply"] = digest["reply"][: len(digest["reply"]) // 2]
    while _size() > max_chars and len(digest.get("user_message", "")) > 20:
        digest["user_message"] = digest["user_message"][: len(digest["user_message"]) // 2]
    return digest
