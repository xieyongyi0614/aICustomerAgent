"""V8.5 M4 Milestone System（milestone-system.md）：关系编年史注册表 + 检测。

里程碑 = 一次性事件；bonus 走独立 cap（不进 events 账本、不侵单日预算）；
解锁 key 只是门牌，语义由 M7/M8 消费方定义。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.core import timeutil
from app.core.settings import get_settings
from app.models.relationship import (
    MilestoneRecord,
    RelationshipDelta,
    RelationshipState,
)
from app.repositories import relationship_milestone_repository
from app.engines.relationship_evolution import clamp01

logger = logging.getLogger(__name__)

NEGATIVE_MOODS = ("sad", "angry", "worried", "anxious", "tired")

CONFLICT_RECOVERY_UNLOCK = "conflict_recovery_available"
EMOTIONAL_SUPPORT_DEEP_UNLOCK = "emotional_support_deep"
STAGE_UNLOCKS = {
    "friend": ("casual_check_in",),
    "close_friend": ("proactive_goodnight", "personal_topics"),
    "partner": ("deep_commitment_language",),
}

_DIMENSIONS = ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")


@dataclass(frozen=True)
class MilestoneContext:
    user_id: str
    event_type: str
    state_before: RelationshipState
    state_after: RelationshipState
    stage_before: str
    stage_after: str
    ledger_empty_before: bool
    shared_activity: bool = False
    character_mood: str = "calm"
    character_intensity: float = 0.0
    conflict_transition: str = ""
    first_interaction_month: str = ""
    now: datetime = field(default_factory=timeutil.now)


@dataclass(frozen=True)
class MilestoneSpec:
    key: str
    title: str
    detect: object
    bonus: RelationshipDelta = field(default_factory=RelationshipDelta)
    memory_worthy: bool = False
    unlocks: tuple[str, ...] = ()


def _stage(name: str):
    def _detect(ctx: MilestoneContext) -> bool:
        return ctx.stage_after == name and ctx.stage_before != name

    return _detect


def _monthly_anniversary(ctx: MilestoneContext) -> bool:
    """认识满 N 月（period_key=YYYY-MM）：本月未刻印且满月未久（28 天容差）。"""
    if not ctx.first_interaction_month:
        return False
    now_month = ctx.now.strftime("%Y-%m")
    if ctx.first_interaction_month == now_month:
        return False
    year, mon = ctx.first_interaction_month.split("-")
    first = datetime(int(year), int(mon), 1)
    return (ctx.now - first).days >= 28


MILESTONES: list[MilestoneSpec] = [
    MilestoneSpec(
        key="first_interaction",
        title="第一次聊天",
        detect=lambda ctx: ctx.ledger_empty_before,
        bonus=RelationshipDelta(familiarity=0.02),
    ),
    MilestoneSpec(
        key="first_self_disclosure",
        title="第一次袒露心事",
        detect=lambda ctx: ctx.event_type == "intimate_moment",
        bonus=RelationshipDelta(trust=0.03, intimacy=0.02),
        memory_worthy=True,
        unlocks=(EMOTIONAL_SUPPORT_DEEP_UNLOCK,),
    ),
    MilestoneSpec(
        key="first_support_in_distress",
        title="低谷时的陪伴",
        detect=lambda ctx: (
            ctx.event_type == "user_care"
            and ctx.character_intensity > 0.6
            and ctx.character_mood in NEGATIVE_MOODS
        ),
        bonus=RelationshipDelta(trust=0.04, intimacy=0.02, comfort=0.03),
        memory_worthy=True,
    ),
    MilestoneSpec(
        key="first_promise_kept",
        title="第一次兑现承诺",
        detect=lambda ctx: ctx.event_type == "promise_kept",
        bonus=RelationshipDelta(trust=0.04),
        memory_worthy=True,
    ),
    MilestoneSpec(
        key="first_shared_activity",
        title="第一次共同完成一件事",
        detect=lambda ctx: ctx.shared_activity,
        bonus=RelationshipDelta(familiarity=0.03, comfort=0.02),
        memory_worthy=True,
    ),
    MilestoneSpec(
        key="first_conflict",
        title="第一次冲突",
        detect=lambda ctx: ctx.event_type == "conflict",
        memory_worthy=True,
        unlocks=(CONFLICT_RECOVERY_UNLOCK,),
    ),
    MilestoneSpec(
        key="first_apology",
        title="第一次道歉",
        detect=lambda ctx: ctx.conflict_transition == "recovery_started",
        bonus=RelationshipDelta(comfort=0.03),
        memory_worthy=True,
    ),
    MilestoneSpec(
        key="first_forgiveness",
        title="第一次和解",
        detect=lambda ctx: ctx.conflict_transition == "reconciled",
        bonus=RelationshipDelta(trust=0.02, comfort=0.05),
        memory_worthy=True,
    ),
    MilestoneSpec(
        key="stage_friend",
        title="成为朋友",
        detect=_stage("friend"),
        memory_worthy=True,
        unlocks=STAGE_UNLOCKS["friend"],
    ),
    MilestoneSpec(
        key="stage_close_friend",
        title="成为亲密朋友",
        detect=_stage("close_friend"),
        memory_worthy=True,
        unlocks=STAGE_UNLOCKS["close_friend"],
    ),
    MilestoneSpec(
        key="stage_partner",
        title="成为恋人",
        detect=_stage("partner"),
        memory_worthy=True,
        unlocks=STAGE_UNLOCKS["partner"],
    ),
    MilestoneSpec(
        key="monthly_anniversary",
        title="认识满一个月",
        detect=_monthly_anniversary,
        bonus=RelationshipDelta(comfort=0.02),
    ),
]


def keyed(key: str) -> MilestoneSpec:
    """按 key 取 spec（测试与调试用）。"""
    return next(spec for spec in MILESTONES if spec.key == key)


def _cap_bonus(bonus: RelationshipDelta) -> RelationshipDelta:
    """里程碑 bonus 独立上限 rel_milestone_delta_cap（不受单轮/单日上限约束）。"""
    cap = get_settings().rel_milestone_delta_cap
    values = {dim: max(-cap, min(cap, getattr(bonus, dim))) for dim in _DIMENSIONS}
    return RelationshipDelta(**values)


def _period_key(spec: MilestoneSpec, ctx: MilestoneContext) -> str:
    if spec.key == "monthly_anniversary":
        return ctx.now.strftime("%Y-%m")
    return ""


def detect_milestones(
    ctx: MilestoneContext, existing: set[tuple[str, str]] | None = None
) -> list[tuple[MilestoneSpec, RelationshipDelta, str]]:
    """逐 spec 谓词检测（纯函数）：返回 (spec, capped_bonus, period_key)。"""
    existing = existing if existing is not None else set()
    hits: list[tuple[MilestoneSpec, RelationshipDelta, str]] = []
    for spec in MILESTONES:
        period_key = _period_key(spec, ctx)
        if (spec.key, period_key) in existing:
            continue
        try:
            matched = spec.detect(ctx)
        except Exception:
            logger.exception("里程碑谓词异常，跳过：%s", spec.key)
            continue
        if matched:
            hits.append((spec, _cap_bonus(spec.bonus), period_key))
    return hits


def process_milestones(
    ctx: MilestoneContext, state: RelationshipState
) -> tuple[RelationshipState, list[MilestoneRecord]]:
    """检测 + 落库 + bonus 应用（独立小事务；检测异常跳过当轮，下轮补检）。"""
    settings = get_settings()
    if not settings.rel_milestone_enabled:
        return state, []
    try:
        existing = relationship_milestone_repository.existing_keys(ctx.user_id)
    except Exception:
        logger.exception("已达成里程碑集合读取失败，跳过本轮里程碑检测")
        return state, []
    hits = detect_milestones(ctx, existing)
    records: list[MilestoneRecord] = []
    updated = state
    for spec, bonus, period_key in hits:
        try:
            record = relationship_milestone_repository.create_milestone(
                user_id=ctx.user_id,
                milestone_key=spec.key,
                title=spec.title,
                period_key=period_key,
                applied_bonus=bonus,
                unlocks=spec.unlocks,
                now=ctx.now,
            )
        except Exception:
            logger.exception("里程碑写入失败，跳过：%s", spec.key)
            continue
        if record is None:
            continue
        records.append(record)
        if any(getattr(bonus, dim) != 0.0 for dim in _DIMENSIONS):
            updates = {
                dim: clamp01(getattr(updated, dim) + getattr(bonus, dim))
                for dim in _DIMENSIONS
            }
            updated = updated.model_copy(update=updates)
    return updated, records