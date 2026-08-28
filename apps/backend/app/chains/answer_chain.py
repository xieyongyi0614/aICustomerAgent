import time
from typing import AsyncIterator

from langchain_core.runnables import Runnable

from app.core.llm_factory import get_llm
from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.prompts.builder import PromptBuilder


def build_chain(
    mode: str,
    state: ConversationState,
    analysis: TurnAnalysis | None = None,
    llm=None,
    scene_ctx=None,
) -> Runnable:
    prompt = PromptBuilder.build(mode, state, analysis, scene_ctx)
    model = llm if llm is not None else get_llm()
    return prompt | model.bind(max_tokens=get_settings().answer_max_tokens)


async def astream(
    mode: str,
    state: ConversationState,
    analysis: TurnAnalysis | None = None,
    llm=None,
    trace=None,
    scene_ctx=None,
) -> AsyncIterator[str]:
    started = time.perf_counter()
    chain = build_chain(mode, state, analysis, llm, scene_ctx)
    if trace is not None:
        trace.record("prompt_builder", (time.perf_counter() - started) * 1000)
    async for chunk in chain.astream({}):
        text = getattr(chunk, "content", chunk)
        if text:
            yield text
