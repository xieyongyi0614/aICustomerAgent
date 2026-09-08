"""Development 归因查询（DEV-005，对齐 MEM-008 / REF-006 attribution 模式）。

聚合 development_state / development_changes / insights / evidence_links，
回答「这个调制从哪来、幅度为何是这个值、每次变更的 before/after 是什么」。
只读旁路不写任何状态；changes 悬空 insight 标 insight_purged 不中断。
"""

from app.core.db import (
    DevelopmentChangeRow,
    DevelopmentStateRow,
    InsightRow,
    SessionLocal,
)
from app.services.reflection import attribution as reflection_attribution

_TRACE_STEPS = (
    "development_state",
    "development_compile",
    "development_apply",
    "development_rollback",
)


def development_state_attribution(state_id: str) -> dict | None:
    """state 全链回溯：state 行 + changes 历史 + 源 Insight 归因链。"""
    with SessionLocal() as session:
        row = session.get(DevelopmentStateRow, state_id)
        if row is None:
            return None
        changes = (
            session.query(DevelopmentChangeRow)
            .filter(DevelopmentChangeRow.development_state_id == state_id)
            .order_by(DevelopmentChangeRow.created_at.asc(), DevelopmentChangeRow.id.asc())
            .all()
        )
        source_insight = _insight_view(session.get(InsightRow, row.source_insight_id))
        if source_insight is not None:
            chain = reflection_attribution.insight_attribution(row.source_insight_id)
        else:
            chain = None
        return {
            "state": _state_view(row),
            "changes": [_change_view(change) for change in changes],
            "source_insight": source_insight,
            "source_insight_chain": chain,
        }


def list_user_development(user_id: str, limit: int = 50) -> list[dict]:
    """用户调制列表（active 在前）；逐项带源 Insight 摘要。"""
    with SessionLocal() as session:
        rows = (
            session.query(DevelopmentStateRow)
            .filter(DevelopmentStateRow.user_id == user_id)
            .order_by(
                DevelopmentStateRow.status.asc(), DevelopmentStateRow.updated_at.desc()
            )
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [_state_view(row) for row in rows]


def _state_view(row: DevelopmentStateRow) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "character_id": row.character_id,
        "kind": row.kind,
        "key": row.key,
        "value": row.value,
        "strength": row.strength,
        "source_insight_id": row.source_insight_id,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _change_view(row: DevelopmentChangeRow) -> dict:
    return {
        "id": row.id,
        "development_state_id": row.development_state_id,
        "before": row.before,
        "after": row.after,
        "insight_id": row.insight_id,
        "reason": row.reason,
        "created_at": row.created_at,
    }


def _insight_view(row: InsightRow | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "statement": row.statement,
        "type": row.type,
        "confidence": row.confidence,
        "scope": row.scope,
        "status": row.status,
    }
