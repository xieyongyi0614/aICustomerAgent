from langchain_core.runnables import Runnable

from app.chains.structured import build_structured_chain
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.prompts.snapshots import format_character, format_recent_context
from app.prompts.turn_analysis import turn_analysis_prompt


def build_chain(llm=None) -> Runnable:
    return build_structured_chain(
        [
            ("system", turn_analysis_prompt),
            ("user", "{user_message}"),
        ],
        TurnAnalysis,
        llm,
    )


async def analyze(content: str, state: ConversationState, llm=None) -> TurnAnalysis:
    chain = build_chain(llm)
    return await chain.ainvoke(
        {
            "user_message": content,
            "recent_context": format_recent_context(state.messages),
            "character_snapshot": format_character(state.character_state),
            "relationship_snapshot": state.relationship_state.stage,
        }
    )
