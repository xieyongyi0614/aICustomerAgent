"""V7 AutonomyPolicy（autonomy-policy.md / cooldown.md）：纯函数裁决流水。

(signal, snapshot, config, now) → AutonomyVerdict，八步按序短路，无 IO。
V8.5 追加 R1~R5 门控（relationship 域规则，纯函数追加收紧/单点放行。
V2.4.0 TOOL-006：`tool_facts` 作为既有八步的**输入面**（只追加理由，不新增步骤、
不拆闸门）；缺省空 dict 时行为与 V2.3.0 逐字节一致。
V2.4.0 TOOL-009：`tool_insights`（工具效能 Insight 只读信号）同为输入面——
只追加"候选收缩"理由，不拆闸门；缺省空 dict 时行为与 V2.3.0 逐字节一致。

V2.5.0 PLAN-007：`plan_facts`（计划运行态只读事实段，`PLAN_FACTS_KEYS` 七键）同为输入面——
在既有调制链**末尾追加一环** `_apply_plan_adjustments`：计划正在推进且本 intent 与其当前步
**同动作**时收紧为 `wait`（不与计划抢同一动作，避免额度被重复消耗），其余情形原样返回。
八步裁决顺序、`TRIGGER_PRIORITY` 数学与 `HIGH_PRIORITY_OVERRIDE`（P0 / P1 越过）一律未改；
缺省空 dict 时行为与 V2.4.0 逐字节一致。
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
from app.character.asuna.action import PROACTIVE_ACTION_MAP
from app.character.asuna.relationship_lexicon import INTENT_UNLOCK_REQUIREMENTS

logger = logging.getLogger(__name__)

QUIET_HOURS_EXEMPT_TYPES: frozenset = frozenset()

SLEEPY_MOODS = frozenset({"tired"})
BUSY_ACTIVITY_KEYWORDS = ("睡觉", "睡眠", "午睡", "休息中", "忙碌", "工作", "开会", "洗澡")

_PROACTIVE_GOAL_TYPES = frozenset(PROACTIVE_INTENTION_MAP.keys())

WORLD_PROACTIVE_EVENT_TYPES = frozenset({"interview", "exam"})

STAGE_RANK = {"stranger": 0, "friend": 1, "close_friend": 2, "partner": 3}

TRIGGER_PRIORITY: dict[str, str] = {
    "scheduled_followup": "P0",
    "action_due": "P1",
    "conversation_inactivity": "P3",
}

HIGH_PRIORITY_OVERRIDE = frozenset({"P0", "P1"})

PLAN_FACTS_KEYS: tuple[str, ...] = (
    "active_goal_id",
    "plan_version",
    "current_step",
    "current_action_type",
    "steps_total",
    "blocked_steps",
    "last_advanced_at",
)
"""`plan_facts` 的**有界契约**（PLAN-007 §4.2.1）：固定七键、无无界列表、无优先级 / 工具细节。

第七键 `current_action_type` 是**契约演进留痕项**：§4.3.2 要求「本 intent 与计划当前步的
`action_type` 相同」才收紧，而原六字段（`active_goal_id` / `plan_version` / `current_step` /
`steps_total` / `blocked_steps` / `last_advanced_at`）不含当前步的动作身份，该判定不可实现
（策略层是纯函数，不得为取动作身份而反读计划）。经裁决取「新增一个标量键」而非「放宽为
同目标级抑制」：字段数 6 → 7（仍有界、仍为标量、仍不含 `tool_id` / 参数 / 优先级），
§4.3.2 的动作级语义**原样保留**。

本常量是契约的**唯一声明处**（键集与键序）：装配侧按同序字面量装配、调制侧按名取值，
二者与 `tests/v25/test_plan007_plan_facts.py` 的键序对照共同受本常量约束。
"""


def trigger_priority(signal: TriggerSignal) -> str:
    """P0 用户明确要求 / P1 重要委托，P3 闲聊级（autonomy-policy.md 优先级表）。"""
    return TRIGGER_PRIORITY.get(signal.type, "P3")


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
    tool_facts: dict = field(default_factory=dict)
    tool_insights: dict = field(default_factory=dict)
    respect: float = 0.60
    comfort: float = 0.60
    conflict_status: str = "none"
    neglect_active: bool = False
    unlocks: tuple[str, ...] = ()
    trust: float = 0.35
    stage: str = "friend"
    relationship_patterns: tuple[str, ...] = ()
    plan_facts: dict = field(default_factory=dict)


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
    """W1/W2/W3（autonomy-integration.md §3）+ W4/W5（V2.3.0 影响裁决）：world 只追加理由，绝不拆闸门。"""
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
    for impact in facts.get("impacts") or []:
        if impact.get("urgency") == "high" or (impact.get("care_relevance") or 0) >= 0.8:
            notes.append(f"世界事件值得关心：{impact.get('event_type')}")
        elif (
            facts.get("part_of_day") == "late_night"
            and (impact.get("topic_value") or 0) > 0.5
        ):
            notes.append("深夜不宜为琐事打扰")
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


def _apply_tool_adjustments(
    verdict: AutonomyVerdict, snapshot: PolicySnapshot
) -> AutonomyVerdict:
    """T1/T2（TOOL-006 §2.1）：tool_facts 作为既有八步的输入面，只追加理由，不拆闸门。"""
    facts = snapshot.tool_facts or {}
    if not facts:
        return verdict
    notes: list[str] = []
    if facts.get("breaker_open"):
        notes.append("有工具处于熔断，暂避该途径")
    if facts.get("recent_failures"):
        notes.append("近期工具有失败，选择手段需谨慎")
    if not notes:
        return verdict
    reason = f"{verdict.reason}；{'；'.join(notes)}"[:60]
    return verdict.model_copy(update={"reason": reason})


def _apply_tool_insight_adjustments(
    verdict: AutonomyVerdict, snapshot: PolicySnapshot
) -> AutonomyVerdict:
    """T3（TOOL-009 §2.3）：工具效能 Insight 只读信号影响候选收缩，只追加理由。

    信号由 `reflection.tool_feed.autonomy_signal` 只读产出（无写方法）；
    缺省空 dict / 无 notes 时行为与 V2.3.0 逐字节一致。
    """
    signal = snapshot.tool_insights or {}
    notes = [str(note) for note in (signal.get("notes") or []) if note]
    if not notes:
        return verdict
    reason = f"{verdict.reason}；{'；'.join(notes)}"[:60]
    return verdict.model_copy(update={"reason": reason})


def _intention_action_type(intention: str | None) -> str | None:
    """自治意图 → 动作身份：`PROACTIVE_ACTION_MAP` 是唯一权威（与自治产行动分支同源）。"""
    if not intention:
        return None
    return PROACTIVE_ACTION_MAP.get(intention)


def _apply_plan_adjustments(
    verdict: AutonomyVerdict, snapshot: PolicySnapshot
) -> AutonomyVerdict:
    """P1（PLAN-007 §4.3.2）：计划正在推进且与本 intent 抢**同一动作**时收紧为 `wait`。

    只收紧不放行——空包 / `current_step is None` / 动作不同 / 非 `act` 一律原样返回；
    本函数不改变八步裁决顺序、不改 `TRIGGER_PRIORITY` 数学；`HIGH_PRIORITY_OVERRIDE` 语义
    原样保留（P0 / P1 触发器仍越过本抑制）。
    """
    facts = snapshot.plan_facts or {}
    if not facts or facts.get("current_step") is None:
        return verdict
    if verdict.decision != "act":
        return verdict
    priority = trigger_priority(verdict.trigger) if verdict.trigger is not None else "P3"
    if priority in HIGH_PRIORITY_OVERRIDE:
        return verdict
    action_type = _intention_action_type(verdict.intention)
    if action_type is None or action_type != facts.get("current_action_type"):
        return verdict
    return AutonomyVerdict(
        decision="wait",
        reason=f"{verdict.reason}；计划推进中，暂不抢同一动作"[:60],
        trigger=verdict.trigger,
    )


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
    priority = trigger_priority(signal)
    cooldown_passed = _cooldown_passed(snapshot, config, now)
    if not cooldown_passed and priority not in HIGH_PRIORITY_OVERRIDE:
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

    reason = f"触发 {signal.type}，存在 {snapshot.selected_goal_type} 目标"
    if not cooldown_passed:
        reason = f"{reason}；{priority}覆盖冷却"
    verdict = AutonomyVerdict(
        decision="act",
        reason=reason[:60],
        trigger=signal,
        goal_id=snapshot.extra_flags.get("goal_id"),
        intention=PROACTIVE_INTENTION_MAP[snapshot.selected_goal_type],
    )
    verdict = _apply_world_adjustments(verdict, snapshot)
    verdict = _apply_action_adjustments(verdict, snapshot)
    verdict = _apply_tool_adjustments(verdict, snapshot)
    verdict = _apply_tool_insight_adjustments(verdict, snapshot)
    verdict = _apply_plan_adjustments(verdict, snapshot)
    return _apply_relationship_rules(verdict, snapshot, config)
