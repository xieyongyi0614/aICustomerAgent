"""记忆检索查询改写链（MEV-002）：把用户当轮输入改写为 1~2 条更利于召回的 query。

lite profile 一次性结构化输出；清洗（去空 / 剔同原文 / 超长丢弃 / 去重 / 截断上限）
在链内完成，异常一律返回空列表——降级判定集中在调用方（retriever），链内不向上抛。
"""

import logging

from pydantic import BaseModel, Field

from app.chains.structured import build_structured_chain
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError, get_settings
from app.prompts.memory_query_rewrite import build_memory_query_rewrite_messages

logger = logging.getLogger(__name__)

QUERY_MAX_CHARS = 120

_LLM_LITE_PROFILE_ID = "lite"


class QueryRewriteResult(BaseModel):
    queries: list[str] = Field(default_factory=list)


def _resolve_llm():
    try:
        return get_llm(_LLM_LITE_PROFILE_ID)
    except SettingsError:
        return get_llm(None)


def build_query_rewrite_chain(llm=None):
    model = llm if llm is not None else _resolve_llm()
    return build_structured_chain(
        build_memory_query_rewrite_messages(), QueryRewriteResult, model
    )


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _clean_queries(raw_queries, user_input: str, max_queries: int) -> list[str]:
    """清洗改写结果：去空、剔同原文、超长丢弃、归一化去重（保留首次出现序）、截断上限。"""
    seen = {_normalize(user_input)}
    cleaned: list[str] = []
    for raw in raw_queries or []:
        text = (raw or "").strip()
        if not text:
            continue
        if len(text) > QUERY_MAX_CHARS:
            logger.warning("记忆查询改写条目超长（%d 字）已丢弃", len(text))
            continue
        key = _normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= max_queries:
            break
    return cleaned


def _rewrite_input(user_input: str, max_queries: int) -> dict:
    return {"user_input": user_input or "", "max_queries": max_queries}


def _max_queries() -> int:
    return get_settings().memory_query_rewrite_max_queries


async def rewrite_queries(user_input: str, llm=None) -> list[str]:
    text = (user_input or "").strip()
    if not text:
        return []
    try:
        max_queries = _max_queries()
        chain = build_query_rewrite_chain(llm)
        result = await chain.ainvoke(_rewrite_input(text, max_queries))
        return _clean_queries(getattr(result, "queries", None), text, max_queries)
    except Exception as exc:
        logger.warning("记忆查询改写失败，回落单 query：%s", exc.__class__.__name__)
        return []


def rewrite_queries_sync(user_input: str, llm=None) -> list[str]:
    text = (user_input or "").strip()
    if not text:
        return []
    try:
        max_queries = _max_queries()
        chain = build_query_rewrite_chain(llm)
        result = chain.invoke(_rewrite_input(text, max_queries))
        return _clean_queries(getattr(result, "queries", None), text, max_queries)
    except Exception as exc:
        logger.warning("记忆查询改写失败，回落单 query：%s", exc.__class__.__name__)
        return []
