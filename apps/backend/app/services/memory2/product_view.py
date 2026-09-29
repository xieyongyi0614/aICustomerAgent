"""API-007 记忆域产品读面与用户写面（零 LLM、确定性派生）。

读面口径按 D5：只返 `status == "active"`，`total` 与分组同口径、同一内存快照。
写面**委托**域内既有写面（`memory_repository.update_memory_content` /
`memory2.lifecycle.explicit_forget`），不直写 `memories`、不硬删。

不暴露 `status` / `salience` / `confidence` / 上限 / 衰减（D5 / D12）。

派生字段说明：`memory_repository.list_active` 返回的 `UserMemory` 不含
`merge_chain` / `source_ref`（`_to_memory` 未映射），而 `source_count` 与
`source_kind` 必须由它们派生；仓储层属禁止改动面，故此处以一次窄读查询按 id 补齐。
行集仍由 `list_active` 提供，active 过滤口径不在本模块重复实现。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.db import Memory as MemoryRow
from app.core.db import SessionLocal
from app.repositories import memory_repository, trace_repository
from app.services.memory2 import lifecycle as memory_lifecycle
from app.services.memory2.types import normalize_type

logger = logging.getLogger(__name__)

CHARACTER_ID = "asuna"

RECEIPT_WINDOW_DAYS = 30
RECEIPT_TRACE_LIMIT = 2000
RECEIPT_TRACE_STEP = "memory_retrieve_v2"

CONTENT_MIN = 1
CONTENT_MAX = 500

GROUP_ORDER = ("preference", "habit", "goal", "now")

GROUP_LABELS = {
    "preference": "长期偏好",
    "habit": "习惯",
    "goal": "目标",
    "now": "当下",
}

TYPE_TO_GROUP = {
    "user_preference": "preference",
    "behavior_pattern": "habit",
    "commitment": "goal",
    "milestone_event": "goal",
    "user_fact": "now",
    "experience": "now",
    "important_event": "now",
    "relationship_fact": "now",
    "relationship_event": "now",
}

TYPE_LABELS = {
    "user_preference": "偏好",
    "behavior_pattern": "习惯",
    "commitment": "目标",
    "milestone_event": "目标",
    "user_fact": "近况",
    "experience": "近况",
    "relationship_fact": "关系",
}

SOURCE_LABELS = {
    "conversation": "对话提及",
    "action_records": "任务完成",
    "world_events": "生活事件",
    "relationship_events": "相处经历",
    "relationship_milestones": "关系里程碑",
    "character_goals": "目标达成",
    "commands": "你直接交代",
    "ledger_insights": "记账观察",
    "user_stated": "你亲口说过",
    "user_derived": "从对话里整理",
    "ai_inferred": "我自己留意到的",
}

RECEIPT_KINDS = (
    ("turn", "recall_turn", "已用于对话"),
    ("autonomy_tick", "recall_autonomy", "已用于任务排序"),
    ("proactive", "recall_proactive", "已用于主动关心"),
)

_RECEIPT_BY_TRACE_KIND = {trace: (kind, label) for trace, kind, label in RECEIPT_KINDS}


class MemoryNotFoundError(Exception):
    """id 不存在，或状态非 active（两者不区分，避免确认 id 存在）。"""


class MemoryForbiddenError(Exception):
    """记忆归属他人。"""


class UnknownMemoryTypeError(Exception):
    """存储类型不在冻结映射表内——显式失败，不静默塞进默认分组。"""


@dataclass(frozen=True, slots=True)
class MemoryReceipt:
    kind: str
    label: str
    ts: str | None
    ref: str | None


@dataclass(frozen=True, slots=True)
class ProductMemoryItem:
    id: str
    kind: str
    type: str
    type_label: str
    content: str
    source_kind: str
    source_label: str
    source_count: int
    last_updated: str | None
    usage_receipts: list[MemoryReceipt]


@dataclass(frozen=True, slots=True)
class ProductMemoryGroup:
    kind: str
    label: str
    items: list[ProductMemoryItem]


@dataclass(frozen=True, slots=True)
class ProductMemoryList:
    generated_at: str
    total: int
    added_this_week: int
    groups: list[ProductMemoryGroup]
    degraded: bool


def group_for(memory_type: str | None) -> str:
    group = TYPE_TO_GROUP.get(memory_type or "")
    if group is None:
        logger.error("记忆类型未映射到产品分组: %r", memory_type)
        raise UnknownMemoryTypeError(memory_type or "")
    return group


def type_label_for(normalized_type: str | None) -> str:
    label = TYPE_LABELS.get(normalized_type or "")
    if label is None:
        logger.error("记忆类型无中文标签: %r", normalized_type)
        raise UnknownMemoryTypeError(normalized_type or "")
    return label


def row_facts(memory_ids: list[str]) -> dict[str, dict]:
    """按 id 补读原始行事实：`merge_chain` / `source_ref` / `forgotten_at` / `user_id` / `status`。

    `UserMemory` 未映射 `merge_chain` / `source_ref` / `forgotten_at` —— 守卫与派生都走本函数
    读原始列。`status` 值域已于 2026-09-29 补全 `decayed` / `forgotten`（原缺致读这两态抛
    `ValidationError`），但仍统一以原始列为准，避免两处口径分叉。
    """
    if not memory_ids:
        return {}
    with SessionLocal() as session:
        rows = (
            session.query(
                MemoryRow.id,
                MemoryRow.merge_chain,
                MemoryRow.source_ref,
                MemoryRow.forgotten_at,
                MemoryRow.user_id,
                MemoryRow.status,
            )
            .filter(MemoryRow.id.in_(memory_ids))
            .all()
        )
    return {
        row_id: {
            "merge_chain": merge_chain,
            "source_ref": source_ref,
            "forgotten_at": forgotten_at,
            "user_id": user_id,
            "status": status,
        }
        for row_id, merge_chain, source_ref, forgotten_at, user_id, status in rows
    }


def source_kind_of(source: str | None, extra: dict) -> str:
    ref = extra.get("source_ref")
    table = ref.get("table") if isinstance(ref, dict) else None
    if isinstance(table, str) and table:
        return table
    return source or ""


def source_label_for(source_kind: str) -> str:
    return SOURCE_LABELS.get(source_kind, source_kind)


def source_count_of(extra: dict) -> int:
    chain = extra.get("merge_chain")
    return 1 + (len(chain) if isinstance(chain, list) else 0)


def _week_start(now: datetime) -> datetime:
    return (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _matched_ids(extra: dict, candidates: set[str]) -> set[str]:
    """检索步命中语义：只认「被采用」的字段，`filtered` 不算使用。"""
    hit: set[str] = set()
    for key in ("memory_id", "target_id"):
        value = extra.get(key)
        if isinstance(value, str) and value in candidates:
            hit.add(value)
    for value in extra.get("memory_ids") or []:
        if isinstance(value, str) and value in candidates:
            hit.add(value)
    for entry in extra.get("returned") or []:
        if isinstance(entry, dict):
            entry_id = entry.get("id")
            if isinstance(entry_id, str) and entry_id in candidates:
                hit.add(entry_id)
    return hit


def receipts_for(
    user_id: str, memory_ids: list[str]
) -> tuple[dict[str, list[MemoryReceipt]], bool]:
    """用途回执：只来自 `runtime_traces` 的检索步；每 kind 留最新一条。"""
    index: dict[str, list[MemoryReceipt]] = {mid: [] for mid in memory_ids}
    if not memory_ids:
        return index, False
    candidates = set(memory_ids)
    try:
        cutoff = datetime.now() - timedelta(days=RECEIPT_WINDOW_DAYS)
        traces = trace_repository.list_since(cutoff, limit=RECEIPT_TRACE_LIMIT)
    except Exception:
        logger.exception("用途回执派生失败，按区块级降级返回空回执")
        return index, True

    seen: dict[str, set[str]] = {mid: set() for mid in memory_ids}
    for trace in traces:
        if trace.user_id != user_id:
            continue
        trace_kind = getattr(trace.kind, "value", None) or str(trace.kind or "")
        mapped = _RECEIPT_BY_TRACE_KIND.get(trace_kind)
        if mapped is None:
            continue
        receipt_kind, label = mapped
        for step in trace.steps or []:
            if step.name != RECEIPT_TRACE_STEP:
                continue
            for memory_id in _matched_ids(step.extra or {}, candidates):
                if receipt_kind in seen[memory_id]:
                    continue
                seen[memory_id].add(receipt_kind)
                index[memory_id].append(
                    MemoryReceipt(
                        kind=receipt_kind,
                        label=label,
                        ts=trace.started_at.isoformat() if trace.started_at else None,
                        ref=trace.turn_id,
                    )
                )
    order = {kind: position for position, (_, kind, _) in enumerate(RECEIPT_KINDS)}
    for receipts in index.values():
        receipts.sort(key=lambda receipt: order[receipt.kind])
    return index, False


def _item(row, extra: dict, receipts: list[MemoryReceipt]) -> ProductMemoryItem:
    normalized = normalize_type(row.type) or row.type
    source_kind = source_kind_of(row.source, extra)
    return ProductMemoryItem(
        id=row.id,
        kind=group_for(row.type),
        type=normalized,
        type_label=type_label_for(normalized),
        content=row.content,
        source_kind=source_kind,
        source_label=source_label_for(source_kind),
        source_count=source_count_of(extra),
        last_updated=row.updated_at.isoformat() if row.updated_at else None,
        usage_receipts=receipts,
    )


def list_product_memories(user_id: str, limit: int = 200) -> ProductMemoryList:
    rows = memory_repository.list_active(user_id, CHARACTER_ID, limit=limit)
    facts = row_facts([row.id for row in rows])
    receipts, degraded = receipts_for(user_id, [row.id for row in rows])
    week_start = _week_start(datetime.now())

    buckets: dict[str, list[ProductMemoryItem]] = {kind: [] for kind in GROUP_ORDER}
    for row in rows:
        item = _item(row, facts.get(row.id, {}), receipts.get(row.id, []))
        buckets[item.kind].append(item)

    groups = [
        ProductMemoryGroup(kind=kind, label=GROUP_LABELS[kind], items=buckets[kind])
        for kind in GROUP_ORDER
    ]
    total = sum(len(group.items) for group in groups)
    added_this_week = sum(
        1 for row in rows if row.created_at and row.created_at >= week_start
    )
    return ProductMemoryList(
        generated_at=datetime.now().isoformat(),
        total=total,
        added_this_week=added_this_week,
        groups=groups,
        degraded=degraded,
    )


def _guard(memory_id: str, user_id: str, allowed: tuple[str, ...]) -> dict:
    """归属与状态守卫（读原始列，避免 `UserMemory` 投影丢列）。"""
    facts = row_facts([memory_id]).get(memory_id)
    if facts is None:
        raise MemoryNotFoundError(memory_id)
    if facts["user_id"] != user_id:
        raise MemoryForbiddenError(memory_id)
    if facts["status"] not in allowed:
        raise MemoryNotFoundError(memory_id)
    return facts


def edit_memory(
    memory_id: str,
    user_id: str,
    content: str,
    importance: float | None = None,
) -> ProductMemoryItem:
    _guard(memory_id, user_id, (memory_lifecycle.STATUS_ACTIVE,))
    row = memory_repository.update_memory_content(
        memory_id, content, importance=importance
    )
    if row is None:
        raise MemoryNotFoundError(memory_id)
    facts = row_facts([memory_id])
    receipts, _ = receipts_for(user_id, [memory_id])
    return _item(row, facts.get(memory_id, {}), receipts.get(memory_id, []))


def forget_memory_for_user(memory_id: str, user_id: str, trace=None) -> str:
    """置 `forgotten`（不硬删）+ 清向量；已 forgotten 幂等，`forgotten_at` 保留首次时刻。

    只接受 `active`（首次遗忘）与 `forgotten`（幂等重放）；`decayed` / `superseded` /
    `invalidated` 一律 404——产品面只见 `active`，对不可见条目动手会确认其存在。
    """
    facts = _guard(
        memory_id,
        user_id,
        (memory_lifecycle.STATUS_ACTIVE, memory_lifecycle.STATUS_FORGOTTEN),
    )
    first_forgotten_at = facts["forgotten_at"]
    if not memory_lifecycle.explicit_forget(memory_id, trace=trace):
        raise MemoryNotFoundError(memory_id)
    if first_forgotten_at is not None:
        return first_forgotten_at.isoformat()

    refreshed = row_facts([memory_id]).get(memory_id, {}).get("forgotten_at")
    return (refreshed or datetime.now()).isoformat()
