"""V2.3.0 UserSituationTracker（architecture.md §5.4 用户事件源）。

确定性模式优先（宁缺毋滥）；LLM 辅助为独立子闸的增强路径，失败静默降级。
处境是世界域事实（角色视角下用户属于世界），不触碰 Character 域。
"""

import logging
import random
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.core.settings import get_settings
from app.models.world import EventImportance
from app.models.world_simulation import (
    SituationDimension,
    SituationSource,
    SituationStatus,
    UserSituation,
)
from app.repositories import world_simulation_repository

logger = logging.getLogger(__name__)


class SituationDetection(BaseModel):
    dimension: str | None = None
    summary: str | None = None
    intensity: int | None = None


class _Pattern:
    def __init__(self, dimension: SituationDimension, keywords: tuple[str, ...],
                 intensity_hint: int, label: str,
                 dismiss_keywords: tuple[str, ...] = ()) -> None:
        self.dimension = dimension
        self.keywords = keywords
        self.intensity_hint = intensity_hint
        self.label = label
        self.dismiss_keywords = dismiss_keywords


SITUATION_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern(
        SituationDimension.HEALTH,
        ("生病", "感冒", "发烧", "发热", "头疼", "头痛", "不舒服", "去医院", "吃药", "腹泻"),
        4,
        "身体不适",
        ("好了", "没事了", "痊愈", "恢复了", "退烧了", "病好了"),
    ),
    _Pattern(
        SituationDimension.WORK_PRESSURE,
        ("加班", "deadline", "项目上线", "压力大", "忙不过来", "赶工", "通宵"),
        3,
        "工作压力大",
        ("忙完了", "项目结束了", "上线完了", "不忙了"),
    ),
    _Pattern(
        SituationDimension.SCHEDULE_CHANGE,
        ("考试", "答辩", "面试", "复习", "备考", "补考"),
        3,
        "重要日程临近",
        ("考完了", "面完了", "答辩完了", "结束了"),
    ),
    _Pattern(
        SituationDimension.TRAVEL,
        ("出差", "去外地", "旅行中", "在路上", "高铁上", "飞机上", "度假"),
        2,
        "外出中",
        ("回来了", "到家了", "回来了", "旅行结束了"),
    ),
    _Pattern(
        SituationDimension.EMOTIONAL_CONTEXT,
        ("心情不好", "难过", "烦躁", "委屈", "emo", "不开心", "郁闷"),
        3,
        "情绪低落",
        (),
    ),
)

_DISMISSAL_RECOVERY = ("好了", "没事了", "结束了", "回来了", "到家了", "忙完了", "恢复了")


def _match_dimension(text: str) -> _Pattern | None:
    lowered = text.lower()
    for pattern in SITUATION_PATTERNS:
        if any(keyword in lowered for keyword in pattern.keywords):
            return pattern
    return None


def _match_dismissal(text: str, pattern: _Pattern) -> bool:
    lowered = text.lower()
    if pattern.dismiss_keywords and any(k in lowered for k in pattern.dismiss_keywords):
        return True
    return any(k in lowered for k in _DISMISSAL_RECOVERY)


def _event_importance(intensity: int) -> str:
    return EventImportance.HIGH.value if intensity >= 4 else EventImportance.NORMAL.value


def _emit_condition_event(user_id: str, situation: UserSituation, kind: str) -> None:
    from app.application import world_engine

    title = situation.summary if kind == "detected" else f"{situation.summary}（已结束）"
    world_engine.create_event(
        user_id,
        event_type="user_condition",
        title=title[:50],
        importance=_event_importance(situation.intensity)
        if kind == "detected"
        else EventImportance.LOW.value,
        source="user_evidence",
        status="completed",
        payload={
            "kind": kind,
            "situation_id": situation.id,
            "dimension": situation.dimension.value,
            "summary": situation.summary,
            "intensity": situation.intensity,
        },
    )


def _supersede_active(user_id: str, dimension: SituationDimension, now: datetime) -> None:
    active = world_simulation_repository.get_active_situation(user_id, dimension)
    if active is None:
        return
    active.status = SituationStatus.EXPIRED
    world_simulation_repository.save_situation(active)


def detect_from_message(
    user_id: str,
    text: str,
    evidence: dict | None = None,
    now: datetime | None = None,
) -> UserSituation | None:
    """确定性检出主入口：命中即落库并发事件；未命中走 LLM 辅助闸。"""
    try:
        if not text:
            return None
        current = now or datetime.now()
        dismissed = dismiss_matching(user_id, text, current)
        pattern = _match_dimension(text)
        if pattern is None:
            if not dismissed:
                return _llm_assist_gate(user_id, text, evidence, current)
            return None
        settings = get_settings()
        intensity = max(1, min(5, pattern.intensity_hint))
        situation = UserSituation(
            id=world_simulation_repository.new_situation_id(),
            user_id=user_id,
            dimension=pattern.dimension,
            summary=f"用户{pattern.label}",
            intensity=intensity,
            status=SituationStatus.ACTIVE,
            source=SituationSource.CONVERSATION_PATTERN,
            evidence={**(evidence or {}), "quote": text[:100], "matched": pattern.label},
            detected_at=current,
            valid_until=current + timedelta(hours=settings.user_situation_valid_hours),
        )
        _supersede_active(user_id, pattern.dimension, current)
        world_simulation_repository.save_situation(situation)
        _emit_condition_event(user_id, situation, "detected")
        return situation
    except Exception:
        logger.exception("用户处境检出失败")
        return None


def dismiss_matching(user_id: str, text: str, now: datetime) -> list[str]:
    dismissed: list[str] = []
    if not text:
        return dismissed
    for pattern in SITUATION_PATTERNS:
        if not _match_dismissal(text, pattern):
            continue
        active = world_simulation_repository.get_active_situation(user_id, pattern.dimension)
        if active is None:
            continue
        active.status = SituationStatus.DISMISSED
        world_simulation_repository.save_situation(active)
        _emit_condition_event(user_id, active, "ended")
        dismissed.append(active.id)
    return dismissed


def expire_and_notify(user_id: str, now: datetime | None = None) -> list[UserSituation]:
    """到期过期（world_simulation 维护步调用）；结束事件供记忆分流。"""
    current = now or datetime.now()
    expired = world_simulation_repository.expire_stale_situations(user_id, current)
    for situation in expired:
        _emit_condition_event(user_id, situation, "ended")
    return expired


def active_situations(user_id: str) -> list[UserSituation]:
    return world_simulation_repository.list_situations(
        user_id, statuses=(SituationStatus.ACTIVE,)
    )


def _llm_assist_gate(
    user_id: str,
    text: str,
    evidence: dict | None,
    now: datetime,
) -> UserSituation | None:
    settings = get_settings()
    if not settings.world_llm_assist_enabled:
        return None
    if random.random() > settings.world_llm_assist_sample_rate:
        return None
    return llm_assist_detect(user_id, text, evidence, now)


def llm_assist_detect(
    user_id: str,
    text: str,
    evidence: dict | None = None,
    now: datetime | None = None,
) -> UserSituation | None:
    """LLM 辅助检出：仅确定性无命中且子闸开启时被调用；失败静默降级。"""
    try:
        from app.chains.structured import build_structured_chain

        dimensions = ", ".join(d.value for d in SituationDimension)
        messages = [
            (
                "system",
                "从用户消息判断其当前处境。dimension 仅可为："
                f"{dimensions}；无处境时全部留空。",
            ),
            ("user", text[:500]),
        ]
        chain = build_structured_chain(messages, SituationDetection)
        result = chain.invoke({})
        valid_values = {d.value for d in SituationDimension}
        if not result.dimension or result.dimension not in valid_values:
            return None
        dimension = SituationDimension(result.dimension)
        current = now or datetime.now()
        settings = get_settings()
        intensity = max(1, min(5, result.intensity or 3))
        situation = UserSituation(
            id=world_simulation_repository.new_situation_id(),
            user_id=user_id,
            dimension=dimension,
            summary=(result.summary or "用户处境变化")[:100],
            intensity=intensity,
            status=SituationStatus.ACTIVE,
            source=SituationSource.LLM_ASSIST,
            evidence={**(evidence or {}), "quote": text[:100], "record": "llm"},
            detected_at=current,
            valid_until=current + timedelta(hours=settings.user_situation_valid_hours),
        )
        _supersede_active(user_id, dimension, current)
        world_simulation_repository.save_situation(situation)
        _emit_condition_event(user_id, situation, "detected")
        return situation
    except Exception:
        logger.exception("LLM 辅助处境检出失败（静默降级）")
        return None
