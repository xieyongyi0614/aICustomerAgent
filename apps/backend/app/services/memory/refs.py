"""turn_meta.memory_refs 装配（API-003；名次观测量为 MEV-004 扩展）。

无引用时返回 None → 调用方不得写键（禁止空数组）。
label 由 content 截取，上限 12 字 + 省略号，不调 LLM。

**名次观测量（MEV-004）**：传入检索结果（`RankedMemories`）或其快照时，每条引用额外带
`score`（4 位小数）/ `rank`（最终名次，1-based）/ `rank_pre`（重排前名次）/ `reranked`
四个**确定性派生**字段；不传时输出与基线逐字节一致（只有 `id` / `kind` / `label`）。

落库链路：`services/conversation/context.py` 在检索处取快照（`rank_snapshot`）挂到
`ConversationState.memory_rank` → `application/chat_pipeline.py` 装配 turn_meta 时回传本模块。
"""

from __future__ import annotations

from app.models.memory import UserMemory

MEMORY_REF_LABEL_MAX = 12

RANK_PRECISION = 4
"""`score` 落库精度：`turn_meta` 是逐轮 JSON，4 位足够区分名次且控制体积。"""


def memory_ref_label(content: str, limit: int = MEMORY_REF_LABEL_MAX) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def rank_snapshot(ranked) -> list[dict]:
    """检索结果 → 按 id 索引的名次快照（`[{id, score, rank, rank_pre, reranked}]`）。

    - `rank`：`ranked.items` 中的最终名次（1-based）；
    - `rank_pre`：重排前名次，按 `score` 降序 + `memory.id` 升序**确定性重算**；
      `rerank_mode == "off"` 时硬约束为恒等（`rank_pre == rank`）；
    - `score` 四舍五入到 `RANK_PRECISION` 位；`reranked` = 该条是否实际获得重排分。
    """
    items = list(getattr(ranked, "items", []) or [])
    if not items:
        return []
    rerank_mode = getattr(ranked, "rerank_mode", "off")
    pre_order = sorted(
        range(len(items)),
        key=lambda index: (-items[index].score, items[index].memory.id),
    )
    pre_rank = {items[index].memory.id: position + 1 for position, index in enumerate(pre_order)}
    snapshot: list[dict] = []
    for position, item in enumerate(items):
        rank = position + 1
        snapshot.append(
            {
                "id": item.memory.id,
                "score": round(float(item.score), RANK_PRECISION),
                "rank": rank,
                "rank_pre": rank if rerank_mode == "off" else pre_rank[item.memory.id],
                "reranked": item.rerank_score is not None,
            }
        )
    return snapshot


def build_memory_refs(
    memories: list[UserMemory] | None,
    ranked=None,
) -> list[dict] | None:
    """装配引用列表；`ranked` 可为检索结果（含 `.items`）或其名次快照（§`rank_snapshot`）。"""
    if not memories:
        return None
    snapshot: dict[str, dict] = {}
    if ranked:
        entries = rank_snapshot(ranked) if hasattr(ranked, "items") else list(ranked)
        snapshot = {entry["id"]: entry for entry in entries}
    refs: list[dict] = []
    for memory in memories:
        if memory.status != "active":
            continue
        label = memory_ref_label(memory.content)
        if not label:
            continue
        ref = {
            "id": memory.id,
            "kind": memory.type,
            "label": label,
        }
        entry = snapshot.get(memory.id)
        if entry is not None:
            ref["score"] = entry["score"]
            ref["rank"] = entry["rank"]
            ref["rank_pre"] = entry["rank_pre"]
            ref["reranked"] = entry["reranked"]
        refs.append(ref)
    return refs or None
