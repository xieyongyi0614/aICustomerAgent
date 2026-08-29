"""V7 Proactive Chain（V7-005）：goal/intention 驱动的主动文本生成链。

输出纯文本（非结构化）；空文本/残留模板符视同生成失败（failure-handling.md §3）。
"""

import logging
import time

from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import get_llm
from app.core.settings import get_settings
from app.prompts.proactive import build_proactive_messages

logger = logging.getLogger(__name__)

_TEMPLATE_MARKER = "{"


def _validate_text(text: str) -> str | None:
    stripped = text.strip().strip('"“”')
    if not stripped:
        return None
    if _TEMPLATE_MARKER in stripped:
        return None
    return stripped


async def generate(
    goal_description: str,
    intention: str,
    recent_context: str = "",
    llm=None,
    trace=None,
) -> str | None:
    started = time.perf_counter()
    try:
        model = llm if llm is not None else get_llm()
        prompt = ChatPromptTemplate.from_messages(
            build_proactive_messages(goal_description, intention, recent_context)
        )
        chain = prompt | model.bind(max_tokens=get_settings().answer_max_tokens)
        message = await chain.ainvoke({})
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
