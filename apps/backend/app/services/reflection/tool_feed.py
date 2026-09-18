"""工具效能 Insight 只读反哺（TOOL-009 §4.3）。

**接口即边界**：本模块只提供读方法（`interest_signal` / `autonomy_signal` /
`tool_ids_of_insights` / `is_enabled`），从 API 形状上排除"反思改工具状态"的可能——
零 `write_registry` / `trip_breaker` 类方法，零导入 `services/tool/registry.py`。

消费方：`decision_pipeline._interest`（interest 维软信号，按工具身份匹配）与
`autonomy_policy`（候选收缩理由）。缺省（无工具 Insight / 子闸关 / 读取异常）返回空
信号，消费方行为与 V2.3.0 逐字节一致。工具身份由 `evidence_links.memory_id` 的
`tool:<tool_id>:...` 命名空间还原（零新建表、零新列）。
"""

import logging

from app.character.asuna import evaluation as asuna_evaluation
from app.core.db import EvidenceLinkRow, SessionLocal
from app.core.settings import get_settings
from app.models.reflection import TOOL_INSIGHT_TYPES
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import lifecycle as reflection_lifecycle

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_tool_feed"

TOOL_FEED_MAX_ITEMS = 5
TOOL_FEED_NOTE_LIMIT = 3


def is_enabled(settings=None) -> bool:
    """反哺开关：工具反思子闸（默认 off）关闭时零读取、零信号。"""
    settings = settings or get_settings()
    return bool(getattr(settings, "v24_tool_reflection_enabled", False))


def interest_signal(user_id: str, *, limit: int = TOOL_FEED_MAX_ITEMS) -> list[dict]:
    """active 工具效能 Insight → interest 维软信号（按 confidence 降序，带工具身份）。

    返回 `[{insight_id, type, statement, confidence, scope, tool_ids}]`；异常降级为空信号。
    """
    settings = get_settings()
    if not is_enabled(settings):
        return []
    try:
        insights = [
            insight
            for insight in reflection_lifecycle.list_active_insights(
                user_id,
                min_confidence=settings.v2_reflection_min_confidence,
                limit=limit,
            )
            if insight.type in TOOL_INSIGHT_TYPES
        ]
        tool_ids = tool_ids_of_insights([insight.id for insight in insights])
    except Exception:
        logger.exception("工具效能 Insight 读取失败，返回空信号：%s", user_id)
        return []
    return [
        {
            "insight_id": insight.id,
            "type": insight.type,
            "statement": insight.statement,
            "confidence": insight.confidence,
            "scope": insight.scope,
            "tool_ids": tool_ids.get(insight.id, []),
        }
        for insight in insights
    ]


def autonomy_signal(user_id: str, *, limit: int = TOOL_FEED_MAX_ITEMS) -> dict:
    """自治侧只读信号：候选收缩理由（`notes`）+ 结构化清单（`insights`）。

    自治只把信号当**输入面**（追加理由），不拆闸门、不改八步裁决（TOOL-006 同款纪律）。
    """
    signal = interest_signal(user_id, limit=limit)
    if not signal:
        return {}
    notes = [
        f"{asuna_evaluation.TOOL_INSIGHT_LABELS.get(item['type'], item['type'])}："
        f"{item['statement']}"
        for item in signal[:TOOL_FEED_NOTE_LIMIT]
    ]
    return {
        "count": len(signal),
        "notes": notes,
        "insights": signal,
        "unreliable_capabilities": [
            item["statement"]
            for item in signal
            if item["type"] == "capability_note"
        ],
    }


def tool_ids_of_insights(insight_ids: list[str]) -> dict[str, list[str]]:
    """Insight → 证据链上的工具身份（只读 `evidence_links` 投影）。"""
    if not insight_ids:
        return {}
    with SessionLocal() as session:
        rows = (
            session.query(EvidenceLinkRow.insight_id, EvidenceLinkRow.memory_id)
            .filter(EvidenceLinkRow.insight_id.in_(list(insight_ids)))
            .all()
        )
    tool_ids: dict[str, list[str]] = {}
    for insight_id, memory_id in rows:
        tool_id = reflection_evidence.tool_id_of_evidence_id(memory_id)
        if tool_id is None:
            continue
        bucket = tool_ids.setdefault(insight_id, [])
        if tool_id not in bucket:
            bucket.append(tool_id)
    return tool_ids
