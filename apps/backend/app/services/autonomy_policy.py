"""V7 AutonomyPolicy（autonomy-policy.md / cooldown.md）：纯函数裁决流水。

(signal, snapshot, config, now) → AutonomyVerdict，八步按序短路，无 IO。
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

logger = logging.getLogger(__name__)

QUIET_HOURS_EXEMPT_TYPES: frozenset = frozenset()

SLEEPY_MOODS = frozenset({"tired"})
BUSY_ACTIVITY_KEYWORDS = ("睡觉", "睡眠", "午睡", "休息中", "忙碌", "工作", "开会", "洗澡")

_PROACTIVE_GOAL_TYPES = frozenset(PROACTIVE_INTENTION_MAP.keys())


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


def evaluate(signal: TriggerSignal, snapshot: PolicySnapshot, config=None, now: datetime | None = None) -> AutonomyVerdict:
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
    return AutonomyVerdict(
        decision="act",
        reason=f"触发 {signal.type}，存在 {snapshot.selected_goal_type} 目标",
        trigger=signal,
        goal_id=snapshot.extra_flags.get("goal_id"),
        intention=intention,
    )
