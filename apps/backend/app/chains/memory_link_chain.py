"""MEV-010 记忆关系抽取链：anchor + 候选 → 三义关系（lite profile 结构化输出）。

契约（`docs/version/v6.0.0/tasks/MEV-010.md` §4.1.1）：

- 白名单 `caused_by` / `before` / `related`，白名单外一律丢弃；
- 模型返回既有三义（`supersedes` / `merges` / `contradicts`）→ 丢弃并计数，绝不写入；
- `related_memory_id` 必须在候选集合内，候选外 id 一律丢弃（fail-closed，防幻觉）；
- 空结果 = 判定「无关」，合法返回，不补全、不猜测。
"""

from pydantic import BaseModel, Field

from app.chains.structured import build_structured_chain
from app.core.constants import MEMORY_LINK_EXTRACTABLE_RELATIONS
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError
from app.prompts.memory_link import (
    build_memory_link_messages,
    format_candidates,
)

__all__ = [
    "LINK_EXTRACTABLE_RELATIONS",
    "MemoryLinkItem",
    "MemoryLinkResult",
    "build_memory_link_chain",
    "extract_links",
    "extract_links_with_stats",
]

LINK_EXTRACTABLE_RELATIONS: tuple[str, ...] = MEMORY_LINK_EXTRACTABLE_RELATIONS

_LLM_LITE_PROFILE_ID = "lite"


class MemoryLinkItem(BaseModel):
    related_memory_id: str
    relation: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class MemoryLinkResult(BaseModel):
    links: list[MemoryLinkItem] = Field(default_factory=list)


def _resolve_llm():
    try:
        return get_llm(_LLM_LITE_PROFILE_ID)
    except SettingsError:
        return get_llm(None)


def build_memory_link_chain(llm=None):
    model = llm if llm is not None else _resolve_llm()
    return build_structured_chain(
        build_memory_link_messages(), MemoryLinkResult, model
    )


def _empty_stats() -> dict:
    return {"ignored_existing_relations": 0, "unknown_ids": 0}


async def extract_links_with_stats(
    anchor_content: str,
    candidates: list[tuple[str, str]],
    llm=None,
) -> tuple[list[MemoryLinkItem], dict]:
    """返回 `(kept_links, stats)`；白名单外与候选外条目只计数、不返回。"""
    stats = _empty_stats()
    if not (anchor_content or "").strip() or not candidates:
        return [], stats

    chain = build_memory_link_chain(llm)
    result = await chain.ainvoke(
        {
            "anchor": anchor_content,
            "candidates": format_candidates(candidates),
        }
    )
    items = getattr(result, "links", None) or []
    candidate_ids = {memory_id for memory_id, _ in candidates}
    kept: list[MemoryLinkItem] = []
    for item in items:
        if item.related_memory_id not in candidate_ids:
            stats["unknown_ids"] += 1
            continue
        if item.relation not in LINK_EXTRACTABLE_RELATIONS:
            stats["ignored_existing_relations"] += 1
            continue
        kept.append(item)
    return kept, stats


async def extract_links(
    anchor_content: str,
    candidates: list[tuple[str, str]],
    llm=None,
) -> list[MemoryLinkItem]:
    items, _ = await extract_links_with_stats(anchor_content, candidates, llm)
    return items
