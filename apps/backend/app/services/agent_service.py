"""兼容壳：编排逻辑已迁至 app/application/chat_pipeline。

对外仅保留 stream_chat 与 EmptyLLMResponseError 符号（api 与测试依赖）。
"""

from typing import AsyncIterator

from app.application.chat_pipeline import (
    EmptyLLMResponseError,
    background_tasks,
    run_chat_pipeline,
)
from app.application import observability
from app.services import trace_collector

__all__ = ["stream_chat", "EmptyLLMResponseError", "background_tasks"]

_background_tasks = background_tasks


async def stream_chat(
    session_id: str, user_id: str, content: str, llm=None
) -> AsyncIterator[dict]:
    trace = trace_collector.get_trace_collector().begin_trace()
    observability_token = observability.current_trace.set(trace)
    try:
        async for event in run_chat_pipeline(session_id, user_id, content, llm, trace):
            yield event
    except BaseException as exc:
        trace.record(
            "llm",
            0.0,
            "error",
            error=exc.__class__.__name__,
        )
        observability.on_turn_error(trace, user_id=user_id, session_id=session_id)
        raise
    finally:
        observability.current_trace.reset(observability_token)
