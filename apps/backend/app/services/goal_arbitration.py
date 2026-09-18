"""V2.0.0 AUT-004 仲裁器：Priority / Conflict / Abandonment / 状态机全景。

六语义裁决全确定性（0 LLM）：显式优先级 + Development/Relationship 只读
调制 → 同 (layer, domain) 顶层组互斥（suspended 留痕）→ keeper 终态复活 →
父子级联；abandonment 双信号置信（长期无进展 + 低相关，保守阈值）。状态
变更唯一走 set_status 转换表守卫；每次 suspended/abandoned/复活写
goal_lifecycle decision_records（不变量 2：Goal 变更可归因）。
"""

import logging
import time
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.observability import DecisionKind, DecisionRecord
from app.repositories import goal_repository
from app.services.development import aggregate as development_aggregate
from app.application import observability
from app.services import state_service

logger = logging.getLogger(__name__)

STEP_NAME = "goal_arbitration"

_ARBITRATION_INTERVAL_KEY = "arbitration"
_abandon_last: dict[str, datetime] = {}

_CONFLICT_TENSION_BONUS = 0.5
_CONFLICT_PERIOD_PENALTY = 1.0
_ABANDON_SIGNAL_WEIGHT = 0.25
_ABANDON_PROGRESS_WEIGHT = 0.5
_ABANDON_SINGLE_SIGNAL_CAP = 0.5
_ABANDON_CONFIDENCE_THRESHOLD = 0.6


def compute_priority(goal, overlay, relationship_params: dict, settings) -> float:
    score = float(goal.priority)
    if goal.layer == "long_term":
        score += settings.autonomy_priority_layer_weight_long
    if overlay is not None and overlay.goal_weights:
        score += float(overlay.goal_weights.get(goal.domain) or 0.0)
    tension = float(relationship_params.get("tension") or 0.0)
    if goal.domain == "relationship" and tension > settings.rel_tension_freeze:
        score += _CONFLICT_TENSION_BONUS
    conflict_status = relationship_params.get("conflict_status") or "none"
    if conflict_status in ("conflict", "cold"):
        score -= _CONFLICT_PERIOD_PENALTY
    return score


def _rank(group, overlay, relationship_params, settings):
    def _key(goal):
        score = compute_priority(goal, overlay, relationship_params, settings)
        return (-score, -goal.priority, goal.created_at, goal.id)

    return sorted(group, key=_key)


def record_goal_lifecycle(record, decision: str, reason: str, snapshot: dict) -> None:
    """lifecycle 归因公共入口（goal_observation 终态转换复用）。"""
    _record_lifecycle(record, decision, reason, snapshot)


def _record_lifecycle(record, decision: str, reason: str, snapshot: dict) -> None:
    try:
        observability.on_decision(
            DecisionRecord(
                kind=DecisionKind.GOAL_LIFECYCLE,
                user_id=record.user_id,
                conversation_id=None,
                action_id=None,
                trigger=STEP_NAME,
                input_snapshot=snapshot,
                decision=decision,
                reason=reason[:200],
            )
        )
    except Exception:
        logger.exception("goal lifecycle 决策记录失败，已忽略")


def _suspend_with_trace(goal, keeper_id: str, score: float, now: datetime) -> str:
    arbitration = {
        "conflict_with": keeper_id,
        "score_basis": round(score, 4),
        "decided_at": now.isoformat(),
    }
    record = goal_repository.set_status(goal.id, "suspended", arbitration)
    _record_lifecycle(
        record or goal,
        "suspended",
        f"同域冲突让位于 {keeper_id}",
        {"goal_id": goal.id, "conflict_with": keeper_id, "score": score},
    )
    _cascade_children(goal, "suspended", {"suspended_by_parent": goal.id}, now)
    return goal.id


def _cascade_children(parent, target: str, arbitration: dict, now: datetime) -> list[str]:
    cascaded: list[str] = []
    for child in goal_repository.list_children_by_status(parent.id, ("active",)):
        record = goal_repository.set_status(
            child.id, target, dict(arbitration, cascaded_from=parent.id)
        )
        if record is not None and record.status == target:
            cascaded.append(child.id)
    return cascaded


def _revive(goal, now: datetime) -> str | None:
    record = goal_repository.set_status(
        goal.id,
        "active",
        dict(goal.arbitration_state or {}, revived_at=now.isoformat()),
    )
    if record is None or record.status != "active":
        return None
    _record_lifecycle(
        record,
        "active",
        "冲突对方已终结，挂起目标复活",
        {"goal_id": goal.id, "revived_from_conflict": (goal.arbitration_state or {}).get("conflict_with")},
    )
    for child in goal_repository.list_children_by_status(
        goal.id, ("suspended",)
    ):
        child_state = child.arbitration_state or {}
        if child_state.get("suspended_by_parent") == goal.id:
            goal_repository.set_status(child.id, "active")
    return goal.id


def arbitrate_user(user_id: str, now: datetime) -> dict:
    """复活先行（可能产生多 active）→ 同域互斥收敛（单 active）。"""
    settings = get_settings()
    goals = goal_repository.list_top_level_layered(
        user_id, statuses=("active", "suspended")
    )
    by_id = {goal.id: goal for goal in goals}
    active_ids = {goal.id for goal in goals if goal.status == "active"}
    changes: list[dict] = []

    for goal in goals:
        if goal.status != "suspended":
            continue
        conflict_with = (goal.arbitration_state or {}).get("conflict_with")
        if conflict_with is not None and conflict_with not in active_ids:
            revived = _revive(goal, now)
            if revived is not None:
                active_ids.add(revived)
                changes.append({"goal_id": revived, "decision": "active", "reason": "revived"})

    overlay = development_aggregate.read_overlay(user_id)
    relationship_params = _relationship_params(user_id)
    groups: dict[tuple[str, str], list] = {}
    for goal in goals:
        if goal.status != "active":
            continue
        groups.setdefault((goal.layer, goal.domain), []).append(goal)

    for group in groups.values():
        if len(group) <= 1:
            continue
        ranked = _rank(group, overlay, relationship_params, settings)
        keeper = ranked[0]
        for loser in ranked[1:]:
            score = compute_priority(loser, overlay, relationship_params, settings)
            suspended_id = _suspend_with_trace(loser, keeper.id, score, now)
            changes.append(
                {"goal_id": suspended_id, "decision": "suspended", "reason": "conflict"}
            )
    return {"status": "ok", "changes": changes}


def _relationship_params(user_id: str) -> dict:
    try:
        character, relationship = state_service.load_states(user_id)
        return {
            "tension": relationship.tension,
            "conflict_status": getattr(relationship, "conflict_status", "none") or "none",
        }
    except Exception:
        logger.exception("关系调制参数读取失败，仲裁按零调制进行")
        return {}


def _description_bigrams(description: str) -> set[str]:
    text = "".join(ch for ch in description if not ch.isspace())
    return {text[i : i + 2] for i in range(len(text) - 1)} if len(text) >= 2 else {text}


def _low_relevance_signals(goal, facts: dict, min_days: int) -> tuple[bool, bool]:
    signal_memory = True
    for memory in facts.get("salient_memories", []):
        content = getattr(memory, "content", "") or ""
        if _description_bigrams(goal.description) & _description_bigrams(content):
            signal_memory = False
            break
    window_start = facts.get("now", datetime.now()) - timedelta(days=min_days)
    signal_action = not any(
        record.get("created_at") is not None
        and record.get("created_at") >= window_start
        for record in facts.get("action_history", [])
    )
    return signal_memory, signal_action


def check_abandonment(user_id: str, facts: dict, now: datetime) -> dict:
    """long_term active 顶层 goal 的放弃检查：双信号置信，保守阈值。"""
    settings = get_settings()
    min_days = settings.autonomy_abandon_min_progress_days
    abandoned: list[dict] = []
    for goal in goal_repository.list_top_level_layered(user_id, statuses=("active",)):
        if goal.layer != "long_term":
            continue
        progress_at = _last_progress_at(goal, facts)
        if progress_at is None:
            no_progress_days = (now - goal.created_at).days
        else:
            no_progress_days = (now - progress_at).days
        if no_progress_days < min_days:
            continue
        signal_memory, signal_action = _low_relevance_signals(goal, facts, min_days)
        progress_ratio = min(no_progress_days / (2 * min_days), 1.0)
        confidence = (
            _ABANDON_PROGRESS_WEIGHT * progress_ratio
            + _ABANDON_SIGNAL_WEIGHT * signal_memory
            + _ABANDON_SIGNAL_WEIGHT * signal_action
        )
        if not (signal_memory and signal_action):
            confidence = min(confidence, _ABANDON_SINGLE_SIGNAL_CAP)
        if confidence < _ABANDON_CONFIDENCE_THRESHOLD:
            continue
        arbitration = {
            "confidence": round(confidence, 4),
            "no_progress_days": no_progress_days,
            "low_relevance": {"memory": signal_memory, "action": signal_action},
            "decided_at": now.isoformat(),
        }
        record = goal_repository.set_status(goal.id, "abandoned", arbitration)
        _record_lifecycle(
            record or goal,
            "abandoned",
            "长期无进展且低相关",
            {"goal_id": goal.id, **arbitration},
        )
        try:
            from app.services.world import event_bridge

            event_bridge.register_goal_event(
                goal.user_id, goal.id, goal.description, "abandoned"
            )
        except Exception:
            logger.exception("goal 放弃世界事件登记失败（goal=%s）", goal.id)
        _cascade_children(goal, "abandoned", {"abandoned_by_parent": goal.id}, now)
        abandoned.append({"goal_id": goal.id, "confidence": arbitration["confidence"]})
    return {"status": "ok", "abandoned": abandoned}


def _last_progress_at(goal, facts: dict) -> datetime | None:
    latest = goal_repository.get_latest_plan(goal.id)
    if latest is None:
        return goal.updated_at
    return latest.updated_at


def run_user_arbitration(user_id: str, facts: dict, now: datetime) -> dict:
    """编排入口：复活+冲突仲裁每次；abandonment 按节流窗口执行。"""
    settings = get_settings()
    result = arbitrate_user(user_id, now)
    interval = settings.autonomy_arbitration_interval_minutes
    last = _abandon_last.get(user_id)
    abandonment: dict = {"abandoned": []}
    if last is None or (now - last).total_seconds() >= interval * 60:
        _abandon_last[user_id] = now
        abandonment = check_abandonment(user_id, facts, now)
    return {
        "status": "ok",
        "arbitration_changes": result.get("changes", []),
        "abandoned": abandonment.get("abandoned", []),
    }


def reset_throttle_state() -> None:
    _abandon_last.clear()
