"""V7.5 上下文 digest 组装与有界截断。"""

from app.core.settings import get_settings

from app.services.evaluation.context.slices import (
    DIGEST_REPLY_CHARS,
    EvaluationContext,
    ProactiveSlice,
    _clip,
)

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

