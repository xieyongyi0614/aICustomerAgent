from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from app.core.llm_factory import get_llm
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.prompts.snapshots import format_character, format_recent_context
from app.prompts.turn_analysis import turn_analysis_prompt


def build_chain(llm=None) -> Runnable:
    prompt = ChatPromptTemplate.from_messages([("system", turn_analysis_prompt)])
    return prompt | (llm or get_llm()).with_structured_output(TurnAnalysis)


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
