"""V9 Action Planner：六闸门 + 计划装配（planner.md §2~§3）。

全部输入为已读快照，闸门内零 IO；能力映射唯一来源 ACTION_CAPABILITY_MAP。
Planner 只裁决与装配，不执行行动。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.character.asuna.action import ACTION_CAPABILITY_MAP
from app.models.action import (
    ActionIntent,
    ActionPlan,
    ActionStep,
    GateReason,
    TERMINAL_STATUSES,
)

logger = logging.getLogger(__name__)

WORLD_DEPENDENT_ACTIONS = (
    "create_reminder",
    "cancel_reminder",
    "create_object",
    "move_object",
    "use_object",
    "query_environment",
)


@dataclass
class GateSnapshot:
    """六闸门快照输入（调用方预读，闸门内零 IO）。"""

    settings: Any
    registry: Any
    records: list[dict] = field(default_factory=list)
    active_count: int = 0
    world_available: bool = False
    active_object_names: list[str] = field(default_factory=list)
    active_reminder_titles: list[str] = field(default_factory=list)
    now: datetime = field(default_factory=datetime.now)


@dataclass
class GateDecision:
    allowed: bool
    reason: GateReason | None = None


def _check_g3(intent: ActionIntent, snapshot: GateSnapshot) -> GateDecision:
    capability_name, action = ACTION_CAPABILITY_MAP[intent.action_type]
    registry = snapshot.registry
    if registry is None or not registry.has(capability_name, action):
        return GateDecision(False, "capability_unavailable")
    if intent.action_type in WORLD_DEPENDENT_ACTIONS and not snapshot.world_available:
        return GateDecision(False, "capability_unavailable")
    return GateDecision(True)


def _check_g4(intent: ActionIntent, snapshot: GateSnapshot) -> GateDecision:
    window_start = snapshot.now - timedelta(hours=snapshot.settings.action_dedupe_window_hours)
    for record in snapshot.records:
        if record.get("dedupe_key") != intent.dedupe_key:
            continue
        created = record.get("created_at")
        if created is not None and created < window_start:
            continue
        if record.get("status") == "succeeded" or record.get("status") not in TERMINAL_STATUSES:
            return GateDecision(False, "duplicate")
    return GateDecision(True)


def _check_g6(intent: ActionIntent, snapshot: GateSnapshot) -> GateDecision:
    if intent.action_type == "create_object":
        name = str(intent.params.get("object", "")).strip()
        if name and any(name in existing or existing in name for existing in snapshot.active_object_names):
            return GateDecision(False, "effect_already_satisfied")
    if intent.action_type == "cancel_reminder":
        target = str(intent.params.get("target", "")).strip()
        matched = bool(target) and any(
            target in title or title in target for title in snapshot.active_reminder_titles
        )
        if not matched:
            return GateDecision(False, "target_not_found")
    return GateDecision(True)


def evaluate_gates(intent: ActionIntent, snapshot: GateSnapshot) -> GateDecision:
    """六闸门按序短路（V7 八步裁决同构）。"""
    if not snapshot.settings.action_enabled:
        return GateDecision(False, "disabled")
    if intent.confidence != "confident":
        return GateDecision(False, "ambiguous_params")
    decision = _check_g3(intent, snapshot)
    if not decision.allowed:
        return decision
    decision = _check_g4(intent, snapshot)
    if not decision.allowed:
        return decision
    if snapshot.active_count >= snapshot.settings.action_max_active_per_user:
        return GateDecision(False, "quota_exceeded")
    return _check_g6(intent, snapshot)


def assemble_plan(
    intent: ActionIntent,
    snapshot: GateSnapshot,
    now: datetime,
    goal_id: str | None = None,
) -> ActionPlan | None:
    """能力映射 + 参数校验 + 计划装配；装配失败返回 None（理论不可达，防御兜底）。"""
    capability_name, action = ACTION_CAPABILITY_MAP[intent.action_type]
    capability = snapshot.registry.get(capability_name) if snapshot.registry is not None else None
    if capability is None:
        return None
    schema = capability.actions.get(action)
    if schema is None:
        return None
    errors = schema.validate(intent.params)
    if errors:
        logger.warning("计划装配参数校验失败（G2/G6 应已拦截）: %s", errors)
        return None
    step = ActionStep(index=0, capability=capability_name, action=action, params=dict(intent.params))
    return ActionPlan(
        intent=intent,
        goal_id=goal_id,
        steps=[step],
        expires_at=now + timedelta(minutes=snapshot.settings.action_plan_expires_minutes),
    )
