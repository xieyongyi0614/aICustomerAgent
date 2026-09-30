"""turn_meta.memory_refs 装配（API-003）。

无引用时返回 None → 调用方不得写键（禁止空数组）。
label 由 content 截取，上限 12 字 + 省略号，不调 LLM。
"""

from __future__ import annotations

from app.models.memory import UserMemory

MEMORY_REF_LABEL_MAX = 12


def memory_ref_label(content: str, limit: int = MEMORY_REF_LABEL_MAX) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def build_memory_refs(memories: list[UserMemory] | None) -> list[dict] | None:
    if not memories:
        return None
    refs: list[dict] = []
    for memory in memories:
        if memory.status != "active":
            continue
        label = memory_ref_label(memory.content)
        if not label:
            continue
        refs.append(
            {
                "id": memory.id,
                "kind": memory.type,
                "label": label,
            }
        )
    return refs or None
