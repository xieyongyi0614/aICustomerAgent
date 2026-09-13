"""Evolution Engine（V2.1.0 AGENT-005）：角色长期演化的唯一写入点。

Personality 编译（Insight 证据 → 有界人格轴漂移，周级限速）、Goal Rebalance
（评估趋势 → evolution 建议进 supply 审核队列）、Evolution Ledger 只读查询。
合法通道：演化唯一输入是 active Insight（经 Reflection 三闸）；写入集中单点。
"""

import logging
import uuid
from datetime import datetime, timedelta

from app.character.asuna import evolution
from app.core.db import (
    DevelopmentChangeRow,
    GoalRow,
    InsightRow,
    PersonalityStateRow,
    SessionLocal,
)
from app.core.settings import get_settings
from app.models.goal import GoalRecord
from app.repositories import goal_repository, personality_state_repository

logger = logging.getLogger(__name__)

# 证据映射规则表：Insight statement 关键词 × 轴 → 漂移方向（幅度 = 基础幅度）
_AXIS_EVIDENCE_RULES: dict[str, tuple[tuple[str, ...], float]] = {
    "assertiveness": (("主动", "发起", "表达观点", "敢于"), +1.0),
    "warmth": (("关心", "温柔", "亲近", "安慰"), +1.0),
    "curiosity": (("好奇", "了解", "探索", "提问"), +1.0),
    "patience": (("耐心", "倾听", "重复解释"), +1.0),
}
_BASE_DELTA = 0.02


def compile_personality(user_id: str, now: datetime | None = None) -> list[dict]:
    """窗口到期轴的编译：证据收集 → 漂移提案 → 限速/边界 → 写入 + 审计。"""
    settings = get_settings()
    if not settings.v21_personality_evolution_enabled:
        return []
    now = now or datetime.now()
    window_days = max(settings.v21_evolution_window_days, 1)
    window_start = now - timedelta(days=window_days)
    insights = _recent_active_insights(user_id, window_start)
    applied: list[dict] = []
    for axis in evolution.PERSONALITY_AXES:
        evidences = _match_axis_evidence(axis, insights)
        if not evidences:
            continue
        drift = _constrain_drift(user_id, axis, evidences, now, settings, window_days)
        if drift is None:
            continue
        if _apply_drift(user_id, axis, drift, evidences[0], now):
            applied.append({"axis": axis, "delta": drift})
    return applied


def rollback_personality_for_insight(insight_id: str, now: datetime | None = None) -> int:
    """按 Insight 逆放人格漂移：恢复 current 并写 rolled_back 审计行。"""
    now = now or datetime.now()
    reverted = 0
    with SessionLocal() as session:
        rows = (
            session.query(DevelopmentChangeRow)
            .filter(
                DevelopmentChangeRow.insight_id == insight_id,
                DevelopmentChangeRow.reason == "personality",
            )
            .all()
        )
        for change in rows:
            personality = session.get(PersonalityStateRow, change.personality_state_id)
            if personality is None or not isinstance(change.before, dict):
                continue
            before = change.before.get("current")
            if before is None:
                continue
            after = personality.current
            personality.current = before
            personality.version += 1
            personality.updated_at = now
            session.add(
                DevelopmentChangeRow(
                    id=str(uuid.uuid4()),
                    personality_state_id=personality.id,
                    before={"current": after},
                    after={"current": before},
                    insight_id=insight_id,
                    reason="rolled_back",
                    created_at=now,
                )
            )
            reverted += 1
        session.commit()
    return reverted


def rebalance_goals(user_id: str, now: datetime | None = None) -> list[str]:
    """Goal Rebalance：长期劣化建议退役（abandoned, evolution_rebalance），
    建议经 supply 审核语义即直接走既有 goal_repository 出口（0 直写 goals）。"""
    settings = get_settings()
    if not settings.v21_personality_evolution_enabled:
        return []
    now = now or datetime.now()
    retired: list[str] = []
    for goal in goal_repository.list_layered_active(user_id):
        if goal.layer not in ("medium", "short_term"):
            continue
        age_days = (now - goal.created_at).days if goal.created_at else 0
        if age_days >= settings.v21_goal_medium_timeout_days * 2 and goal.priority <= 2:
            record = goal_repository.finish_goal(
                goal.id, "abandoned", failure_reason="evolution_rebalance"
            )
            if record is not None:
                retired.append(goal.id)
    return retired


def ledger(user_id: str, limit: int = 50) -> list[dict]:
    """Evolution Ledger 只读投影：development/personality/goal 三源时间线。"""
    entries: list[dict] = []
    with SessionLocal() as session:
        changes = (
            session.query(DevelopmentChangeRow, PersonalityStateRow)
            .outerjoin(
                PersonalityStateRow,
                DevelopmentChangeRow.personality_state_id == PersonalityStateRow.id,
            )
            .filter(DevelopmentChangeRow.personality_state_id.isnot(None))
            .order_by(DevelopmentChangeRow.created_at.desc())
            .limit(limit)
            .all()
        )
        for change, personality in changes:
            entries.append(
                {
                    "occurred_at": change.created_at,
                    "user_id": personality.user_id,
                    "change_kind": "personality",
                    "summary": {"axis": personality.axis},
                    "source_ref": change.insight_id,
                }
            )
        goals = (
            session.query(GoalRow)
            .filter(GoalRow.user_id == user_id, GoalRow.layer.isnot(None))
            .order_by(GoalRow.updated_at.desc())
            .limit(limit)
            .all()
        )
        for goal in goals:
            entries.append(
                {
                    "occurred_at": goal.updated_at,
                    "user_id": goal.user_id,
                    "change_kind": "goal",
                    "summary": {
                        "status": goal.status,
                        "layer": goal.layer,
                        "description": goal.description,
                    },
                    "source_ref": goal.origin,
                }
            )
    return sorted(entries, key=lambda e: e["occurred_at"] or datetime.min, reverse=True)


def _recent_active_insights(user_id: str, window_start: datetime) -> list:
    with SessionLocal() as session:
        rows = (
            session.query(InsightRow)
            .filter(
                InsightRow.user_id == user_id,
                InsightRow.status == "active",
                InsightRow.created_at >= window_start,
            )
            .order_by(InsightRow.created_at.desc())
            .limit(50)
            .all()
        )
        return [(row.id, row.statement) for row in rows]


def _match_axis_evidence(axis: str, insights: list[tuple[str, str]]) -> list[str]:
    keywords, _direction = _AXIS_EVIDENCE_RULES[axis]
    return [insight_id for insight_id, statement in insights
            if any(keyword in statement for keyword in keywords)]


def _constrain_drift(
    user_id: str, axis: str, evidences: list[str], now: datetime, settings, window_days: int
) -> float | None:
    rows = {r.axis: r for r in personality_state_repository.get_all(user_id)}
    row = rows.get(axis)
    if row is None:
        return None
    base_delta = _BASE_DELTA * min(len(evidences), 3)
    recent = _recent_drift_sum(user_id, axis, now - timedelta(days=window_days))
    max_week = settings.v21_evolution_max_drift_per_week
    if abs(recent) + base_delta > max_week:
        return None
    target = row.current + base_delta
    if target > row.bound_max or target < row.bound_min:
        target = min(row.bound_max, max(row.bound_min, target))
        if abs(target - row.current) < 1e-9:
            return None
    return round(target - row.current, 6)


def _recent_drift_sum(user_id: str, axis: str, since: datetime) -> float:
    with SessionLocal() as session:
        rows = (
            session.query(DevelopmentChangeRow)
            .join(
                PersonalityStateRow,
                DevelopmentChangeRow.personality_state_id == PersonalityStateRow.id,
            )
            .filter(
                PersonalityStateRow.user_id == user_id,
                PersonalityStateRow.axis == axis,
                DevelopmentChangeRow.created_at >= since,
            )
            .all()
        )
        return sum(
            (change.after or {}).get("delta", 0.0)
            for change in rows
            if isinstance(change.after, dict)
        )


def _apply_drift(user_id: str, axis: str, delta: float, insight_id: str, now: datetime) -> bool:
    with SessionLocal() as session:

        row = (
            session.query(PersonalityStateRow)
            .filter(
                PersonalityStateRow.user_id == user_id,
                PersonalityStateRow.axis == axis,
            )
            .first()
        )
        if row is None:
            return False
        before = row.current
        row.current = round(before + delta, 6)
        row.source_insight_id = insight_id
        row.version += 1
        row.updated_at = now
        session.add(
            DevelopmentChangeRow(
                id=str(uuid.uuid4()),
                development_state_id=None,
                personality_state_id=row.id,
                before={"current": before},
                after={"current": row.current, "delta": delta},
                insight_id=insight_id,
                reason="personality",
                created_at=now,
            )
        )
        session.commit()
        logger.info("personality 漂移：%s %s %+0.4f", user_id, axis, delta)
        return True
