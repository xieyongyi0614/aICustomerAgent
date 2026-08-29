from langchain_core.runnables import Runnable

from app.chains.structured import build_structured_chain
from app.models.conversation import ConversationState
from app.models.intention import IntentionDecision
from app.prompts.intention import intention_prompt
from app.prompts.snapshots import (
    format_character,
    format_memory_snapshot,
    format_recent_context,
    format_relationship,
    format_scene_summary,
)


def build_chain(llm=None) -> Runnable:
    return build_structured_chain(
        [("system", intention_prompt)],
        IntentionDecision,
        llm,
    )


async def decide(
    content: str,
    state: ConversationState,
    selected_goal,
    scene_state=None,
    llm=None,
) -> IntentionDecision | None:
    chain = build_chain(llm)
    goal = selected_goal.goal if selected_goal is not None else None
    goal_lines = (
        f"{goal.description}\n选择理由：{selected_goal.reason}"
        if goal is not None
        else "暂无明确目标"
    )
    return await chain.ainvoke(
        {
            "selected_goal": goal_lines,
            "character_snapshot": format_character(state.character_state),
            "relationship_snapshot": format_relationship(state.relationship_state),
            "scene_snapshot": format_scene_summary(scene_state),
            "memory_snapshot": format_memory_snapshot(state.memories),
            "recent_context": format_recent_context(state.messages),
            "user_message": content,
        }
    )
