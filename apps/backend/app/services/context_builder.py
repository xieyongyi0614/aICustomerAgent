import asyncio
import json
import logging
import time
from datetime import datetime

from app.core.settings import get_settings
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.reflection import InsightSummary
from app.models.relationship import RelationshipState
from app.prompts.builder import SHARED_EXPERIENCE_HEADER, SHARED_EXPERIENCE_NOTE
from app.services import (
    conversation_service,
    relationship_shared,
    relationship_patterns,
)
from app.services import goal_service
from app.services import memory_service
from app.services import state_service
from app.services import summary_service
from app.services.memory2 import retriever as memory2_retriever
from app.services.development import aggregate as development_aggregate
from app.services.reflection import lifecycle as reflection_lifecycle

logger = logging.getLogger(__name__)


def _load_states_with_fallback(user_id: str) -> tuple[CharacterState, RelationshipState]:
    try:
        return state_service.load_states(user_id)
    except Exception:
        logger.exception("状态读取失败，降级为默认状态")
        return CharacterState(), RelationshipState()


def _working_window(messages):
    recent = get_settings().memory_recent_context_messages
    return messages[-recent:] if recent > 0 else []


def _select_retrieval_segment(ranked) -> tuple[list, int, int]:
    """检索段装配：Freshness 排序 + 合并预算（≤v2_memory_retrieval_budget）贪心装入。

    Working 段（近期消息/信号/Scene）由既有分段承载；本函数只裁定长期检索段。
    超预算的条目按 Freshness 丢弃并计数，明细随 context_assemble_v2 步骤进 trace。
    """
    settings = get_settings()
    budget = settings.v2_memory_retrieval_budget
    fresh_first = sorted(
        ranked.items,
        key=lambda item: (_freshness(item.memory), item.score),
        reverse=True,
    )
    selected: list = []
    seen: set[str] = set()
    used = 0
    dropped = 0
    for item in fresh_first:
        memory = item.memory
        if memory.id in seen or not memory.content:
            continue
        if used + len(memory.content) > budget:
            dropped += 1
            continue
        selected.append(memory)
        seen.add(memory.id)
        used += len(memory.content)
    return selected, used, dropped


def _freshness(memory) -> tuple:
    reference = memory.last_accessed_at or memory.created_at
    if reference is None:
        return (datetime.min, 0.0)
    if reference.tzinfo is not None:
        reference = reference.replace(tzinfo=None)
    return (reference, memory.importance)


def _load_context_insights(
    user_id: str, retrieval_used: int, trace=None
) -> tuple[list[InsightSummary], dict]:
    """REF-007：高置信 active Insight → insight 段，并入检索类合并预算 800。

    记忆优先于认知（证据 > 结论）：预算 = 800 − 记忆检索段实际字符；逐条按
    confidence DESC 取用（statement 截断），落选原因逐条 trace。
    """
    settings = get_settings()
    if not settings.v2_reflection_enabled:
        return [], {}
    try:
        candidates = reflection_lifecycle.list_active_insights(
            user_id,
            "asuna",
            min_confidence=0.0,
            scopes=None,
            limit=settings.v2_reflection_context_max_items * 3,
        )
    except Exception:
        logger.exception("Insight 查询失败，insight 段降级为空")
        return [], {}
    scopes = json.loads(settings.v2_reflection_context_scopes_json)
    budget = max(0, settings.v2_memory_retrieval_budget - retrieval_used)
    selected: list[InsightSummary] = []
    reasons: dict[str, str] = {}
    used = 0
    for insight in candidates:
        if len(selected) >= settings.v2_reflection_context_max_items:
            reasons[insight.id] = "over_limit"
            continue
        if insight.confidence < settings.v2_reflection_min_confidence:
            reasons[insight.id] = "below_confidence"
            continue
        if insight.scope not in scopes:
            reasons[insight.id] = "scope_excluded"
            continue
        statement = insight.statement.strip()
        if len(statement) > settings.v2_reflection_context_statement_chars:
            statement = statement[: settings.v2_reflection_context_statement_chars] + "…"
        text = f"- ({insight.type}) {statement}"
        if used + len(text) > budget:
            reasons[insight.id] = "budget"
            continue
        selected.append(
            InsightSummary(
                insight_id=insight.id,
                statement=statement,
                type=insight.type,
                confidence=insight.confidence,
            )
        )
        used += len(text)
        reasons[insight.id] = "in"
    trace_payload = {
        "budget": budget,
        "used": used,
        "selected": [summary.insight_id for summary in selected],
        "reasons": reasons,
    }
    if trace is not None:
        trace.record("context_insight", 0.0, "ok", **trace_payload)
    return selected, trace_payload


def _select_shared_entries(collected: list, trace=None) -> tuple[list, dict]:
    """共同经历选材：Freshness（最新优先）选材 + 预算贪心装入，渲染保持时间序。"""
    settings = get_settings()
    budget = settings.v2_relationship_shared_budget_chars
    reserve = len(SHARED_EXPERIENCE_HEADER) + len(SHARED_EXPERIENCE_NOTE) + 1
    limit = settings.v2_relationship_shared_limit
    fresh_first = sorted(collected, key=lambda entry: entry.occurred_at, reverse=True)
    selected: list = []
    reasons: dict[str, str] = {}
    used = reserve
    for entry in fresh_first:
        if len(selected) >= limit:
            reasons[entry.entry_id] = "over_limit"
            continue
        line_len = len(entry.title) + 2
        if used + line_len > budget:
            reasons[entry.entry_id] = "budget"
            continue
        selected.append(entry)
        used += line_len
        reasons[entry.entry_id] = "in"
    selected.sort(key=lambda entry: entry.occurred_at)
    payload = {
        "budget": budget,
        "used": used,
        "selected": [entry.entry_id for entry in selected],
        "reasons": reasons,
    }
    if trace is not None:
        trace.record("relationship_shared", 0.0, "ok", **payload)
    return selected, payload


def _load_shared_experiences(
    user_id: str, trace=None
) -> tuple[list, dict]:
    """REL-002：共同经历投影 → 选材；投影异常一律降级为空段（fail-safe）。"""
    try:
        collected = relationship_shared.collect_shared_experiences(user_id)
    except Exception:
        logger.exception("共同经历投影失败，段降级为空")
        return [], {}
    return _select_shared_entries(collected, trace=trace)


def _load_relationship_patterns(user_id: str, trace=None) -> tuple[list, dict]:
    """REL-003：关系模式读取（双闸 Flag 在服务内）+ trace；异常降级为空。"""
    try:
        patterns, payload = relationship_patterns.read_relationship_patterns(user_id)
    except Exception:
        logger.exception("关系模式读取失败，本轮回退无注入")
        return [], {"reasons": {}, "selected": []}
    if trace is not None:
        trace.record("relationship_pattern", 0.0, "ok", **payload)
    return patterns, payload


async def build(
    session_id: str,
    user_id: str,
    current_input: str,
    trace=None,
) -> ConversationState:
    if not current_input:
        raise ValueError("current_input 必填")
    return await asyncio.to_thread(
        _build_sync, session_id, user_id, current_input, trace
    )


def _build_sync(
    session_id: str,
    user_id: str,
    current_input: str,
    trace=None,
) -> ConversationState:
    conversation_row = conversation_service.ensure_conversation(session_id, user_id)
    messages = conversation_service.load_window(session_id)
    current = summary_service.get_summary(session_id)
    summary = current.summary if current else None
    started = time.perf_counter()
    retrieval_used = 0
    dropped = 0
    insights: list[InsightSummary] = []
    insight_payload: dict = {}
    try:
        if get_settings().v2_memory_enabled:
            ranked = memory2_retriever.retrieve(user_id, current_input, trace=trace)
            memories, retrieval_used, dropped = _select_retrieval_segment(ranked)
            insights, insight_payload = _load_context_insights(
                user_id, retrieval_used, trace=trace
            )
        else:
            recalled = memory_service.retrieve(user_id, current_input)
            memories = memory_service.select_for_context(recalled)
    except Exception:
        logger.exception("记忆检索失败，降级为空记忆")
        memories = []
    if trace is not None:
        trace.record("memory_retrieval", (time.perf_counter() - started) * 1000)
    if get_settings().v2_memory_enabled and trace is not None:
        recent_window = _working_window(messages)
        trace.record(
            "context_assemble_v2",
            0.0,
            "ok",
            working_messages=len(recent_window),
            working_chars=sum(len(m.content) for m in recent_window),
            retrieval_budget=get_settings().v2_memory_retrieval_budget,
            retrieval_used=retrieval_used,
            retrieval_selected=len(memories),
            retrieval_dropped=dropped,
            insight_budget=insight_payload.get("budget", 0),
            insight_used=insight_payload.get("used", 0),
            insight_selected=len(insights),
        )
    character_state, relationship_state = _load_states_with_fallback(user_id)
    goals = [
        goal
        for goal in goal_service.load_active(user_id)
        if goal.layer is None
    ]
    development_overlay = None
    if get_settings().v2_development_enabled:
        development_overlay = development_aggregate.read_overlay(user_id)
    shared_experiences: list = []
    if get_settings().v2_relationship_evolved_enabled:
        shared_experiences, _ = _load_shared_experiences(user_id, trace=trace)
        relationship_pattern_list, _ = _load_relationship_patterns(user_id, trace=trace)
    else:
        relationship_pattern_list: list = []
    mode = getattr(conversation_row, "mode", None) or "default"
    mode_entered_at = getattr(conversation_row, "mode_entered_at", None)
    return ConversationState(
        session_id=session_id,
        user_id=user_id,
        messages=messages,
        summary=summary,
        memories=memories,
        current_input=current_input,
        character_state=character_state,
        relationship_state=relationship_state,
        goals=goals,
        insights=insights,
        development_overlay=development_overlay,
        shared_experiences=shared_experiences,
        relationship_patterns=relationship_pattern_list,
        mode=mode,
        mode_entered_at=mode_entered_at,
    )
