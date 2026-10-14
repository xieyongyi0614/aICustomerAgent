"""记忆检索重排链（MEV-001）：对 top-N 候选按查询相关性重打分。

lite profile 一次性结构化输出；未知 id 丢弃、缺失候选不补齐、链内不吞异常——
降级判定集中在调用方（retriever）。
"""

from pydantic import BaseModel, Field

from app.chains.structured import build_structured_chain
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError
from app.prompts.memory_rerank import (
    build_memory_rerank_messages,
    format_rerank_candidates,
)

RERANK_CONTENT_MAX_CHARS = 200

_LLM_LITE_PROFILE_ID = "lite"


class MemoryRerankItem(BaseModel):
    id: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class MemoryRerankResult(BaseModel):
    items: list[MemoryRerankItem] = Field(default_factory=list)


def _resolve_llm():
    try:
        return get_llm(_LLM_LITE_PROFILE_ID)
    except SettingsError:
        return get_llm(None)


def build_memory_rerank_chain(llm=None):
    model = llm if llm is not None else _resolve_llm()
    return build_structured_chain(
        build_memory_rerank_messages(), MemoryRerankResult, model
    )


def _truncate_content(content: str) -> str:
    return " ".join((content or "").split())[:RERANK_CONTENT_MAX_CHARS]


def _normalize(
    result, allowed_ids: set[str]
) -> list[MemoryRerankItem]:
    items = getattr(result, "items", None) or []
    return [item for item in items if item.id in allowed_ids]


def _rerank_input(query: str, candidates: list[tuple[str, str]]) -> dict:
    truncated = [
        (memory_id, _truncate_content(content)) for memory_id, content in candidates
    ]
    return {"query": query or "", "candidates": format_rerank_candidates(truncated)}


async def rerank_memories(
    query: str,
    candidates: list[tuple[str, str]],
    llm=None,
) -> list[MemoryRerankItem]:
    allowed_ids = {memory_id for memory_id, _ in candidates}
    if not allowed_ids:
        return []
    chain = build_memory_rerank_chain(llm)
    result = await chain.ainvoke(_rerank_input(query, candidates))
    return _normalize(result, allowed_ids)


def rerank_memories_sync(
    query: str,
    candidates: list[tuple[str, str]],
    llm=None,
) -> list[MemoryRerankItem]:
    allowed_ids = {memory_id for memory_id, _ in candidates}
    if not allowed_ids:
        return []
    chain = build_memory_rerank_chain(llm)
    result = chain.invoke(_rerank_input(query, candidates))
    return _normalize(result, allowed_ids)
