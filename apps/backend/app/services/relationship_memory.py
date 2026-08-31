"""V8.5 M6 Memory Integration（memory-integration.md）：关系记忆候选 + 投递。

路由边界：账本记"对关系有影响的事"（全量），记忆记"角色该长期记住的事"。
纯函数产出候选 → 投递既有 memory 仓储（零侵入 V4，不改 extractor/第 5 步）。
source 落 ai_inferred（V4 既有枚举零改动），type=relationship_event + 模板标记。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.character.asuna.relationship_lexicon import MEMORY_TEMPLATES
from app.models.relationship import MilestoneRecord

logger = logging.getLogger(__name__)

MEMORY_SOURCE = "relationship_evolution"
MEMORY_TYPE = "relationship_event"
MEMORY_DEDUP_WINDOW_HOURS = 24.0

IMPORTANCE_MILESTONE = 0.90
IMPORTANCE_RECONCILED = 0.85
IMPORTANCE_STRONG_DISCLOSURE = 0.80
IMPORTANCE_CONFLICT = 0.75
IMPORTANCE_PROMISE = 0.80

CAUSE_CLIP_CHARS = 20
_memory_dedup: dict[str, datetime] = {}


@dataclass(frozen=True)
class MemoryCandidate:
    content: str
    importance: float
    template_key: str
    type: str = MEMORY_TYPE
    source: str = "ai_inferred"
    character_id: str = "asuna"


def render_template(template_key: str, cause: str = "") -> str:
    """确定性渲染（同输入同输出）；cause 截断 20 字防敏感信息直入记忆。"""
    template = MEMORY_TEMPLATES.get(template_key)
    if template is None:
        return ""
    return template.format(cause=cause[:CAUSE_CLIP_CHARS])


def _dedup_key(content: str) -> str:
    return content


def _seen_recently(content: str, now: datetime) -> bool:
    seen_at = _memory_dedup.get(_dedup_key(content))
    if seen_at is None:
        return False
    return (now - seen_at).total_seconds() / 3600 < MEMORY_DEDUP_WINDOW_HOURS


def _mark(content: str, now: datetime) -> None:
    _memory_dedup[_dedup_key(content)] = now


def to_memory_candidates(
    turn_event,
    milestones: list[MilestoneRecord],
    conflict_transition: str,
    now: datetime | None = None,
) -> list[MemoryCandidate]:
    """路由边界表（memory-integration.md §1）的纯函数实现。

    turn_event：本轮 conversation 账本行（无则 None）；
    milestones：本轮新刻印（memory_worthy 者投递）；
    conflict_transition：reconciled 时投递和解。
    """
    now = now or datetime.now()
    candidates: list[MemoryCandidate] = []
    if turn_event is not None:
        event_type = getattr(turn_event, "type", "none")
        magnitude = getattr(turn_event, "magnitude", "weak")
        cause = getattr(turn_event, "cause", "") or ""
        if event_type == "intimate_moment" and magnitude == "strong":
            candidates.append(
                MemoryCandidate(
                    content=render_template("first_self_disclosure", cause),
                    importance=IMPORTANCE_STRONG_DISCLOSURE,
                    template_key="first_self_disclosure",
                )
            )
        elif event_type in ("conflict", "boundary_violation"):
            candidates.append(
                MemoryCandidate(
                    content=render_template("conflict", cause),
                    importance=IMPORTANCE_CONFLICT,
                    template_key="conflict",
                )
            )
        elif event_type == "promise_broken":
            candidates.append(
                MemoryCandidate(
                    content=render_template("promise_broken"),
                    importance=IMPORTANCE_PROMISE,
                    template_key="promise_broken",
                )
            )
    for milestone in milestones:
        content = render_template(milestone.milestone_key)
        if not content:
            content = milestone.title
        candidates.append(
            MemoryCandidate(
                content=content,
                importance=IMPORTANCE_MILESTONE,
                template_key=milestone.milestone_key,
            )
        )
    if conflict_transition == "reconciled":
        candidates.append(
            MemoryCandidate(
                content=render_template("reconciled"),
                importance=IMPORTANCE_RECONCILED,
                template_key="reconciled",
            )
        )
    unique: list[MemoryCandidate] = []
    for candidate in candidates:
        if not candidate.content or _seen_recently(candidate.content, now):
            continue
        unique.append(candidate)
        _mark(candidate.content, now)
    return unique


def deliver_candidates(candidates: list[MemoryCandidate], user_id: str) -> int:
    """投递既有 memory 仓储；失败不回滚演化（只降级）。"""
    from app.repositories import memory_repository

    delivered = 0
    for candidate in candidates:
        try:
            memory_repository.create_memory(
                user_id=user_id,
                character_id=candidate.character_id,
                content=candidate.content,
                memory_type=candidate.type,
                importance=candidate.importance,
                confidence=candidate.importance,
                source=candidate.source,
            )
            delivered += 1
        except Exception:
            logger.exception("关系记忆投递失败，跳过该条")
    return delivered