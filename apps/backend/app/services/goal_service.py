"""V6 Goal 生命周期策略与每轮目标选择。

Goal 的创建/完成/过期/取消全部由确定性代码裁决（goal-policy.md），
LLM 仅通过 turn_analysis 事件与 executed_intention 提供信号，无处置权。
选择层（goal-selection.md / goal-conflict.md）：tier 排序 + 上下文修正，
永远返回确定性结果。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.character.asuna import PERSISTENT_GOALS
from app.core.settings import get_settings
from app.models.character_state import CharacterState
from app.models.emotion import TurnAnalysis
from app.models.goal import (
    GOAL_DESCRIPTION_MAX_LENGTH,
    GOAL_TIER,
    GoalPlanRecord,
    GoalRecord,
)
from app.models.relationship import RelationshipState
from app.models.scene import SceneState
from app.repositories import goal_repository

logger = logging.getLogger(__name__)

GOAL_DESCRIPTION_REPAIR = "修复与用户的隔阂"
GOAL_DESCRIPTION_REST = "劝用户早点休息"
GOAL_DESCRIPTION_COMPANION = "陪伴用户放松"

TIER_DESCRIPTION_ORDER = (
    GOAL_DESCRIPTION_REST,
    GOAL_DESCRIPTION_COMPANION,
    GOAL_DESCRIPTION_REPAIR,
)

_CONFLICT_EVENT_TYPES = ("conflict", "boundary_violation")
_FATIGUE_EMOTIONS = ("tired", "sad", "anxious")
_NEGATIVE_MOODS = ("worried", "sad", "tired", "angry")
_SCENE_DESCRIPTION_PREFIX = "完成"
_SCENE_ACTION_MAX_CHARS = GOAL_DESCRIPTION_MAX_LENGTH - len(_SCENE_DESCRIPTION_PREFIX)

_TIER_RELATIONSHIP_BOOST = 0.9
_TIER_USER_CARE_EMOTION_BOOST = 0.8
_TIER_USER_CARE_REST_BOOST = 0.85
_TIER_CONVERSATION_SUPPRESS = 3.5


@dataclass
class SelectedGoal:
    goal: GoalRecord | None
    reason: str
    suppressed: list[str] = field(default_factory=list)
    suppressed_description: str | None = None


@dataclass
class GoalChanges:
    created: list[GoalRecord] = field(default_factory=list)
    completed: list[GoalRecord] = field(default_factory=list)
    expired: list[GoalRecord] = field(default_factory=list)
    cancelled: list[GoalRecord] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.created or self.completed or self.expired or self.cancelled
        )


def seed_if_absent(user_id: str, character_id: str = "asuna") -> None:
    try:
        goal_repository.seed_goals(user_id, PERSISTENT_GOALS, character_id)
    except Exception:
        logger.exception("persistent 目标播种失败，本轮以现有目标集运行")


def load_active(user_id: str, character_id: str = "asuna") -> list[GoalRecord]:
    try:
        return goal_repository.list_active(user_id, character_id)
    except Exception:
        logger.exception("active 目标读取失败，降级为空目标集")
        return []


def scene_goal_description(action: str) -> str:
    return f"{_SCENE_DESCRIPTION_PREFIX}{action[:_SCENE_ACTION_MAX_CHARS]}"


def _pending_action(scene: SceneState | None):
    if scene is None or scene.pending_action is None:
        return None
    if scene.pending_action.status == "pending":
        return scene.pending_action
    return None


def _has_active_description(
    goals: list[GoalRecord], goal_type: str, description: str
) -> bool:
    return any(g.type == goal_type and g.description == description for g in goals)


def _create_goal(
    user_id: str,
    goal_type: str,
    description: str,
    current_turn: int,
    source: str,
    priority: int,
) -> GoalRecord:
    now = datetime.now()
    record = GoalRecord(
        user_id=user_id,
        type=goal_type,
        description=description,
        priority=priority,
        horizon="current",
        source=source,
        created_turn=current_turn,
        expires_at_turn=current_turn + get_settings().goal_default_ttl_turns,
        created_at=now,
        updated_at=now,
    )
    return goal_repository.create_goal(record)


def _decide_creation(
    user_id: str,
    goals: list[GoalRecord],
    analysis: TurnAnalysis,
    executed_intention: str | None,
    pending,
    tension: float,
    current_turn: int,
) -> GoalChanges:
    changes = GoalChanges()

    if pending is not None:
        candidate = ("scene", scene_goal_description(pending.action), "scene")
    elif executed_intention == "suggest_rest":
        candidate = ("user_care", GOAL_DESCRIPTION_REST, "policy")
    elif analysis.user_emotion.emotion in _FATIGUE_EMOTIONS:
        candidate = ("user_care", GOAL_DESCRIPTION_COMPANION, "policy")
    elif (
        analysis.relationship_event.type in _CONFLICT_EVENT_TYPES
        and tension >= get_settings().rel_tension_freeze
    ):
        candidate = ("relationship", GOAL_DESCRIPTION_REPAIR, "policy")
    else:
        return changes

    goal_type, description, source = candidate
    if _has_active_description(goals, goal_type, description):
        return changes
    changes.created.append(
        _create_goal(user_id, goal_type, description, current_turn, source, priority=5)
    )
    return changes


def review(
    user_id: str,
    session_id: str,
    analysis: TurnAnalysis,
    executed_intention: str | None,
    current_turn: int,
    character: CharacterState,
    relationship: RelationshipState,
    scene: SceneState | None,
) -> GoalChanges:
    settings = get_settings()
    seed_if_absent(user_id)
    goals = goal_repository.list_active(user_id)
    changes = _decide_creation(
        user_id,
        goals,
        analysis,
        executed_intention,
        _pending_action(scene),
        relationship.tension,
        current_turn,
    )
    pending = _pending_action(scene)
    created_ids = {g.id for g in changes.created}
    for goal in goals:
        if goal.id in created_ids:
            continue
        if goal.horizon != "current":
            continue
        if goal.expires_at_turn is not None and current_turn > goal.expires_at_turn:
            expired = goal_repository.expire_goal(goal.id)
            if expired is not None:
                changes.expired.append(expired)
            continue

        if goal.type == "scene":
            if pending is None:
                completed = goal_repository.complete_goal(goal.id)
                if completed is not None:
                    changes.completed.append(completed)
            elif goal.description != scene_goal_description(pending.action):
                cancelled = goal_repository.cancel_goal(goal.id)
                if cancelled is not None:
                    changes.cancelled.append(cancelled)
        elif goal.description == GOAL_DESCRIPTION_REST:
            if current_turn - goal.created_turn >= settings.goal_rest_complete_turns:
                completed = goal_repository.complete_goal(goal.id)
                if completed is not None:
                    changes.completed.append(completed)
        elif goal.description == GOAL_DESCRIPTION_COMPANION:
            if (
                character.mood == "calm"
                and character.intensity <= settings.goal_companion_complete_intensity
            ):
                completed = goal_repository.complete_goal(goal.id)
                if completed is not None:
                    changes.completed.append(completed)
        elif (
            goal.type == "relationship"
            and goal.description == GOAL_DESCRIPTION_REPAIR
        ):
            if relationship.tension <= settings.goal_repair_complete_tension:
                completed = goal_repository.complete_goal(goal.id)
                if completed is not None:
                    changes.completed.append(completed)
            elif relationship.tension < settings.rel_tension_freeze:
                cancelled = goal_repository.cancel_goal(goal.id)
                if cancelled is not None:
                    changes.cancelled.append(cancelled)

    return changes


def changes_to_trace(changes: GoalChanges) -> dict:
    return {
        "created": [g.id for g in changes.created],
        "completed": [g.id for g in changes.completed],
        "expired": [g.id for g in changes.expired],
        "cancelled": [g.id for g in changes.cancelled],
    }


def list_layered_active(
    user_id: str,
    layer: str | None = None,
    domain: str | None = None,
    character_id: str = "asuna",
) -> list[GoalRecord]:
    try:
        return goal_repository.list_layered_active(
            user_id, layer=layer, domain=domain, character_id=character_id
        )
    except Exception:
        logger.exception("层级 active 目标读取失败，降级为空目标集")
        return []


def list_children(goal_id: str) -> list[GoalRecord]:
    try:
        return goal_repository.list_children(goal_id)
    except Exception:
        logger.exception("层级子目标读取失败，降级为空集")
        return []


def list_tree(user_id: str, root_goal_id: str) -> list[dict]:
    try:
        return goal_repository.list_tree(user_id, root_goal_id)
    except Exception:
        logger.exception("目标树读取失败，降级为空树")
        return []


def list_active_plans(user_id: str) -> list[tuple[GoalRecord, GoalPlanRecord]]:
    try:
        return goal_repository.list_active_plans(user_id)
    except Exception:
        logger.exception("活跃计划联查失败，降级为空集")
        return []


def get_goal(goal_id: str) -> GoalRecord | None:
    """按 id 取目标记录（**只读门面**）：上层不得直读 `goal_repository`（H-3）。"""
    try:
        return goal_repository.get_goal(goal_id)
    except Exception:
        logger.exception("目标记录读取失败，按不可得处理：%s", goal_id)
        return None


def get_plan(plan_id: str) -> GoalPlanRecord | None:
    """按 id 取计划记录（**只读门面**）：上层不得直读 `goal_repository`（H-3）。"""
    try:
        return goal_repository.get_plan(plan_id)
    except Exception:
        logger.exception("计划记录读取失败，按不可得处理：%s", plan_id)
        return None


def _effective_tier(goal: GoalRecord, signals: dict) -> float:
    settings = get_settings()
    tier = float(GOAL_TIER[goal.type])
    if goal.type == "relationship" and signals["tension"] > settings.rel_tension_freeze:
        tier = _TIER_RELATIONSHIP_BOOST
    if goal.type == "user_care":
        if signals["strong_negative"]:
            tier = min(tier, _TIER_USER_CARE_EMOTION_BOOST)
        if (
            goal.description == GOAL_DESCRIPTION_REST
            and signals["late_night"]
            and signals["user_emotion"] == "tired"
        ):
            tier = min(tier, _TIER_USER_CARE_REST_BOOST)
    if goal.type == "conversation" and signals["strong_negative"]:
        tier = _TIER_CONVERSATION_SUPPRESS
    return tier


def _selection_reason(goal: GoalRecord, signals: dict, settings) -> str:
    if goal.type == "scene":
        return "存在未完成场景承诺，scene 目标优先"
    if goal.type == "relationship" and signals["tension"] > settings.rel_tension_freeze:
        return f"紧张度 {signals['tension']:.1f}，修复隔阂目标提升"
    if (
        goal.type == "user_care"
        and goal.description == GOAL_DESCRIPTION_REST
        and signals["late_night"]
        and signals["user_emotion"] == "tired"
    ):
        return "深夜且用户疲惫，劝休目标提升"
    if goal.type == "user_care" and signals["strong_negative"]:
        return "情绪强度高企，user_care 目标提前"
    return "按目标层级 scene > user_care > relationship > conversation 选取"


def select(
    goals: list[GoalRecord],
    *,
    tension: float,
    user_emotion: str,
    character_mood: str,
    character_intensity: float,
    scene_pending: bool,
    late_night: bool,
    development_weights: dict[str, float] | None = None,
) -> SelectedGoal:
    if not goals:
        return SelectedGoal(goal=None, reason="目标集为空，动机层降级", suppressed=[])

    settings = get_settings()
    strong_negative = (
        character_mood in _NEGATIVE_MOODS
        and character_intensity >= settings.emotion_strong_threshold
    )
    signals = {
        "tension": tension,
        "user_emotion": user_emotion,
        "late_night": late_night,
        "strong_negative": strong_negative,
    }

    def sort_key(goal: GoalRecord):
        description_rank = (
            TIER_DESCRIPTION_ORDER.index(goal.description)
            if goal.description in TIER_DESCRIPTION_ORDER
            else len(TIER_DESCRIPTION_ORDER)
        )
        tier = _effective_tier(goal, signals)
        if development_weights:
            delta = float(development_weights.get(goal.type) or 0.0)
            cap = settings.development_pattern_goal_tier_delta_max
            tier -= max(-cap, min(cap, delta))
        return (
            tier,
            -goal.priority,
            -goal.created_at.timestamp(),
            description_rank,
            goal.id,
        )

    ranked = sorted(goals, key=sort_key)
    selected = ranked[0]
    suppressed = [g.id for g in ranked[1:]]
    background = ranked[1].description if len(ranked) > 1 else None

    reason = _selection_reason(selected, signals, settings)
    if development_weights and float(
        development_weights.get(selected.type) or 0.0
    ) != 0.0:
        reason = f"{reason}；development 调制生效"
    if scene_pending and selected.type != "scene":
        reason = f"存在未完成场景承诺；{reason}"
    return SelectedGoal(
        goal=selected,
        reason=reason,
        suppressed=suppressed,
        suppressed_description=background,
    )
