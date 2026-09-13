"""V2.2.0 CHAR-007：调用方接线的 StyleContext 构造（Flag 灰度 + 失败降级）。

总闸 v22_experience_enabled + 子闸 v22_style_contract_enabled 双开才装配；
子闸分别门控 Addressing / Emotion / Habits 三路投影。任何失败降级为
None，回复链路以「无风格契约」继续（裁决 Q6）。
"""

import logging

from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.style_contract import StyleContract
from app.services.experience.style_assembler import assemble_style_contract

logger = logging.getLogger(__name__)


def build_style_context(
    state: ConversationState,
    analysis: TurnAnalysis | None = None,
    personality_state=None,
) -> StyleContract | None:
    settings = get_settings()
    if not settings.v22_experience_enabled or not settings.v22_style_contract_enabled:
        return None
    try:
        return assemble_style_contract(
            state,
            analysis,
            personality_state,
            include_addressing=settings.v22_relationship_addressing_enabled,
            include_emotion=settings.v22_emotion_transition_enabled,
            include_habits=settings.v22_habit_runtime_enabled,
        )
    except Exception:
        logger.exception("StyleContract 构造失败，降级为无契约回复")
        return None
