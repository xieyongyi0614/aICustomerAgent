"""Goal Stack Evaluator（V2.1.0 AGENT-003）：四层目标栈激活裁决，纯规则 0 LLM。

每 Run 执行：超时退役（L2/L1）→ 按层分组 → 每层主目标选举
（priority > GOAL_TIER > 创建时间）→ 驱动分数产出；抑制原因留痕。
既有 goal_service.select / 状态机 / 仲裁语义零改动（本模块只读 + 退役出口）。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.goal import GOAL_TIER, GoalRecord
from app.repositories import goal_repository
from app.services import state_service

logger = logging.getLogger(__name__)

_LAYER_TIMEOUT_SETTINGS = {
    "medium": "goal_medium_timeout_days",
    "short_term": "goal_short_timeout_hours",
}


@dataclass
class GoalStack:
    """每层至多一个活跃主目标；空层为 None。"""

    long_term: GoalRecord | None = None
    medium: GoalRecord | None = None
    short_term: GoalRecord | None = None
    drives: dict[str, float] = field(default_factory=dict)
    suppressed: dict[str, str] = field(default_factory=dict)

    def as_summary(self) -> dict:
        def _ref(goal: GoalRecord | None) -> dict | None:
            if goal is None:
                return None
            return {
                "id": goal.id,
                "layer": goal.layer,
                "type": goal.type,
                "description": goal.description,
                "origin": goal.origin,
            }

        return {
            "long_term": _ref(self.long_term),
            "medium": _ref(self.medium),
            "short_term": _ref(self.short_term),
            "drives": self.drives,
            "suppressed": self.suppressed,
        }

    def primary(self) -> GoalRecord | None:
        return self.short_term or self.medium or self.long_term


def evaluate_stack(
    user_id: str, now: datetime | None = None, retire_overdue_enabled: bool = True
) -> GoalStack:
    """栈裁决。retire_overdue_enabled=False 为只读模式（前台 Run 用，铁律 4：
    长期化写入只发生在后台）。"""
    settings = get_settings()
    now = now or datetime.now()
    if not settings.goal_stack_enabled:
        return GoalStack()
    if retire_overdue_enabled:
        retire_overdue(user_id, now, settings)
    goals = goal_repository.list_layered_active(user_id)
    character, _relationship = _load_states(user_id)
    low_energy = character.energy < 0.2

    stack = GoalStack()
    by_layer: dict[str, list[GoalRecord]] = {}
    for goal in goals:
        by_layer.setdefault(goal.layer or "", []).append(goal)
    for layer in ("long_term", "medium", "short_term"):
        candidates = by_layer.get(layer) or []
        if not candidates:
            continue
        primary = max(
            candidates,
            key=lambda g: (
                g.priority,
                -GOAL_TIER.get(g.type, 9),
                -(g.created_at.timestamp() if g.created_at else 0),
            ),
        )
        weight = {"long_term": 0.3, "medium": 0.6, "short_term": 1.0}[layer]
        stack.drives[primary.id] = round(weight * (primary.priority / 5.0), 4)
        if layer == "short_term" and low_energy:
            stack.suppressed[primary.id] = "low_energy"
            continue
        setattr(stack, layer, primary)
    return stack


def retire_overdue(user_id: str, now: datetime, settings) -> int:
    """L2/L1 超窗退役：created_at + timeout < now → expired（既有状态机出口）。"""
    retired = 0
    for goal in goal_repository.list_layered_active(user_id):
        timeout_setting = _LAYER_TIMEOUT_SETTINGS.get(goal.layer or "")
        if timeout_setting is None or goal.created_at is None:
            continue
        value = getattr(settings, timeout_setting)
        if goal.layer == "medium":
            deadline = goal.created_at + timedelta(days=max(value, 0))
        else:
            deadline = goal.created_at + timedelta(hours=max(value, 0))
        if now >= deadline:
            record = goal_repository.finish_goal(
                goal.id, "abandoned", failure_reason="timeout"
            )
            if record is not None:
                retired += 1
    return retired


def run_goal_stack_stage(user_id: str, run, now: datetime | None = None) -> dict:
    """autonomous_tick 的 goal_stack 阶段实现：栈裁决 + RunContext 传递。

    Goal Rebalance 建议在此（supply 审核侧，后台唯一写入时机）消费：
    Evolution Engine 只产建议，退役经既有 finish_goal 出口，不新增写路径。
    """
    now = now or datetime.now()
    stack = evaluate_stack(user_id, now)
    run.data["goal_stack"] = stack.as_summary()
    retired = _apply_evolution_rebalance(user_id, now)
    primary = stack.primary()
    return {
        "status": "ok",
        "primary_goal": primary.id if primary is not None else None,
        "suppressed": stack.suppressed,
        "rebalance_retired": retired,
    }


def _apply_evolution_rebalance(user_id: str, now: datetime) -> list[str]:
    settings = get_settings()
    if not settings.personality_evolution_enabled:
        return []
    try:
        from app.services import evolution

        proposals = evolution.propose_rebalance(user_id, now)
        if not proposals:
            return []
        return evolution.apply_rebalance(user_id, proposals, now)
    except Exception:
        logger.exception("goal rebalance 建议消费失败，已忽略")
        return []


def _load_states(user_id: str):
    try:
        return state_service.load_states(user_id)
    except Exception:
        from app.models.character_state import CharacterState
        from app.models.relationship import RelationshipState

        return CharacterState(), RelationshipState()
