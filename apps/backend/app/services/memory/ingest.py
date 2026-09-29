"""Memory 2.0 统一摄取通道（MEM-002）。

四源（Conversation / ActionRecord / 完结 WorldEvent / RelationshipEvent）收敛为
幂等的 memory_candidates 行（status=pending）。假设/Roleplay 触发词 → visibility=
hypothetical（仍入库但不进长期检索）；瞬时动作短语 → 不产候选并记 trace 拦截原因。
所有写入经 source_table+source_id 唯一约束做幂等：命中既有候选则返回，不更新。
"""

import logging
import uuid
from datetime import datetime

from app.core.db import MemoryCandidateRow, SessionLocal
from app.core.settings import get_settings
from app.models.memory import MemoryExtraction
from app.services.action.memory_bridge import to_memory_candidates
from app.services.relationship_milestone import MILESTONES

logger = logging.getLogger(__name__)

SOURCE_CONVERSATION = "conversation"
SOURCE_ACTION = "action_records"
SOURCE_WORLD = "world_events"
SOURCE_RELATIONSHIP = "relationship_events"
SOURCE_RELATIONSHIP_MILESTONE = "relationship_milestones"
SOURCE_GOAL = "character_goals"

NARRATIVE_MILESTONE_PREFIX = "narrative:"
MILESTONE_SALIENCE_MEMORY_WORTHY = 0.90
MILESTONE_SALIENCE_NARRATIVE = 0.85
MILESTONE_SALIENCE_DEFAULT = 0.70

VISIBILITY_PRIVATE = "private"
VISIBILITY_HYPOTHETICAL = "hypothetical"


def _trigger_hit(content: str, triggers: list[str]) -> str | None:
    for token in triggers:
        if token in content:
            return token
    return None


def classify_conversation_visibility(
    content: str, trace=None
) -> tuple[str | None, str | None]:
    """返回 (visibility, 拦截原因)。

    hypothetical 触发 → visibility=hypothetical（入库但标记）；瞬时动作 → (None, 拦截原因)。
    """
    settings = get_settings()
    hypothetical = _trigger_hit(content, settings.hypothetical_triggers())
    if hypothetical is not None:
        return VISIBILITY_HYPOTHETICAL, None
    transient = _trigger_hit(content, settings.transient_triggers())
    if transient is not None:
        reason = f"transient_action:{transient}"
        if trace is not None:
            trace.record(
                "memory_ingest", 0.0, "blocked",
                error=reason, source=SOURCE_CONVERSATION,
            )
        return None, reason
    return VISIBILITY_PRIVATE, None


def _create_candidate(
    user_id: str,
    character_id: str,
    source_table: str,
    source_id: str,
    content: str,
    proposed_type: str,
    source_kind: str,
    salience_init: float,
    visibility: str | None = VISIBILITY_PRIVATE,
    source_ref_extra: dict | None = None,
    created_at: datetime | None = None,
) -> MemoryCandidateRow:
    created_at = created_at or datetime.now()
    source_ref: dict = {"table": source_table, "id": source_id}
    if source_ref_extra:
        source_ref.update(source_ref_extra)
    with SessionLocal() as session:
        existing = (
            session.query(MemoryCandidateRow)
            .filter(
                MemoryCandidateRow.source_table == source_table,
                MemoryCandidateRow.source_id == source_id,
            )
            .first()
        )
        if existing is not None:
            return existing
        row = MemoryCandidateRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            character_id=character_id,
            content=content,
            proposed_type=proposed_type,
            source=source_kind,
            source_ref=source_ref,
            source_table=source_table,
            source_id=source_id,
            salience=salience_init,
            status="pending",
            visibility=visibility,
            created_at=created_at,
        )
        session.add(row)
        session.commit()
        return row


def ingest_from_conversation(
    user_id: str,
    extraction: MemoryExtraction,
    source_id_base: str,
    character_id: str = "asuna",
    trace=None,
    created_at: datetime | None = None,
) -> list[MemoryCandidateRow]:
    """复用 v1 extractor 产物（MemoryExtraction），对每条候选执行词表预筛后幂等落候选。"""
    settings = get_settings()
    rows: list[MemoryCandidateRow] = []
    blocked = 0
    limit = settings.memory_ingest_max_per_turn
    for index, candidate in enumerate(extraction.candidates[:limit]):
        if not candidate.content:
            continue
        visibility, reason = classify_conversation_visibility(
            candidate.content, trace=trace
        )
        if reason is not None:
            blocked += 1
            continue
        source_id = f"{source_id_base}:{index}"
        row = _create_candidate(
            user_id=user_id,
            character_id=character_id,
            source_table=SOURCE_CONVERSATION,
            source_id=source_id,
            content=candidate.content,
            proposed_type=candidate.type,
            source_kind=candidate.source,
            salience_init=candidate.importance,
            visibility=visibility,
            source_ref_extra={
                "importance": candidate.importance,
                "confidence": candidate.confidence,
                "relation": candidate.relation,
            },
            created_at=created_at,
        )
        rows.append(row)
    if trace is not None:
        trace.record(
            "memory_ingest",
            0.0,
            extra={
                "source": SOURCE_CONVERSATION,
                "created": len(rows),
                "blocked": blocked,
                "candidate_ids": [row.id for row in rows],
            },
        )
    return rows


def ingest_from_action_record(
    record, character_id: str = "asuna", trace=None
) -> MemoryCandidateRow | None:
    """仅取 action_memory_policy deposit=true 的类型（内容/类型沿用 v9 边界表）。"""

    if record.status not in ("succeeded", "failed"):
        return None
    candidates = to_memory_candidates(record)
    if not candidates:
        return None
    candidate = candidates[0]
    if not candidate.content:
        return None
    row = _create_candidate(
        user_id=record.user_id,
        character_id=character_id,
        source_table=SOURCE_ACTION,
        source_id=record.id,
        content=candidate.content,
        proposed_type=candidate.type,
        source_kind=candidate.source,
        salience_init=candidate.importance,
        source_ref_extra={
            "action_type": record.action_type,
            "status": record.status,
        },
    )
    if trace is not None:
        trace.record(
            "memory_ingest",
            0.0,
            extra={"source": SOURCE_ACTION, "created": 1, "candidate_ids": [row.id]},
        )
    return row


def _salience_from_world_importance(importance: str) -> float:
    return {"high": 0.8, "normal": 0.6, "low": 0.4}.get(importance, 0.5)


def _enum_value(value):
    return getattr(value, "value", value)


def _completed_event_content(event) -> str:
    """完结事件的描述句（与 `world/memory_bridge.to_memory_candidates` 同源）。

    两侧必须逐字一致：世界旁路（v1）与 v2 正门对同一事件都会写入，内容相同时
    精确重复会被评估器判为 `duplicate_exact` 拒绝，从而不再出现「富描述被裸标题顶掉」。
    """

    moment = event.completed_at or event.due_at or datetime.now()
    return f"用户在{moment.strftime('%m月%d日')}完成了{event.title}"


def ingest_from_world_event(event, user_id: str, trace=None) -> MemoryCandidateRow | None:
    """仅完结（completed）事件；user_id 由调用方提供（WorldEvent 只含 world_id）。"""
    if _enum_value(event.status) != "completed":
        return None
    importance = _enum_value(event.importance)
    row = _create_candidate(
        user_id=user_id,
        character_id="asuna",
        source_table=SOURCE_WORLD,
        source_id=event.id,
        content=_completed_event_content(event),
        proposed_type="important_event",
        source_kind="user_stated",
        salience_init=_salience_from_world_importance(importance),
        source_ref_extra={
            "world_id": event.world_id,
            "importance": importance,
        },
    )
    if trace is not None:
        trace.record(
            "memory_ingest",
            0.0,
            extra={
                "source": SOURCE_WORLD,
                "created": 1,
                "candidate_ids": [row.id] if row else [],
            },
        )
    return row


_MAGNITUDE_SALIENCE = {"weak": 0.45, "normal": 0.6, "strong": 0.75}


def ingest_from_relationship_event(event, trace=None) -> MemoryCandidateRow | None:
    """relationship 事件 → 叙事候选；仅读事件表字段，不读 relationship_state 数值。"""
    event_type = str(_enum_value(event.type))
    cause = event.cause if (event.cause and event.cause.strip()) else ""
    content = cause if cause else f"与用户的一次{event_type}互动"
    row = _create_candidate(
        user_id=event.user_id,
        character_id="asuna",
        source_table=SOURCE_RELATIONSHIP,
        source_id=event.id,
        content=content,
        proposed_type="relationship_event",
        source_kind="user_derived",
        salience_init=_MAGNITUDE_SALIENCE.get(event.magnitude, 0.6),
        source_ref_extra={"type": event_type, "magnitude": event.magnitude},
    )
    if trace is not None:
        trace.record(
            "memory_ingest",
            0.0,
            extra={
                "source": SOURCE_RELATIONSHIP,
                "created": 1,
                "candidate_ids": [row.id],
            },
        )
    return row


def _milestone_salience(milestone_key: str) -> float:
    if milestone_key.startswith(NARRATIVE_MILESTONE_PREFIX):
        return MILESTONE_SALIENCE_NARRATIVE

    worthy = {spec.key for spec in MILESTONES if spec.memory_worthy}
    if milestone_key in worthy:
        return MILESTONE_SALIENCE_MEMORY_WORTHY
    return MILESTONE_SALIENCE_DEFAULT


def ingest_from_relationship_milestone(
    milestone, trace=None
) -> MemoryCandidateRow | None:
    """relationship 里程碑 → milestone_event 叙事候选；只读里程碑行，不读/不写数值。"""
    source_ref_extra: dict = {
        "milestone_key": milestone.milestone_key,
        "period_key": milestone.period_key,
    }
    meta = getattr(milestone, "meta", None) or {}
    insight_id = meta.get("insight_id")
    if insight_id:
        source_ref_extra["insight_id"] = insight_id
    row = _create_candidate(
        user_id=milestone.user_id,
        character_id="asuna",
        source_table=SOURCE_RELATIONSHIP_MILESTONE,
        source_id=milestone.id,
        content=milestone.title or milestone.milestone_key,
        proposed_type="milestone_event",
        source_kind="user_derived",
        salience_init=_milestone_salience(milestone.milestone_key),
        source_ref_extra=source_ref_extra,
    )
    if trace is not None:
        trace.record(
            "memory_ingest",
            0.0,
            extra={
                "source": SOURCE_RELATIONSHIP_MILESTONE,
                "created": 1,
                "candidate_ids": [row.id],
            },
        )
    return row

def ingest_from_goal_completion(user_id: str, goal_id: str, description: str) -> MemoryCandidateRow | None:
    """AUT-003 goal 完成语义：experience 候选经 P1 通道（Goal 域不直写 memories）。"""
    return _create_candidate(
        user_id=user_id,
        character_id="asuna",
        source_table=SOURCE_GOAL,
        source_id=f"{goal_id}:completed",
        content=f"完成了目标：{description}",
        proposed_type="experience",
        source_kind="ai_inferred",
        salience_init=0.75,
        source_ref_extra={"goal_id": goal_id, "outcome": "completed"},
    )
