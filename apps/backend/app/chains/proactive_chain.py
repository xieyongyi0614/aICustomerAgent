"""V7 Proactive Chain（V7-005）：goal/intention 驱动的主动文本生成链。

输出纯文本（非结构化）；空文本/残留模板符视同生成失败（failure-handling.md §3）。
"""

import logging
import time
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import get_llm
from app.core.settings import get_settings
from app.models.observability import LLM_CALL_ERROR, LLM_CALL_OK, CallSite
from app.prompts.proactive import build_proactive_messages
from app.services.observability.llm_capture import (
    UsageCallbackHandler,
    build_llm_record,
)

logger = logging.getLogger(__name__)

_TEMPLATE_MARKER = "{"


def _validate_text(text: str) -> str | None:
    stripped = text.strip().strip('"“”')
    if not stripped:
        return None
    if _TEMPLATE_MARKER in stripped:
        return None
    return stripped


def _record_call(trace, model, handler, started, started_at, status, error_kind):
    from app.application import observability

    observability.record_llm_call(
        build_llm_record(
            CallSite.PROACTIVE,
            model,
            handler,
            started,
            started_at,
            status=status,
            error_kind=error_kind,
            request_id=trace.request_id if trace is not None else None,
            turn_id=trace.turn_id if trace is not None else None,
        )
    )


async def generate(
    goal_description: str,
    intention: str,
    recent_context: str = "",
    llm=None,
    trace=None,
) -> str | None:
    started = time.perf_counter()
    started_at = datetime.now()
    try:
        model = llm if llm is not None else get_llm()
        prompt = ChatPromptTemplate.from_messages(
            build_proactive_messages(goal_description, intention, recent_context)
        )
        chain = prompt | model.bind(max_tokens=get_settings().answer_max_tokens)
        capture = get_settings().observability_persist_enabled
        handler = UsageCallbackHandler() if capture else None
        try:
            message = await chain.ainvoke(
                {}, config={"callbacks": [handler]} if capture else None
            )
        except Exception as exc:
            if capture:
                _record_call(
                    trace, model, handler, started, started_at,
                    LLM_CALL_ERROR, exc.__class__.__name__,
                )
            raise
        if capture:
            _record_call(trace, model, handler, started, started_at, LLM_CALL_OK, None)
        text = getattr(message, "content", message)
        validated = _validate_text(str(text))
        if trace is not None:
            trace.record(
                "proactive_generate",
                (time.perf_counter() - started) * 1000,
                "ok" if validated is not None else "error",
                error=None if validated is not None else "empty or template output",
            )
        if validated is None:
            logger.warning("主动消息生成结果无效，视同失败")
        return validated
    except Exception as exc:
        logger.exception("主动消息生成失败")
        if trace is not None:
            trace.record(
                "proactive_generate",
                (time.perf_counter() - started) * 1000,
                "error",
                error=exc.__class__.__name__,
            )
        return None
