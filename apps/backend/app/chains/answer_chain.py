import time
from datetime import datetime
from typing import AsyncIterator

from langchain_core.runnables import Runnable

from app.core.llm_factory import get_llm
from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.observability import LLM_CALL_ERROR, LLM_CALL_OK, CallSite
from app.prompts.builder import PromptBuilder
from app.services.observability.llm_capture import UsageCallbackHandler, build_llm_record


def build_chain(
    mode: str,
    state: ConversationState,
    analysis: TurnAnalysis | None = None,
    llm=None,
    scene_ctx=None,
    goal_ctx=None,
    behavior_ctx=None,
    prompt=None,
    world_ctx=None,
    action_ctx=None,
) -> Runnable:
    if prompt is None:
        prompt = PromptBuilder.build(
            mode, state, analysis, scene_ctx, goal_ctx, behavior_ctx, world_ctx, action_ctx
        )
    model = llm if llm is not None else get_llm()
    return prompt | model.bind(max_tokens=get_settings().answer_max_tokens)


def _record_answer_call(llm, trace, handler, started, started_at, first_token_ms, status, error_kind):
    from app.application import observability

    observability.record_llm_call(
        build_llm_record(
            CallSite.ANSWER,
            llm,
            handler,
            started,
            started_at,
            status=status,
            error_kind=error_kind,
            ttft_ms=first_token_ms,
            request_id=trace.request_id if trace is not None else None,
            turn_id=trace.turn_id if trace is not None else None,
        )
    )


async def astream(
    mode: str,
    state: ConversationState,
    analysis: TurnAnalysis | None = None,
    llm=None,
    trace=None,
    scene_ctx=None,
    goal_ctx=None,
    behavior_ctx=None,
    world_ctx=None,
    action_ctx=None,
) -> AsyncIterator[str]:
    from app.services.observability import prompt_capture

    started = time.perf_counter()
    started_at = datetime.now()
    prompt = PromptBuilder.build(
        mode, state, analysis, scene_ctx, goal_ctx, behavior_ctx, world_ctx, action_ctx
    )
    chain = build_chain(
        mode, state, analysis, llm, scene_ctx, goal_ctx, behavior_ctx, prompt=prompt, action_ctx=action_ctx
    )
    if trace is not None:
        trace.record("prompt_builder", (time.perf_counter() - started) * 1000)
        trace.model_name = getattr(llm, "model_name", None) or "default"

    if prompt_capture.enabled():
        formatted = prompt.format_messages()
        prompt_capture.capture_prompt_snapshot(
            CallSite.ANSWER,
            formatted,
            llm,
            section_budget=prompt_capture.section_budget_from_messages(formatted),
        )

    capture = get_settings().observability_persist_enabled
    handler = UsageCallbackHandler() if capture else None
    first_token_ms = None
    try:
        async for chunk in chain.astream(
            {}, config={"callbacks": [handler]} if capture else None
        ):
            usage = getattr(chunk, "usage_metadata", None)
            if usage and trace is not None:
                trace.add_token_usage(
                    {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                    }
                )
            text = getattr(chunk, "content", chunk)
            if text:
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - started) * 1000
                yield text
    except Exception as exc:
        if capture:
            _record_answer_call(
                llm, trace, handler, started, started_at, first_token_ms,
                LLM_CALL_ERROR, exc.__class__.__name__,
            )
        raise
    if capture:
        _record_answer_call(
            llm, trace, handler, started, started_at, first_token_ms, LLM_CALL_OK, None
        )
