"""V8.5 M5 Conflict System（conflict-system.md）：冲突状态机 + neglect + 张力消退。

tension 是标量，冲突是过程：none → strain → conflict → cold → recovery → resolved。
全部迁移为纯函数；结算 delta 走 source=system 账本（无信号变化的显式"因"）。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.core import timeutil
from app.character.asuna.relationship_lexicon import RECOVERY_LEXICON
from app.core.settings import get_settings
from app.models.relationship import (
    ConflictRecord,
    RelationshipDelta,
    RelationshipState,
    RelationshipEvent,
)
from app.engines.relationship_evolution import clamp01

logger = logging.getLogger(__name__)

TENSION_CONFLICT_STATUSES = ("conflict", "cold")

STRAIN_RELIEF_TENSION = 0.3
STRAIN_RELIEF_HOURS = 48.0
RECOVERY_FALLBACK_DAYS = 7.0
TIME_HEALS_TENSION = 0.3


@dataclass
class ConflictOutcome:
    state: RelationshipState
    record: ConflictRecord | None = None
    transition: str = ""
    system_events: list = field(default_factory=list)


def _system_event(user_id, session_id, cause, impact, now):
    return RelationshipEvent(
        user_id=user_id,
        session_id=session_id,
        type="none",
        magnitude="weak",
        impact=impact,
        confidence=1.0,
        source="system",
        cause=cause,
        created_at=now,
    )


def recovery_hit(user_message: str) -> bool:
    """修复信号词表（用户→角色方向道歉）；不产演化信号。"""
    return any(phrase in user_message for phrase in RECOVERY_LEXICON)


def _event_negative(event) -> bool:
    impact = event.impact
    return impact.tension > 0 or impact.trust < 0


def negative_event_count(events: list) -> int:
    return sum(1 for event in events if _event_negative(event))


def _new_record(user_id: str, status: str, now: datetime, trigger_event_id=None) -> ConflictRecord:
    return ConflictRecord(
        user_id=user_id,
        status=status,
        trigger_event_id=trigger_event_id,
        started_at=now,
        last_negative_at=now if status in ("strain", "conflict") else None,
        created_at=now,
    )


def _first_id(events: list) -> str | None:
    return events[0].id if events else None


def _soften_tension(state: RelationshipState) -> RelationshipState:
    """none/strain 态命中修复词表只做温和去 tense（道歉本身不加分）。"""
    return state.model_copy(update={"tension": max(0.0, state.tension - 0.02)})


def _apply_settlement(state: RelationshipState, settle: RelationshipDelta) -> RelationshipState:
    return state.model_copy(
        update={
            "tension": max(0.0, min(1.0, state.tension + settle.tension)),
            "comfort": max(0.0, min(1.0, state.comfort + settle.comfort)),
        }
    )


def _strain_relief(state: RelationshipState, record: ConflictRecord, now: datetime) -> bool:
    if state.tension > STRAIN_RELIEF_TENSION:
        return False
    if record.last_negative_at is None:
        return True
    return (now - record.last_negative_at).total_seconds() / 3600 >= STRAIN_RELIEF_HOURS


def _cold_elapsed(record: ConflictRecord, now: datetime, settings) -> bool:
    reference = record.last_negative_at or record.started_at
    hours = (now - reference).total_seconds() / 3600
    return hours >= settings.rel_conflict_cold_hours


def evaluate_conflict(
    user_id: str,
    session_id: str,
    state: RelationshipState,
    record: ConflictRecord | None,
    turn_events: list,
    user_message: str,
    now: datetime,
) -> ConflictOutcome:
    """冲突状态机迁移（非法迁移拒绝 = 原样返回）。"""
    settings = get_settings()
    current = record.status if record is not None else "none"
    has_conflict_event = any(
        event.type in ("conflict", "boundary_violation") for event in turn_events
    )
    negative = negative_event_count(turn_events)
    user_recovery = recovery_hit(user_message)
    outcome = ConflictOutcome(state=state, record=record)

    if current == "none":
        if has_conflict_event:
            outcome.record = _new_record(user_id, "conflict", now, _first_id(turn_events))
            outcome.transition = "conflict_started"
        elif state.tension > settings.rel_tension_freeze or negative >= 2:
            outcome.record = _new_record(user_id, "strain", now)
            outcome.transition = "strain_started"
        return outcome

    assert record is not None

    if current == "strain":
        if has_conflict_event:
            record.status = "conflict"
            record.last_negative_at = now
            outcome.transition = "conflict_started"
        elif _strain_relief(state, record, now):
            record.status = "resolved"
            record.resolved_at = now
            outcome.transition = "strain_relieved"
            outcome.system_events.append(
                _system_event(user_id, session_id, "strain 静默解除", RelationshipDelta(), now)
            )
        elif user_recovery:
            outcome.state = _soften_tension(state)
        return outcome

    if current in ("conflict", "cold"):
        if negative:
            record.last_negative_at = now
        if current == "conflict" and _cold_elapsed(record, now, settings):
            record.status = "cold"
            outcome.transition = "cold_started"
        if user_recovery:
            record.status = "recovery"
            record.recovery_started_at = record.recovery_started_at or now
            outcome.transition = "recovery_started"
        return outcome

    if current == "recovery":
        positives = sum(
            1 for event in turn_events if not _event_negative(event) and event.type != "none"
        )
        if positives >= settings.rel_conflict_recover_positive:
            record.status = "resolved"
            record.resolved_at = now
            record.resolution = "reconciled"
            outcome.transition = "reconciled"
            settle = RelationshipDelta(tension=-state.tension / 2, comfort=0.05)
            outcome.state = _apply_settlement(state, settle)
            outcome.system_events.append(
                _system_event(user_id, session_id, "和解结算", settle, now)
            )
        elif record.recovery_started_at is not None and (
            now - record.recovery_started_at
        ).total_seconds() / 86400 > RECOVERY_FALLBACK_DAYS and not turn_events:
            record.status = "cold"
            outcome.transition = "recovery_fallback"
        return outcome

    if current == "resolved":
        if has_conflict_event:
            outcome.record = _new_record(user_id, "conflict", now, _first_id(turn_events))
            outcome.transition = "conflict_reopened"
        return outcome

    return outcome


def detect_neglect(
    user_id: str,
    session_id: str,
    state: RelationshipState,
    had_user_message: bool,
    now: datetime,
) -> ConflictOutcome:
    """疏远检测（读时检查，一次性落账；重逢即修复）。"""
    settings = get_settings()
    threshold = float(settings.neglect_thresholds().get(state.stage, 7.0))
    reference = state.last_interaction_at
    gap_days = (
        (now - reference).total_seconds() / 86400 if reference is not None else threshold + 1
    )
    outcome = ConflictOutcome(state=state)
    if had_user_message:
        if state.neglect_active:
            outcome.state = state.model_copy(update={"neglect_active": False})
        return outcome
    if gap_days > threshold and not state.neglect_active:
        trust_drop = -0.01 if state.stage in ("close_friend", "partner") else 0.0
        outcome.state = state.model_copy(
            update={
                "neglect_active": True,
                "comfort": max(0.0, state.comfort - 0.05),
                "trust": max(0.0, state.trust + trust_drop),
            }
        )
        outcome.system_events.append(
            _system_event(
                user_id,
                session_id,
                "久未联系",
                RelationshipDelta(comfort=-0.05, trust=trust_drop),
                now,
            )
        )
    return outcome


def decay_tension(
    user_id: str,
    session_id: str,
    state: RelationshipState,
    record: ConflictRecord | None,
    now: datetime,
) -> ConflictOutcome:
    """张力自然消退（按天、幂等；active conflict 期暂停）。"""
    settings = get_settings()
    outcome = ConflictOutcome(state=state, record=record)
    if record is not None and record.status in TENSION_CONFLICT_STATUSES:
        return outcome
    reference = state.last_interaction_at
    if reference is None:
        return outcome
    days = (timeutil.local(now).date() - timeutil.local(reference).date()).days
    if days <= 0 or state.tension <= 0:
        return outcome
    decay = min(settings.rel_tension_daily_decay * days, state.tension)
    outcome.state = state.model_copy(
        update={"tension": max(0.0, state.tension - decay)}
    )
    outcome.system_events.append(
        _system_event(
            user_id,
            session_id,
            "张力自然消退",
            RelationshipDelta(tension=-decay),
            now,
        )
    )
    return outcome
