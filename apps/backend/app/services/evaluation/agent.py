"""Agent Evaluation（V2.1.0 AGENT-006）：Agent 级六指标 + 周期快照 + 演化议题。

只读旁路铁律：本模块对业务表零写入（唯一写面 = agent_metric_snapshots）。
规则优先 0 LLM；缺材料指标出 None（不污染趋势）。趋势越限 → 演化议题 →
经 Reflection 既有 event 触发通道进入证据窗口（三闸全额生效）。
"""

import logging
from datetime import datetime, timedelta

from app.core import timeutil
from app.core.settings import get_settings
from app.repositories import (
    action_repository,
    agent_metric_repository,
    decision_repository,
    goal_repository,
)
from app.services.conversation import state as state_service

logger = logging.getLogger(__name__)

METRIC_NAMES = (
    "persona_consistency",
    "memory_accuracy",
    "action_quality",
    "relationship_quality",
    "goal_progress",
    "decision_quality",
)


def run_daily_snapshot(user_id: str, now: datetime | None = None) -> dict:
    settings = get_settings()
    now = timeutil.ensure_aware(now) or timeutil.now()
    window_start = timeutil.local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    metrics = _compute_metrics(user_id, now)
    history = [
        row
        for row in agent_metric_repository.list_recent(
            user_id, limit=settings.metric_trend_windows
        )
        if row.window_start < window_start
    ]
    trend = _trend(metrics, history, settings)
    agent_metric_repository.save(
        user_id, window_start, now, metrics=metrics, trend=trend, now=now
    )
    topics = _emit_topics(user_id, trend, settings, now)
    return {"status": "ok", "metrics": metrics, "trend": trend, "topics": topics}


def _compute_metrics(user_id: str, now: datetime) -> dict:
    day_start = timeutil.local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    metrics: dict = {name: None for name in METRIC_NAMES}

    metrics["action_quality"] = _action_quality(user_id, day_start, now)
    metrics["decision_quality"] = _decision_quality(user_id, day_start, now)
    metrics["goal_progress"] = _goal_progress(user_id, now)
    metrics["relationship_quality"] = _relationship_quality(user_id)
    metrics["persona_consistency"] = _persona_consistency(user_id)
    return metrics


def _action_quality(user_id: str, day_start: datetime, now: datetime) -> float | None:
    records = [
        r
        for r in action_repository.list_records(user_id, limit=50)
        if r.created_at and day_start <= r.created_at <= now
    ]
    if not records:
        return None
    terminal = [r for r in records if r.status in ("succeeded", "failed")]
    if not terminal:
        return None
    return round(sum(1 for r in terminal if r.status == "succeeded") / len(terminal), 4)


def _decision_quality(user_id: str, day_start: datetime, now: datetime) -> float | None:
    records = decision_repository.search(user_id=user_id, limit=50)
    relevant = [
        r
        for r in records
        if r.created_at and r.created_at >= day_start and r.candidates
    ]
    if not relevant:
        return None
    scored = [
        r
        for r in relevant
        if r.outcome in ("delivered", "enqueue_failed", "executed", "failed")
    ]
    if not scored:
        return None
    good = sum(1 for r in scored if r.outcome not in ("enqueue_failed", "failed"))
    return round(good / len(scored), 4)


def _goal_progress(user_id: str, now: datetime) -> float | None:
    goals = goal_repository.list_layered_active(user_id)
    if not goals:
        return None
    settings = get_settings()
    healthy = 0
    for goal in goals:
        overdue = False
        if goal.created_at:
            age = now - goal.created_at
            if goal.layer == "medium" and age > timedelta(days=settings.goal_medium_timeout_days):
                overdue = True
            if goal.layer == "short_term" and age > timedelta(
                hours=settings.goal_short_timeout_hours
            ):
                overdue = True
        healthy += 0 if overdue else 1
    return round(healthy / len(goals), 4)


def _relationship_quality(user_id: str) -> float | None:
    try:
        _character, relationship = state_service.load_states(user_id)
    except Exception:
        return None
    intimacy = float(getattr(relationship, "intimacy", 0.0) or 0.0)
    trust = float(getattr(relationship, "trust", 0.0) or 0.0)
    tension = float(getattr(relationship, "tension", 0.0) or 0.0)
    return round(max(0.0, min(1.0, (intimacy + trust) / 2 - tension / 4)), 4)


def _persona_consistency(user_id: str) -> float | None:
    from app.repositories import personality_state_repository
    from app.character.asuna import evolution

    rows = personality_state_repository.get_all(user_id)
    if not rows:
        return None
    in_bounds = sum(
        1 for r in rows if r.bound_min <= r.current <= r.bound_max
    )
    return round(in_bounds / len(rows), 4)


def _trend(metrics: dict, history: list, settings) -> dict:
    """趋势：方向 + 连续越限窗口数（streak）。

    越限判定 = 当前窗口与之前连续窗口的值均低于该指标阈值，且连续数达到
    `metric_breach_streak`（默认 2，与既有「当前+前值」规则等价）。
    `metric_trend_windows` 为历史取数深度；`windows` 字段回报真实连续数。
    """
    streak_required = max(settings.metric_breach_streak, 1)
    trend: dict = {}
    for name, value in metrics.items():
        if value is None:
            continue
        prior_values = [h.metrics.get(name) for h in history]
        previous = next((v for v in prior_values if v is not None), None)
        threshold = getattr(settings, f"metric_floor_{name}", None)
        streak = 0
        if threshold is not None and value < threshold:
            streak = 1
            for prior in prior_values:
                if prior is None or prior >= threshold:
                    break
                streak += 1
        trend[name] = {
            "direction": (
                "up" if previous is not None and value > previous else
                "down" if previous is not None and value < previous else "flat"
            ),
            "previous": previous,
            "breached": streak >= streak_required,
            "windows": streak,
        }
    return trend


def _emit_topics(user_id: str, trend: dict, settings, now: datetime) -> list[str]:
    """趋势越限 -> 演化议题（结构化文本）；经 Reflection 既有 event 触发通道。"""
    topics: list[str] = []
    for name, info in trend.items():
        if not info.get("breached"):
            continue
        topic = (
            f"agent_metric:{name} 连续 {info['windows']} 窗口低于阈值，"
            "当前值与历史值请作为证据窗口核查行为模式成因"
        )
        topics.append(topic)
        logger.warning("演化议题：%s", topic)
    if topics:
        try:
            from app.services.reflection import triggers as reflection_triggers

            reflection_triggers.trigger_for_user(user_id, trigger="event", now=now)
        except Exception:
            logger.exception("演化议题进入 Reflection 触发通道失败，已留痕")
    return topics
