from langchain_core.runnables import Runnable

from app.chains.structured import build_structured_chain
from app.models.conversation import ConversationState
from app.models.emotion import EventCategory, TurnAnalysis
from app.prompts.snapshots import format_character, format_recent_context
from app.prompts.turn_analysis import turn_analysis_prompt

V2_EVENT_TO_V5_RELATIONSHIP_MAP: dict[str, str] = {
    "achievement": "praise",
    "complaint": "criticized",
    "conflict": "conflict",
    "share_goal": "user_help",
    "seek_help": "user_help",
    "help_given": "user_care",
    "setback": "none",
    "daily": "none",
    "farewell": "none",
}


def map_v2_event_to_relationship(event: EventCategory) -> str:
    return V2_EVENT_TO_V5_RELATIONSHIP_MAP.get(event, "none")


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
