"""V2.2.0 CHAR-007：调用方接线的 StyleContext 构造（失败降级）。

Addressing / Emotion / Habits 三路投影无条件装配；任何失败降级为 None，
回复链路以「无风格契约」继续（裁决 Q6）。
"""

import logging

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
    try:
        return assemble_style_contract(state, analysis, personality_state)
    except Exception:
        logger.exception("StyleContract 构造失败，降级为无契约回复")
        return None
