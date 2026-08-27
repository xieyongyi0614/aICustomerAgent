import logging

from langchain_core.runnables import Runnable

from app.chains.structured import build_structured_chain
from app.models.character_state import StateUpdateDecision
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.prompts.snapshots import format_character
from app.prompts.state_update import state_update_prompt

logger = logging.getLogger(__name__)


def build_chain(llm=None) -> Runnable:
    return build_structured_chain(
        [
            ("system", state_update_prompt),
            ("user", "用户输入：{user_input}\n助手回复：{ai_reply}"),
        ],
        StateUpdateDecision,
        llm,
    )


async def update(
    state: ConversationState,
    analysis: TurnAnalysis,
    user_input: str,
    ai_reply: str,
    llm=None,
) -> StateUpdateDecision | None:
    try:
        chain = build_chain(llm)
        return await chain.ainvoke(
            {
                "character_snapshot": format_character(state.character_state),
                "relationship_snapshot": state.relationship_state.stage,
                "user_emotion": analysis.user_emotion.emotion,
                "event": analysis.user_emotion.event,
                "behavior": analysis.behavior.behavior,
                "user_input": user_input,
                "ai_reply": ai_reply,
            }
        )
    except Exception:
        logger.exception("状态更新链失败，降级为纯代码规则")
        return None
