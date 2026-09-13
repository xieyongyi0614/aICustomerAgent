"""V2.2.0 CHAR-006：StyleContract 装配中枢。

把 Emotion / Personality / Relationship / Habit 四路投影按固定优先级
合成一个可解释、可回放的 StyleContract：硬约束（forbidden/principles）
> 情绪 > 关系档位 > 人格调制 > 习惯。全程规则/查表，0 额外 LLM；
任一子组件异常时降级为最小契约（仅硬约束 + 空习惯），不阻塞回复。
"""

import logging

from app.character.asuna.personality_profile import PERSONA_PROFILE
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.style_contract import StyleContract
from app.services.experience.emotion_expression import build_emotion_expression
from app.services.experience.habit_trigger import HabitTriggerContext, trigger_habits
from app.services.experience.personality_modulation import (
    build_personality_modulation,
)
from app.services.experience.relationship_addressing import (
    build_addressing,
    relationship_emotion_boost,
)

logger = logging.getLogger(__name__)

EMOTION_TIER_TO_EXPRESSIVENESS: dict[str, str] = {
    "subtle": "restrained",
    "natural": "natural",
    "rich": "open",
}

PERSONALITY_HABIT_BOUNDARY: dict[str, tuple[str, ...]] = {
    "warmth": ("habit_care_action_first", "habit_comfort_companion_first"),
    "curiosity": ("habit_question_bounded",),
    "patience": ("habit_listen_before_speak",),
}

INHIBITED_AXIS_THRESHOLD = 0.3


def assemble_style_contract(
    state: ConversationState,
    analysis: TurnAnalysis | None = None,
    personality_state=None,
    *,
    include_addressing: bool = True,
    include_emotion: bool = True,
    include_habits: bool = True,
) -> StyleContract:
    contract = _hard_constraints()
    if include_addressing:
        _apply_addressing(contract, state)
    if include_emotion:
        _apply_emotion(contract, state, relationship_modulation=include_addressing)
    _apply_personality(contract, personality_state)
    if include_habits:
        _apply_habits(contract, state, analysis or TurnAnalysis())
    _resolve_conflicts(contract, resolve_expressiveness=include_addressing)
    contract.style_hint = contract.build_style_hint()
    return contract


def _hard_constraints() -> StyleContract:
    try:
        return StyleContract(
            forbidden=list(PERSONA_PROFILE.forbidden_behaviors),
            principles=list(PERSONA_PROFILE.principles),
        )
    except Exception:
        logger.exception("人格硬约束读取失败，降级空契约")
        return StyleContract()


def _apply_addressing(contract: StyleContract, state: ConversationState) -> None:
    try:
        contract.addressing = build_addressing(state.relationship_state)
    except Exception:
        logger.exception("Addressing 投影失败，降级默认档位")


def _apply_emotion(
    contract: StyleContract, state: ConversationState, relationship_modulation: bool = True
) -> None:
    try:
        boost = (
            relationship_emotion_boost(state.relationship_state.stage)
            if relationship_modulation
            else 0.0
        )
        contract.emotion_constraint = build_emotion_expression(
            state.character_state, intensity_boost=boost
        )
    except Exception:
        logger.exception("情绪表达投影失败，降级默认约束")


def _apply_personality(contract: StyleContract, personality_state) -> None:
    try:
        contract.personality_modulation = build_personality_modulation(
            PERSONA_PROFILE, personality_state
        )
    except Exception:
        logger.exception("人格调制投影失败，降级基线")


def _apply_habits(
    contract: StyleContract, state: ConversationState, analysis: TurnAnalysis
) -> None:
    try:
        context = HabitTriggerContext(
            analysis=analysis,
            conflict_status=getattr(
                state.relationship_state, "conflict_status", "none"
            )
            or "none",
            user_message=state.current_input,
            memory_present=bool(state.memories),
        )
        contract.habits = trigger_habits(context)
    except Exception:
        logger.exception("习惯触发失败，降级空习惯")
        contract.habits = []


def _resolve_conflicts(
    contract: StyleContract, resolve_expressiveness: bool = True
) -> None:
    if resolve_expressiveness:
        _resolve_emotion_vs_relationship(contract)
    _apply_personality_habit_boundary(contract)


def _resolve_emotion_vs_relationship(contract: StyleContract) -> None:
    emotion_expressiveness = EMOTION_TIER_TO_EXPRESSIVENESS[
        contract.emotion_constraint.expression_intensity
    ]
    if contract.addressing.emotion_expressiveness != emotion_expressiveness:
        contract.addressing = contract.addressing.model_copy(
            update={"emotion_expressiveness": emotion_expressiveness}
        )


def _apply_personality_habit_boundary(contract: StyleContract) -> None:
    modulation = contract.personality_modulation
    suppressed: set[str] = set()
    for axis, habit_ids in PERSONALITY_HABIT_BOUNDARY.items():
        if modulation.axis_value(axis) <= INHIBITED_AXIS_THRESHOLD:
            suppressed.update(habit_ids)
    if suppressed:
        contract.habits = [
            habit for habit in contract.habits if habit.rule_id not in suppressed
        ]
