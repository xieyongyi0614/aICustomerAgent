import time
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import get_llm
from app.core.settings import get_settings
from app.models.observability import LLM_CALL_ERROR, LLM_CALL_OK, CallSite
from app.prompts.summary import summary_prompt
from app.services.observability.llm_capture import (
    UsageCallbackHandler,
    build_llm_record,
)


_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", summary_prompt),
        ("user", "待摘要的新消息：\n{new_messages}"),
    ]
)


def build_chain(llm=None):
    return _SUMMARY_PROMPT | (llm or get_llm())


def _submit_record(llm, handler, started, started_at, status, error_kind):
    from app.application import observability

    observability.submit_llm_call(
        build_llm_record(
            CallSite.SUMMARY,
            llm,
            handler,
            started,
            started_at,
            status=status,
            error_kind=error_kind,
        )
    )


async def summarize(old_summary: str, new_messages: str, llm=None) -> str:
    chain = build_chain(llm)
    capture = get_settings().observability_persist_enabled
    handler = UsageCallbackHandler() if capture else None
    started = time.perf_counter()
    started_at = datetime.now()
    from app.services.observability import prompt_capture

    if prompt_capture.enabled():
        prompt_capture.capture_prompt_snapshot(
            CallSite.SUMMARY,
            _SUMMARY_PROMPT.format_messages(old_summary=old_summary, new_messages=new_messages),
            llm,
        )
    try:
        result = await chain.ainvoke(
            {"old_summary": old_summary, "new_messages": new_messages},
            config={"callbacks": [handler]} if capture else None,
        )
    except Exception as exc:
        if capture:
            _submit_record(llm, handler, started, started_at, LLM_CALL_ERROR, exc.__class__.__name__)
        raise
    if capture:
        _submit_record(llm, handler, started, started_at, LLM_CALL_OK, None)
    return getattr(result, "content", str(result)).strip()
