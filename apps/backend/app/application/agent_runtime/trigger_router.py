"""Trigger Router（AGENT-001 §5.2）：四类触发源归一为 (run_kind, trigger_type)。"""

from app.core.settings import get_settings

_BACKGROUND_REASON_TO_TRIGGER = {
    "due_trigger": "schedule",
    "goal_work": "schedule",
    "goal_catchup": "schedule",
    "inactivity_eligible": "threshold",
}


def classify_channel_message() -> tuple[str, str]:
    """用户消息 → 前台 Run。"""
    return "foreground_chat", "channel_message"


def classify_background_trigger(user_id: str, now) -> tuple[str, str]:
    """后台工作发现 → (trigger_type, reason)；复用既有 _cycle_reason 判据。"""
    from app.application import life_loop

    reason = life_loop._cycle_reason(user_id, now)
    return _BACKGROUND_REASON_TO_TRIGGER.get(reason, "schedule"), reason


def classify_proactive_trigger(reason: str) -> str:
    """主动触发 reason → trigger_type（复用既有映射，零新触发类型）。"""
    return _BACKGROUND_REASON_TO_TRIGGER.get(reason, "schedule")


def escalation_whitelist() -> frozenset[str]:
    settings = get_settings()
    raw = settings.agent_event_escalation_types
    types = {t.strip() for t in raw.split(",") if t.strip()}
    types |= {
        t.strip()
        for t in (settings.world_event_escalation_types or "").split(",")
        if t.strip()
    }
    return frozenset(types)


def evaluate_event_escalation(event_type: str) -> bool:
    """事件预闸（0 LLM）：仅白名单内事件类型升级为完整 Run。"""
    return event_type in escalation_whitelist()
