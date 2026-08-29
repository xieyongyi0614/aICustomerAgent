"""V6 IntentionPolicy：LLM 候选意图的纯代码校验/降级。

规则表驱动（intention-model.md §4 / intention-selection.md §4），
Policy 永远输出一个合法 Intention，链失败或候选非法时回退 continue_topic。
"""

import logging
from datetime import datetime

from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.intention import (
    EXPRESSION_INTENTIONS,
    INTENTION_GOAL_DEFAULTS,
    INTENTION_GOAL_FIT,
    INTENTION_REASON_MAX_LENGTH,
    IntentionDecision,
    IntentionType,
    ValidatedIntention,
)
from app.services.goal_service import GOAL_DESCRIPTION_REPAIR, SelectedGoal

logger = logging.getLogger(__name__)

_DEGRADED_REASON = "策略降级"
_INVALID_REASON = "意图在当前状态下不合法，降级"
_GOAL_MISMATCH_REASON = "与当前目标不一致，按目标类型降级"
_SCENE_PRIORITY_REASON = "存在未完成场景承诺，表达类意图让位"

_COMFORT_USER_EMOTIONS = ("sad", "anxious", "tired")
_COMFORT_EVENT_TYPES = ("criticized", "worrying_news")


def _is_late_night(now: datetime) -> bool:
    settings = get_settings()
    return now.hour >= settings.goal_late_night_start or now.hour < settings.goal_late_night_end


def _express_affection_valid(state: ConversationState, analysis, now: datetime) -> bool:
    return state.relationship_state.intimacy >= get_settings().stage_close_intimacy


def _tease_user_valid(state: ConversationState, analysis, now: datetime) -> bool:
    settings = get_settings()
    relationship = state.relationship_state
    return (
        relationship.familiarity >= settings.goal_tease_familiarity
        and relationship.tension <= settings.goal_tease_max_tension
    )


def _maintain_distance_valid(state: ConversationState, analysis, now: datetime) -> bool:
    return state.relationship_state.tension > get_settings().rel_tension_freeze


def _repair_rapport_valid(state: ConversationState, analysis, now: datetime) -> bool:
    return state.relationship_state.tension >= get_settings().goal_repair_min_tension


def _celebrate_valid(state: ConversationState, analysis, now: datetime) -> bool:
    if analysis is None:
        return False
    return (
        analysis.user_emotion.event == "achievement"
        or analysis.user_emotion.emotion == "happy"
    )


def _suggest_rest_valid(state: ConversationState, analysis, now: datetime) -> bool:
    user_tired = analysis is not None and analysis.user_emotion.emotion == "tired"
    return user_tired or _is_late_night(now)


def _comfort_user_valid(state: ConversationState, analysis, now: datetime) -> bool:
    if analysis is None:
        return False
    return analysis.user_emotion.emotion in _COMFORT_USER_EMOTIONS or (
        analysis.emotion_event.type in _COMFORT_EVENT_TYPES
    )


VALIDITY_RULES = {
    "express_affection": _express_affection_valid,
    "tease_user": _tease_user_valid,
    "maintain_distance": _maintain_distance_valid,
    "repair_rapport": _repair_rapport_valid,
    "celebrate_with_user": _celebrate_valid,
    "suggest_rest": _suggest_rest_valid,
    "comfort_user": _comfort_user_valid,
}

_ALWAYS_VALID = (
    "encourage_user",
    "continue_topic",
    "ask_followup",
    "share_own_feeling",
    "lighten_mood",
)


def _is_valid(intention: str, state: ConversationState, analysis, now: datetime) -> bool:
    rule = VALIDITY_RULES.get(intention)
    if rule is None:
        return intention in _ALWAYS_VALID
    return rule(state, analysis, now)


def _truncate_reason(reason: str) -> str:
    return reason[:INTENTION_REASON_MAX_LENGTH]


def _fallback(
    goal_id: str | None, reason: str, intention: IntentionType = "continue_topic"
) -> ValidatedIntention:
    return ValidatedIntention(
        intention=intention, reason=_truncate_reason(reason), goal_id=goal_id, degraded=True
    )


def enforce(
    decision: object,
    selected_goal: SelectedGoal | None,
    state: ConversationState,
    analysis: TurnAnalysis | None,
    now: datetime,
    scene_pending: bool = False,
) -> ValidatedIntention:
    goal_id = (
        selected_goal.goal.id
        if selected_goal is not None and selected_goal.goal is not None
        else None
    )
    if not isinstance(decision, IntentionDecision):
        return _fallback(goal_id, _DEGRADED_REASON)

    candidate: IntentionType = decision.intention
    if not _is_valid(candidate, state, analysis, now):
        return _fallback(goal_id, _INVALID_REASON)

    degraded = False
    reason = decision.reason
    if selected_goal is not None and selected_goal.goal is not None:
        goal_type = selected_goal.goal.type
        if goal_type not in INTENTION_GOAL_FIT[candidate]:
            candidate = INTENTION_GOAL_DEFAULTS[goal_type]
            degraded = True
            reason = _GOAL_MISMATCH_REASON
            if not _is_valid(candidate, state, analysis, now):
                return _fallback(goal_id, _INVALID_REASON)

    if candidate in EXPRESSION_INTENTIONS and scene_pending:
        return _fallback(goal_id, _SCENE_PRIORITY_REASON)

    return ValidatedIntention(
        intention=candidate,
        reason=_truncate_reason(reason),
        goal_id=goal_id,
        degraded=degraded,
    )
