"""V7.5 评估上下文收集器（evaluation-model.md §4 / architecture.md §2①）。

从 PostProcessContext 与既有仓储切片构造 EvaluationContext 与有界 context digest；
只读、零写操作，任一切片缺失容错（None/空值，不抛）。
"""

import logging
from dataclasses import dataclass, field

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
    importance: float = 0.0


@dataclass
class ProactiveSlice:
    action_id: str = ""
    trigger_type: str = ""
    intention: str = ""
    reason: str = ""
    delivered_at: object | None = None
    payload_text: str = ""
    previous_delivered_at: object | None = None
    last_user_message_at: object | None = None
    episode_attempts: int = 1


@dataclass
class RelationshipSlice:
    before: dict | None = None
    after: dict | None = None
    applied: dict | None = None
    truncated: dict | None = None
    day_positive: dict | None = None
    day_negative: dict | None = None
    events: list = field(default_factory=list)
    signal_present: bool = False
    comfort_drift: float = 0.0
    conflict_status: str = "none"


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
    world: dict | None = None
    relationship: RelationshipSlice | None = None


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return text[:limit]


def collect_turn_context(ctx) -> EvaluationContext:
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
    context.world = _collect_world(ctx.user_id)
    context.relationship = _collect_relationship(ctx.user_id)
    return context


def _collect_relationship(user_id: str) -> RelationshipSlice | None:
    """V8.5 关系演化审计切片（内存审计，缺席为 None = 规则跳过）。"""
    try:
        from app.services import state_service

        audit = state_service.get_relationship_audit(user_id)
    except Exception:
        logger.exception("关系审计切片读取失败，relationship 规则降级")
        return None
    if not audit:
        return None
    return RelationshipSlice(
        before=_state_dims(audit.get("before")),
        after=_state_dims(audit.get("after")),
        applied=_delta_dims(audit.get("applied")),
        truncated=dict(audit.get("truncated") or {}),
        day_positive=_delta_dims(audit.get("day_positive")),
        day_negative=_delta_dims(audit.get("day_negative")),
        events=list(audit.get("events") or []),
        signal_present=bool(audit.get("signal_present")),
        comfort_drift=float(audit.get("comfort_drift") or 0.0),
        conflict_status=str(
            getattr(audit.get("after"), "conflict_status", "none") or "none"
        ),
    )


_RELATIONSHIP_DIMENSIONS = ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")


def _state_dims(state) -> dict | None:
    if state is None:
        return None
    return {dim: float(getattr(state, dim, 0.0)) for dim in _RELATIONSHIP_DIMENSIONS}


def _delta_dims(delta) -> dict | None:
    if delta is None:
        return None
    return {dim: float(getattr(delta, dim, 0.0)) for dim in _RELATIONSHIP_DIMENSIONS}


def _collect_world(user_id: str) -> dict | None:
    """V8 世界事实切片（只读）：评估 World Consistency 规则用；缺席为 None。"""
    try:
        from app.core.settings import get_settings as _settings
        from app.repositories import world_repository

        if not _settings().world_enabled:
            return None
        world = world_repository.get_world(user_id)
        if world is None:
            return None
        entities = world_repository.list_objects(world.world_id)
        return {
            "location": world.current_location,
            "objects": [
                {
                    "name": obj.name,
                    "state": obj.state,
                    "quantity": obj.quantity,
                    "status": obj.status.value,
                }
                for obj in entities
            ],
        }
    except Exception:
        logger.exception("世界切片读取失败，world 规则降级")
        return None


def _collect_recent_messages(ctx) -> list[RecentMessage]:
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
                importance=float(getattr(memory, "importance", 0.0) or 0.0),
            )
        )
    return refs


def _collect_emotion(ctx) -> EmotionSlice:
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


def _collect_behavior(ctx) -> BehaviorSlice:
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


def collect_proactive_context(action) -> EvaluationContext | None:
    """主动行为主体（autonomy-evaluation.md §1）：delivered 后由引擎调用，只读切片。"""
    if getattr(action, "status", "") != "delivered" or not getattr(
        action, "payload_text", None
    ):
        return None
    settings = get_settings()
    context = EvaluationContext(
        subject="proactive_action",
        subject_id=str(action.id),
        session_id=action.session_id,
        user_id=action.user_id,
        user_message="",
        reply=_clip(action.payload_text, DIGEST_REPLY_CHARS),
        request_id=str(action.id),
    )
    context.proactive = _collect_proactive_facts(action, settings)
    context.state = _collect_state(action.user_id, None)
    context.recent_messages = _collect_proactive_recent(action.session_id)
    return context


def _collect_proactive_facts(action, settings) -> ProactiveSlice:
    delivered_at = action.delivered_at
    previous_delivered_at = None
    episode_attempts = 1
    last_user_message_at = None
    try:
        from app.repositories import proactive_repository

        history = proactive_repository.list_delivered_history(action.user_id, limit=10)
        earlier = [
            row
            for row in history
            if row.id != action.id and row.delivered_at is not None
        ]
        if earlier and delivered_at is not None:
            previous_delivered_at = earlier[0].delivered_at
            window_minutes = settings.autonomy_min_interval_minutes * 2
            episode_attempts = 1 + sum(
                1
                for row in earlier
                if (delivered_at - row.delivered_at).total_seconds() / 60
                <= window_minutes
            )
    except Exception:
        logger.exception("主动历史切片读取失败，时机审计降级")
    try:
        from app.services import conversation_service

        window = conversation_service.load_window(action.session_id, max_messages=10)
        human_messages = [m for m in window if m.role == "human"]
        if human_messages:
            last_user_message_at = human_messages[-1].created_at
    except Exception:
        logger.exception("会话尾部切片读取失败，时机审计降级")
    return ProactiveSlice(
        action_id=str(action.id),
        trigger_type=action.trigger_type,
        intention=action.intention,
        reason=action.reason,
        delivered_at=delivered_at,
        payload_text=_clip(action.payload_text or "", DIGEST_REPLY_CHARS),
        previous_delivered_at=previous_delivered_at,
        last_user_message_at=last_user_message_at,
        episode_attempts=episode_attempts,
    )


def _collect_proactive_recent(session_id: str) -> list[RecentMessage]:
    try:
        from app.services import conversation_service

        window = conversation_service.load_window(
            session_id, max_messages=DIGEST_RECENT_MESSAGES
        )
    except Exception:
        logger.exception("主动近期消息切片读取失败，digest 降级")
        return []
    return [
        RecentMessage(role=m.role, content=_clip(m.content, DIGEST_RECENT_CHARS))
        for m in window
    ][-DIGEST_RECENT_MESSAGES:]


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
