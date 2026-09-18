"""Evolution Engine（V2.1.0 AGENT-005）：角色长期演化的唯一写入点。

Personality 编译（Insight 证据 → 有界人格轴漂移，周级限速）、Goal Rebalance
（建议生成 propose_rebalance 纯读 + supply 审核侧应用 apply_rebalance）、
Evolution Ledger 只读投影（personality/development/goal/relationship/memory 五源）。
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
    Memory,
    PersonalityStateRow,
    RelationshipEventRow,
    SessionLocal,
)
from app.core.settings import get_settings
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
_REBALANCE_MAX_PRIORITY = 2


def compile_personality(user_id: str, now: datetime | None = None) -> list[dict]:
    """窗口到期轴的编译：证据收集 → 漂移提案 → 限速/边界 → 写入 + 审计。"""
    settings = get_settings()
    if not settings.personality_evolution_enabled:
        return []
    now = now or datetime.now()
    window_days = max(settings.evolution_window_days, 1)
    window_start = now - timedelta(days=window_days)
    insights = _recent_active_insights(user_id, window_start)
    applied: list[dict] = []
    for axis in evolution.PERSONALITY_AXES:
        evidences, direction = _match_axis_evidence(axis, insights)
        if not evidences:
            continue
        drift = _constrain_drift(
            user_id, axis, direction, evidences, now, settings, window_days
        )
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


def propose_rebalance(user_id: str, now: datetime | None = None) -> list[dict]:
    """Goal Rebalance 建议生成（纯读，0 写）：长期未推进的低优先 L2/L1 目标。

    建议不落地、不写 goals；由 supply 审核侧（goal_stack 阶段）消费后决定是否退役。
    阈值取该层超时窗口的**半程**：必须早于 goal_stack.retire_overdue 的硬超时
    （整程），否则建议永远不可达（硬超时先退役，活跃集里已无该目标）。
    """
    settings = get_settings()
    if not settings.personality_evolution_enabled:
        return []
    now = now or datetime.now()
    proposals: list[dict] = []
    for goal in goal_repository.list_layered_active(user_id):
        if goal.layer not in ("medium", "short_term"):
            continue
        if goal.priority > _REBALANCE_MAX_PRIORITY or goal.created_at is None:
            continue
        half_window = _rebalance_half_window(goal.layer, settings)
        if half_window is None:
            continue
        age = now - goal.created_at
        if age < half_window:
            continue
        proposals.append(
            {
                "goal_id": goal.id,
                "layer": goal.layer,
                "age_days": age.days,
                "priority": goal.priority,
                "reason": "evolution_rebalance",
            }
        )
    return proposals


def _rebalance_half_window(layer: str, settings) -> timedelta | None:
    if layer == "medium":
        return timedelta(days=max(settings.goal_medium_timeout_days, 2) / 2)
    if layer == "short_term":
        return timedelta(hours=max(settings.goal_short_timeout_hours, 2) / 2)
    return None


def apply_rebalance(user_id: str, proposals: list[dict], now: datetime | None = None) -> list[str]:
    """supply 审核侧应用入口：退役经既有 finish_goal 状态机出口，不新增写路径。"""
    retired: list[str] = []
    for proposal in proposals:
        record = goal_repository.finish_goal(
            proposal["goal_id"], "abandoned", failure_reason=proposal["reason"]
        )
        if record is not None:
            retired.append(proposal["goal_id"])
    if retired:
        logger.info(
            "goal rebalance 退役：%s goals=%s", user_id, retired
        )
    return retired


def rebalance_goals(user_id: str, now: datetime | None = None) -> list[str]:
    """建议 + 应用（等价 supply 审核通过）：保留既有单入口语义供周期任务调用。"""
    return apply_rebalance(user_id, propose_rebalance(user_id, now), now)


def ledger(user_id: str, limit: int = 50) -> list[dict]:
    """Evolution Ledger 只读投影：development/personality/goal/relationship/memory 五源时间线。"""
    entries: list[dict] = []
    with SessionLocal() as session:
        changes = (
            session.query(DevelopmentChangeRow, PersonalityStateRow)
            .join(
                PersonalityStateRow,
                DevelopmentChangeRow.personality_state_id == PersonalityStateRow.id,
            )
            .filter(PersonalityStateRow.user_id == user_id)
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
                    "summary": {
                        "axis": personality.axis,
                        "before": (change.before or {}).get("current"),
                        "after": (change.after or {}).get("current"),
                    },
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
        events = (
            session.query(RelationshipEventRow)
            .filter(RelationshipEventRow.user_id == user_id)
            .order_by(RelationshipEventRow.created_at.desc())
            .limit(limit)
            .all()
        )
        for event in events:
            entries.append(
                {
                    "occurred_at": event.created_at,
                    "user_id": event.user_id,
                    "change_kind": "relationship",
                    "summary": {"type": event.type, "magnitude": event.magnitude},
                    "source_ref": event.cause or None,
                }
            )
        superseded = (
            session.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.superseded_by.isnot(None),
            )
            .order_by(Memory.updated_at.desc())
            .limit(limit)
            .all()
        )
        for memory in superseded:
            entries.append(
                {
                    "occurred_at": memory.updated_at,
                    "user_id": memory.user_id,
                    "change_kind": "memory",
                    "summary": {"type": memory.type, "content": memory.content[:40]},
                    "source_ref": memory.superseded_by,
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


def _match_axis_evidence(axis: str, insights: list[tuple[str, str]]) -> tuple[list[str], float]:
    keywords, direction = _AXIS_EVIDENCE_RULES[axis]
    matched = [insight_id for insight_id, statement in insights
               if any(keyword in statement for keyword in keywords)]
    return matched, direction


def _constrain_drift(
    user_id: str,
    axis: str,
    direction: float,
    evidences: list[str],
    now: datetime,
    settings,
    window_days: int,
) -> float | None:
    """限速 + 边界钳制：单窗口至多一次漂移（连续同向需多窗口证据累积），
    单次幅度不超过周级上限；越界钳制到 bound。"""
    rows = {r.axis: r for r in personality_state_repository.get_all(user_id)}
    row = rows.get(axis)
    if row is None:
        return None
    max_week = settings.evolution_max_drift_per_week
    if max_week <= 0:
        return None
    used = _recent_drift_sum(user_id, axis, now - timedelta(days=window_days))
    if abs(used) > 1e-9:
        return None
    base_delta = min(_BASE_DELTA * min(len(evidences), 3), max_week)
    target = row.current + direction * base_delta
    clamped = min(row.bound_max, max(row.bound_min, target))
    delta = round(clamped - row.current, 6)
    if abs(delta) < 1e-9:
        return None
    return delta


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
