from typing import AsyncIterator

from langchain_core.runnables import Runnable

from app.core.llm_factory import get_llm
from app.models.conversation import ConversationState
from app.prompts.builder import PromptBuilder


def build_chain(mode: str, state: ConversationState) -> Runnable:
    prompt = PromptBuilder.build(mode, state)
    return prompt | get_llm()


async def astream(mode: str, state: ConversationState) -> AsyncIterator[str]:
    chain = build_chain(mode, state)
    async for chunk in chain.astream({}):
        text = getattr(chunk, "content", chunk)
        if text:
            yield text
