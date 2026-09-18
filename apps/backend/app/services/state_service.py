import logging
import time
from dataclasses import dataclass
from datetime import datetime

from app.chains import state_update_chain, turn_analysis_chain
from app.core.settings import get_settings
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.core.constants import RELATIONSHIP_DIMENSIONS_V85
from app.models.relationship import (
    RelationshipDelta,
    RelationshipEvent,
    RelationshipState,
)
from app.models.emotion import EmotionHistoryEntry
from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    relationship_event_repository,
    relationship_repository,
)
from app.services import (
    relationship_evolution,
    relationship_signal,
    state_engine,
    relationship_conflict,
    relationship_milestone,
)
from app.repositories import (
    relationship_conflict_repository,
    relationship_snapshot_repository,
)

logger = logging.getLogger(__name__)

RELATIONSHIP_DIMENSIONS = ("intimacy", "trust", "familiarity", "tension")

_reputation_audits: dict[str, dict] = {}


def get_relationship_audit(user_id: str) -> dict | None:
    """本轮演化审计（评估护栏消费；内存结构，缺席返回 None = 规则跳过）。"""
    return _reputation_audits.get(user_id)

REPLAY_TYPE_KEYWORDS = (
    (("安慰", "关心", "陪", "照顾"), "user_care"),
    (("帮", "帮忙", "支持"), "user_help"),
    (("送", "礼物", "夸", "称赞"), "praise"),
    (("吵", "冲突", "生气", "冷战"), "conflict"),
)


def _day_impact_totals(
    user_id: str, now: datetime, events: list | None = None
) -> tuple[RelationshipDelta, RelationshipDelta]:
    positive = RelationshipDelta()
    negative = RelationshipDelta()
    try:
        if events is None:
            events = relationship_event_repository.list_events(user_id, limit=500)
    except Exception:
        logger.exception("当日事件账本读取失败，日上限按零已用处理")
        return positive, negative
    for event in events:
        if event.created_at.date() != now.date():
            continue
        for dim in RELATIONSHIP_DIMENSIONS_V85:
            value = getattr(event.impact, dim)
            if value > 0:
                setattr(positive, dim, getattr(positive, dim) + value)
            elif value < 0:
                setattr(negative, dim, getattr(negative, dim) - value)
    return positive, negative


def _resolve_relationship_event(
    analysis: TurnAnalysis,
) -> tuple[str, str, float, str]:
    decision = analysis.relationship_event
    if decision.type != "none":
        return decision.type, decision.magnitude, decision.confidence, decision.cause
    event = analysis.user_emotion.event
    mapped = turn_analysis_chain.map_event_to_relationship(event)
    if mapped != "none":
        return mapped, "normal", 0.5, ""
    if event == "daily":
        return "long_interaction", "weak", 0.3, ""
    return "none", "normal", 0.0, ""


@dataclass
class StateSnapshotData:
    character_state: CharacterState
    relationship_state: RelationshipState
    emotion_history: list[EmotionHistoryEntry]
    relationship_events: list


def load_snapshot(user_id: str, limit: int) -> StateSnapshotData:
    character = character_state_repository.get_state(user_id)
    relationship = relationship_repository.get_relationship(user_id)
    history = emotion_history_repository.list_recent(user_id, limit)
    events = relationship_event_repository.list_events(user_id, limit)
    return StateSnapshotData(
        character_state=character,
        relationship_state=relationship,
        emotion_history=history,
        relationship_events=events,
    )


def load_states(user_id: str) -> tuple[CharacterState, RelationshipState]:
    character = character_state_repository.get_state(user_id)
    relationship = relationship_repository.get_relationship(user_id)
    now = datetime.now()
    recovered = state_engine.apply_idle_recovery(character, now)
    decayed = state_engine.apply_emotion_decay(recovered, now)
    if decayed != recovered:
        character_state_repository.upsert_state(user_id, decayed)
    return decayed, relationship


def load_relationship(user_id: str) -> RelationshipState:
    """只读关系状态（零副作用，缺记录返回默认值不落库）。

    工具层预读（TOOL-007 §2.2 关系阶段投影）与只读消费方的统一入口：
    工具实现体禁止导入 `relationship_*_repository`，读面必须经服务层（静态扫描强制）。
    """
    return relationship_repository.get_relationship(user_id)


def load_last_user_emotion(user_id: str) -> str:
    try:
        entries = emotion_history_repository.list_recent(user_id, 1)
        return entries[0].user_emotion if entries else "neutral"
    except Exception:
        logger.exception("最近用户情绪读取失败，按 neutral 处理")
        return "neutral"


async def apply_and_save(
    user_id: str,
    session_id: str,
    state: ConversationState,
    analysis: TurnAnalysis,
    user_input: str,
    ai_reply: str,
    llm=None,
    trace=None,
) -> None:
    now = datetime.now()
    started = time.perf_counter()
    decision = await state_update_chain.update(
        state, analysis, user_input, ai_reply, llm=llm
    )
    if trace is not None:
        elapsed = (time.perf_counter() - started) * 1000
        trace.record("state_update", elapsed, "degraded" if decision is None else "ok")

    character = state_engine.apply_idle_recovery(state.character_state, now)
    character = state_engine.apply_character(character, decision, analysis, now)

    emotion_started = time.perf_counter()
    try:
        character = state_engine.update_emotion(character, analysis.emotion_event, now)
        if trace is not None:
            trace.record(
                "emotion_update", (time.perf_counter() - emotion_started) * 1000
            )
    except Exception as exc:
        logger.exception("情绪更新失败，保持上一轮情绪")
        if trace is not None:
            trace.record(
                "emotion_update",
                0.0,
                "error",
                error=exc.__class__.__name__,
            )

    relationship_started = time.perf_counter()
    new_relationship = state.relationship_state
    pending_events: list[RelationshipEvent] = []
    recent_events: list = []
    settings = get_settings()
    try:
        recent_events = relationship_event_repository.list_events(user_id, limit=500)
        day_positive, day_negative = _day_impact_totals(
            user_id, now, events=recent_events
        )
        before = state.relationship_state
        if settings.rel_evolution_enabled:
            window = relationship_signal.EvidenceWindow.rebuild_from_events(
                recent_events[: settings.rel_signal_evidence_window]
            )
            signal = relationship_signal.analyze_interaction(
                user_input, analysis, ai_reply
            )
            repeats_by_kind: dict[tuple[str, str], int] = {}
            if signal is not None:
                repeats_by_kind[(signal.kind, signal.quality)] = window.count(
                    signal.kind, signal.quality
                )
                signal = relationship_signal.observe(window, signal)
                event_type, magnitude = relationship_signal.map_signal_to_event(signal)
                confidence, cause = signal.salience, signal.cause
            else:
                event_type, magnitude, confidence, cause = (
                    _resolve_relationship_event(analysis)
                )
            new_relationship, outcome = relationship_evolution.evolve(
                before,
                event_type,
                magnitude,
                analysis.behavior.behavior,
                signal,
                repeats_by_kind,
                day_positive,
                day_negative,
                now,
                session_id=session_id,
                user_id=user_id,
                cause=cause,
                confidence=confidence,
                window=window.snapshot(),
            )
            if outcome.event is not None:
                pending_events.append(outcome.event)
            _reputation_audits[user_id] = {
                "before": before,
                "after": new_relationship,
                "applied": outcome.applied_delta,
                "truncated": outcome.truncated,
                "day_positive": day_positive,
                "day_negative": day_negative,
                "events": list(pending_events),
                "signal_present": signal is not None,
                "signal_kind": signal.kind if signal is not None else "",
                "event_type": event_type,
                "comfort_drift": outcome.comfort_drift_applied,
                "version_before": outcome.version_before,
                "version_after": outcome.version_after,
            }
        else:
            event_type, magnitude, confidence, cause = (
                _resolve_relationship_event(analysis)
            )
            new_relationship, applied = state_engine.apply_relationship_v5(
                state.relationship_state,
                event_type,
                magnitude,
                analysis.behavior.behavior,
                day_positive,
                day_negative,
            )
            if event_type != "none":
                pending_events.append(
                    RelationshipEvent(
                        user_id=user_id,
                        session_id=session_id,
                        type=event_type,
                        magnitude=magnitude,
                        impact=applied,
                        confidence=confidence,
                        cause=cause,
                        created_at=now,
                    )
                )
        if trace is not None:
            trace.record(
                "relationship_event",
                (time.perf_counter() - relationship_started) * 1000,
            )
    except Exception as exc:
        logger.exception("关系更新失败，保持上一轮关系")
        new_relationship = state.relationship_state
        if trace is not None:
            trace.record(
                "relationship_event",
                0.0,
                "error",
                error=exc.__class__.__name__,
            )

    try:
        replay_state, replay_events = _replay_relationship_memories(
            user_id, session_id, state, new_relationship, now
        )
        if replay_events:
            pending_events.extend(replay_events)
            new_relationship = replay_state
    except Exception:
        logger.exception("记忆回放补记失败，跳过，不影响主流程")

    character_state_repository.upsert_state(user_id, character)
    try:
        relationship_repository.commit_relationship_update(
            user_id, new_relationship, pending_events
        )
    except Exception:
        logger.exception("关系状态与事件账本落库失败，保持上一轮")

    try:
        _run_relationship_subsystems(
            user_id, session_id, state, analysis, character,
            new_relationship, pending_events, user_input, recent_events, now,
        )
    except Exception:
        logger.exception("关系演化后处理失败，不影响本轮回答")

    emotion_history_repository.append(
        user_id=user_id,
        session_id=session_id,
        user_emotion=analysis.user_emotion.emotion,
        event=analysis.user_emotion.event,
        behavior=analysis.behavior.behavior,
        mood_before=state.character_state.mood,
        mood_after=character.mood,
        energy_after=character.energy,
        stage_after=new_relationship.stage,
    )


def _run_relationship_subsystems(
    user_id: str,
    session_id: str,
    state: ConversationState,
    analysis: TurnAnalysis,
    character: CharacterState,
    new_relationship: RelationshipState,
    turn_events: list[RelationshipEvent],
    user_input: str,
    recent_events: list,
    now: datetime,
) -> None:
    """V8.5 演化后处理：冲突 → 里程碑 → 记忆投递（独立小事务，只降级）。"""

    audit = _reputation_audits.get(user_id) or {}
    before: RelationshipState = audit.get("before") or new_relationship
    shared_activity = audit.get("signal_kind") == "shared_activity"

    conflict_outcome = relationship_conflict.evaluate_conflict(
        user_id, session_id, new_relationship,
        relationship_conflict_repository.get_active_conflict(user_id),
        turn_events, user_input, now,
    )
    updated = conflict_outcome.state
    new_system_events: list[RelationshipEvent] = list(conflict_outcome.system_events)
    if conflict_outcome.record is not None:
        record = conflict_outcome.record
        if _conflict_exists(record):
            relationship_conflict_repository.update_status(record)
        else:
            relationship_conflict_repository.create_conflict(record)
        updated = updated.model_copy(update={"conflict_status": record.status})

    decay = relationship_conflict.decay_tension(
        user_id, session_id, updated, conflict_outcome.record, now
    )
    if decay.system_events:
        updated = decay.state
        new_system_events.extend(decay.system_events)

    stage_before = before.stage
    milestone_ctx = relationship_milestone.MilestoneContext(
        user_id=user_id,
        event_type=audit.get("event_type", "none"),
        state_before=before,
        state_after=updated,
        stage_before=stage_before,
        stage_after=updated.stage,
        ledger_empty_before=not recent_events,
        shared_activity=shared_activity,
        character_mood=character.mood,
        character_intensity=character.intensity,
        conflict_transition=conflict_outcome.transition,
        first_interaction_month=(
            recent_events[-1].created_at.strftime("%Y-%m") if recent_events else ""
        ),
        now=now,
    )
    updated, milestone_records = relationship_milestone.process_milestones(
        milestone_ctx, updated
    )

    if updated != new_relationship or new_system_events:
        relationship_repository.commit_relationship_update(
            user_id, updated, new_system_events
        )

    memory_worthy_keys = {
        spec.key for spec in relationship_milestone.MILESTONES if spec.memory_worthy
    }
    worthy = [m for m in milestone_records if m.milestone_key in memory_worthy_keys]
    conversation_event = next(
        (e for e in turn_events if e.source == "conversation" and e.type != "none"),
        None,
    )

    _capture_snapshot_if_needed(
        user_id,
        state_before=before,
        state_after=updated,
        stage_before=stage_before,
        conflict_transition=conflict_outcome.transition,
        new_milestones=milestone_records,
        now=now,
    )


def _capture_snapshot_if_needed(
    user_id: str,
    state_before: RelationshipState,
    state_after: RelationshipState,
    stage_before: str,
    conflict_transition: str,
    new_milestones: list,
    now: datetime,
) -> None:
    """persistence.md §6：stage 跃迁 / 里程碑命中 / 冲突迁移 → 写关键帧，限频 20。

    Args:
        conflict_transition: 具名冲突迁移类型（conflict_started / reconciled /
            recovery_started ...，见 relationship_conflict.evaluate_conflict）。
            空串表示本轮无迁移，按真值判断跳过。
    """

    trigger: str | None = None
    if stage_before != state_after.stage:
        trigger = f"stage_transition:{stage_before}→{state_after.stage}"
    elif conflict_transition:
        trigger = f"conflict:{conflict_transition}"
    elif new_milestones:
        trigger = f"milestone:{new_milestones[0].milestone_key}"
    if trigger is None:
        return
    try:
        relationship_snapshot_repository.create_snapshot(
            user_id,
            version=state_after.version,
            state=state_after,
            trigger=trigger,
            now=now,
        )
    except Exception:
        pass


def _conflict_exists(record) -> bool:
    try:
        return any(c.id == record.id for c in relationship_conflict_repository.list_conflicts(record.user_id, limit=200))
    except Exception:
        return False


def _replay_type_for(content: str) -> str:
    for keywords, event_type in REPLAY_TYPE_KEYWORDS:
        if any(keyword in content for keyword in keywords):
            return event_type
    return "user_care"


def _replay_exists(user_id: str, cause: str) -> bool:
    events = relationship_event_repository.list_events(user_id, limit=200)
    return any(
        event.source == "memory_replay" and event.cause == cause for event in events
    )


def _replay_is_idle(user_id: str, now: datetime) -> bool:
    settings = get_settings()
    events = relationship_event_repository.list_events(user_id, limit=1)
    if not events:
        return True
    idle_hours = (now - events[0].created_at).total_seconds() / 3600
    return idle_hours >= settings.rel_replay_min_idle_hours


def _replay_relationship_memories(
    user_id: str,
    session_id: str,
    state: ConversationState,
    relationship: RelationshipState,
    now: datetime,
) -> tuple[RelationshipState, list[RelationshipEvent]]:
    settings = get_settings()
    updated = relationship
    replay_events: list[RelationshipEvent] = []
    for memory in state.memories:
        if memory.type != "relationship_event":
            continue
        try:
            cause = memory.content[:50]
            if _replay_exists(user_id, cause):
                continue
            if not _replay_is_idle(user_id, now):
                continue
            event_type = _replay_type_for(memory.content)
            base = state_engine.build_relationship_impact(event_type, "weak")
            discount = settings.rel_replay_discount
            new_values = {}
            applied = {}
            for dim in RELATIONSHIP_DIMENSIONS:
                delta = getattr(base, dim) * discount
                current = getattr(updated, dim)
                new_value = state_engine.clamp(current + delta, 0.0, 1.0)
                new_values[dim] = new_value
                applied[dim] = round(new_value - current, 6)
            stage = state_engine.next_stage(
                new_values["intimacy"],
                new_values["trust"],
                new_values["familiarity"],
                updated.stage,
                tension=new_values["tension"],
            )
            replay_events.append(
                RelationshipEvent(
                    user_id=user_id,
                    session_id=session_id,
                    type=event_type,
                    magnitude="weak",
                    impact=RelationshipDelta(**applied),
                    confidence=0.5,
                    source="memory_replay",
                    cause=cause,
                    created_at=now,
                )
            )
            updated = updated.model_copy(update={**new_values, "stage": stage})
        except Exception:
            logger.exception("单条记忆回放补记失败，跳过该条")
    return updated, replay_events
