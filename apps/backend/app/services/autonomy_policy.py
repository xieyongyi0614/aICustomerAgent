"""V7 AutonomyPolicy（autonomy-policy.md / cooldown.md）：纯函数裁决流水。

(signal, snapshot, config, now) → AutonomyVerdict，八步按序短路，无 IO。
V8.5 追加 R1~R5 门控（relationship 域规则，纯函数追加收紧/单点放行。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time

from app.core.settings import get_settings
from app.models.autonomy import (
    PROACTIVE_INTENTION_MAP,
    AutonomyVerdict,
    TriggerSignal,
)
from app.character.asuna.relationship_lexicon import INTENT_UNLOCK_REQUIREMENTS

logger = logging.getLogger(__name__)

QUIET_HOURS_EXEMPT_TYPES: frozenset = frozenset()

SLEEPY_MOODS = frozenset({"tired"})
BUSY_ACTIVITY_KEYWORDS = ("睡觉", "睡眠", "午睡", "休息中", "忙碌", "工作", "开会", "洗澡")

_PROACTIVE_GOAL_TYPES = frozenset(PROACTIVE_INTENTION_MAP.keys())

WORLD_PROACTIVE_EVENT_TYPES = frozenset({"interview", "exam"})

STAGE_RANK = {"stranger": 0, "friend": 1, "close_friend": 2, "partner": 3}


@dataclass
class PolicySnapshot:
    generating: bool = False
    has_active_action: bool = False
    last_proactive_at: datetime | None = None
    attempt_count: int = 0
    intimacy: float = 0.3
    tension: float = 0.0
    mood: str = "calm"
    current_activity: str | None = None
    selected_goal_type: str | None = None
    goal_degraded: bool = False
    extra_flags: dict = field(default_factory=dict)
    world_facts: dict = field(default_factory=dict)
    action_facts: dict = field(default_factory=dict)
    respect: float = 0.60
    comfort: float = 0.60
    conflict_status: str = "none"
    neglect_active: bool = False
    unlocks: tuple[str, ...] = ()
    trust: float = 0.35
    stage: str = "friend"
    relationship_patterns: tuple[str, ...] = ()


def _parse_hhmm(value: str) -> dt_time | None:
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return dt_time(hour=hour, minute=minute)


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    start_time, end_time = _parse_hhmm(start), _parse_hhmm(end)
    if start_time is None or end_time is None or start_time == end_time:
        return False
    current = now.time()
    if start_time > end_time:
        return current >= start_time or current < end_time
    return start_time <= current < end_time


def effective_interval_minutes(
    snapshot: PolicySnapshot, config
) -> float:
    base = float(config.autonomy_min_interval_minutes)
    if snapshot.intimacy >= 0.55:
        base *= 0.5
    elif snapshot.tension > 0.5 and snapshot.selected_goal_type == "relationship":
        base *= 0.5
    if snapshot.comfort < 0.35:
        base *= 1.5
    backoff = config.autonomy_backoff_multiplier ** max(snapshot.attempt_count - 1, 0)
    interval = base * backoff
    return max(interval, float(config.autonomy_min_interval_floor_minutes))


def _cooldown_passed(snapshot: PolicySnapshot, config, now: datetime) -> bool:
    if snapshot.last_proactive_at is None:
        return True
    interval = effective_interval_minutes(snapshot, config)
    elapsed_minutes = (now - snapshot.last_proactive_at).total_seconds() / 60
    return elapsed_minutes >= interval


def _activity_busy(activity: str | None) -> bool:
    if not activity:
        return False
    return any(keyword in activity for keyword in BUSY_ACTIVITY_KEYWORDS)


def _apply_world_adjustments(verdict: AutonomyVerdict, snapshot: PolicySnapshot) -> AutonomyVerdict:
    """W1/W2/W3（autonomy-integration.md §3）：world 只追加理由，绝不拆闸门。"""
    facts = snapshot.world_facts or {}
    if not facts:
        return verdict
    notes: list[str] = []
    if facts.get("weather") == "rain":
        notes.append("雨天不宜出门")
    for event in facts.get("salient_events") or []:
        if (
            event.get("type") in WORLD_PROACTIVE_EVENT_TYPES
            and event.get("importance") == "high"
            and 0 <= (event.get("due_in_hours") or 24) <= 24
        ):
            notes.append(f"记得关心{event.get('title')}")
    if not notes:
        return verdict
    reason = f"{verdict.reason}；{'；'.join(notes)}"[:60]
    return verdict.model_copy(update={"reason": reason})


def _reconciliation_already_used(snapshot: PolicySnapshot) -> bool:
    """单冲突至多放行一次 reconciliation_check_in（幂等保护，内存 flag，默认关即视为未用）。"""
    return bool(snapshot.extra_flags.get("reconciliation_attempted", False))


def _apply_relationship_rules(
    verdict: AutonomyVerdict, snapshot: PolicySnapshot, config
) -> AutonomyVerdict:
    """V8.5 R1~R5：八步闸门之后追加收紧；R5 放行优先级高于 R3。"""
    if verdict.decision != "act":
        return verdict
    intention = verdict.intention or ""
    reason = verdict.reason
    conflict_status = snapshot.conflict_status or "none"
    unlocks = snapshot.unlocks or ()
    stage_rank = STAGE_RANK.get(snapshot.stage, 0)
    friend_rank = STAGE_RANK["friend"]
    trust = snapshot.trust

    if conflict_status in ("conflict", "cold"):
        if (
            intention == "reconciliation_check_in"
            and "conflict_recovery_available" in unlocks
            and trust > 0.3
            and not _reconciliation_already_used(snapshot)
        ):
            reason = f"{reason}；R1单和解放行"[:60]
            return verdict.model_copy(update={"reason": reason})
        return AutonomyVerdict(
            decision="ignore",
            reason=f"{reason}；R1冲突期克制"[:60],
            trigger=verdict.trigger,
        )

    if (
        intention in ("reminder", "followup")
        and trust < float(config.rel_autonomy_trust_floor)
    ):
        if snapshot.neglect_active and stage_rank >= friend_rank:
            reason = f"{reason}；R5疏远召回覆盖R3"[:60]
            return verdict.model_copy(update={"reason": reason})
        return AutonomyVerdict(
            decision="ignore",
            reason=f"{reason}；R3信任不足"[:60],
            trigger=verdict.trigger,
        )


    required_unlock = INTENT_UNLOCK_REQUIREMENTS.get(intention)
    if required_unlock is not None and required_unlock not in unlocks:
        return AutonomyVerdict(
            decision="ignore",
            reason=f"{reason}；R4解锁未达成"[:60],
            trigger=verdict.trigger,
        )

    if snapshot.neglect_active and stage_rank >= friend_rank and intention == "reconnect_check_in":
        reason = f"{reason}；R5疏远召回"[:60]
        return verdict.model_copy(update={"reason": reason})

    return verdict


def _apply_action_adjustments(
    verdict: AutonomyVerdict, snapshot: PolicySnapshot
) -> AutonomyVerdict:
    """V9 A1/A2（autonomy-integration.md §2）：action_facts 只追加理由，不拆闸门。"""
    facts = snapshot.action_facts or {}
    if not facts:
        return verdict
    notes: list[str] = []
    for reminder in facts.get("pending_reminders") or []:
        due_in_hours = reminder.get("due_in_hours")
        if due_in_hours is not None and 0 <= due_in_hours <= 24:
            notes.append(f"提醒「{reminder.get('title')}」快到期，可跟进行动")
            break
    if facts.get("recent_failures"):
        notes.append("有未闭环的委托，可补救性关怀")
    if not notes:
        return verdict
    reason = f"{verdict.reason}；{'；'.join(notes)}"[:60]
    return verdict.model_copy(update={"reason": reason})


def evaluate(
    signal: TriggerSignal, snapshot: PolicySnapshot, config=None, now: datetime | None = None
) -> AutonomyVerdict:
    config = config or get_settings()
    now = now or datetime.now()

    def _verdict(decision: str, reason: str) -> AutonomyVerdict:
        return AutonomyVerdict(decision=decision, reason=reason[:60], trigger=signal)

    if snapshot.generating:
        return _verdict("wait", "用户正在对话")
    if in_quiet_hours(now, config.autonomy_quiet_hours_start, config.autonomy_quiet_hours_end) and (
        signal.type not in QUIET_HOURS_EXEMPT_TYPES
    ):
        return _verdict("ignore", "静音时段")
    if not _cooldown_passed(snapshot, config, now):
        return _verdict("wait", "冷却中")
    if snapshot.attempt_count >= config.autonomy_max_attempts_per_episode:
        return _verdict("ignore", "本集期已达上限")
    if snapshot.has_active_action:
        return _verdict("wait", "上一条主动还未处理")
    if snapshot.intimacy < 0.3 and snapshot.selected_goal_type != "relationship":
        return _verdict("ignore", "关系尚浅，不主动打扰")
    if snapshot.mood in SLEEPY_MOODS or _activity_busy(snapshot.current_activity):
        return _verdict("ignore", "角色状态不宜")
    if snapshot.goal_degraded or snapshot.selected_goal_type not in _PROACTIVE_GOAL_TYPES:
        return _verdict("ignore", "无主动动机")

    intention = PROACTIVE_INTENTION_MAP[snapshot.selected_goal_type]
    verdict = AutonomyVerdict(
        decision="act",
        reason=f"触发 {signal.type}，存在 {snapshot.selected_goal_type} 目标",
        trigger=signal,
        goal_id=snapshot.extra_flags.get("goal_id"),
        intention=intention,
    )
    verdict = _apply_world_adjustments(verdict, snapshot)
    verdict = _apply_action_adjustments(verdict, snapshot)
    return _apply_relationship_rules(verdict, snapshot, config)
