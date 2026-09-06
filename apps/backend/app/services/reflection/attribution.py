"""Reflection 归因查询（REF-006，对齐 MEM-008 attribution 模式）。

聚合 insights / reflection_runs / evidence_links / memories，回答「这个 Insight
从哪来、为什么 confidence 是这个值、每条证据的原文是什么」。evidence_links 悬空
（memory 被物理清）标 memory_purged 不中断；只读旁路不写任何状态。
"""

from app.core.db import EvidenceLinkRow, InsightRow, Memory, ReflectionRunRow, SessionLocal

_REFLECTION_TRACE_STEPS = (
    "reflection_evidence",
    "reflection_trigger",
    "reflection_run",
    "reflection_invalidate",
    "context_insight",
)


def _run_view(row: ReflectionRunRow | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "user_id": row.user_id,
        "character_id": row.character_id,
        "trigger": row.trigger,
        "status": row.status,
        "evidence_summary": row.evidence_summary,
        "outcome": row.outcome,
        "llm_used": row.llm_used,
        "insight_ids": row.insight_ids,
        "error": row.error,
        "created_at": row.created_at,
    }


def insight_attribution(insight_id: str) -> dict | None:
    """完整证据链回溯：insight 行 + run 行 + evidence_links→memories 原文。"""
    with SessionLocal() as session:
        row = session.get(InsightRow, insight_id)
        if row is None:
            return None
        insight = {
            "id": row.id,
            "user_id": row.user_id,
            "character_id": row.character_id,
            "statement": row.statement,
            "type": row.type,
            "confidence": row.confidence,
            "scope": row.scope,
            "status": row.status,
            "run_id": row.run_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "invalidated_at": row.invalidated_at,
            "invalidated_reason": row.invalidated_reason,
            "superseded_by": row.superseded_by,
        }
        run = session.get(ReflectionRunRow, row.run_id) if row.run_id else None
        links = (
            session.query(EvidenceLinkRow)
            .filter(EvidenceLinkRow.insight_id == insight_id)
            .all()
        )
        evidence = []
        for link in links:
            memory = session.get(Memory, link.memory_id)
            evidence.append(
                {
                    "memory_id": link.memory_id,
                    "weight": link.weight,
                    "created_at": link.created_at,
                    "content": memory.content if memory is not None else None,
                    "source": memory.source if memory is not None else None,
                    "memory_created_at": memory.created_at if memory is not None else None,
                    "status": "ok" if memory is not None else "memory_purged",
                }
            )
    return {
        "insight": insight,
        "run": _run_view(run),
        "evidence": evidence,
        "trace_status": "ok" if evidence else "no_evidence",
    }


def list_reflection_runs(user_id: str | None = None, limit: int = 50) -> list[dict]:
    """run 列表（额度审计与 skipped 原因排查；只读）。"""
    with SessionLocal() as session:
        query = session.query(ReflectionRunRow)
        if user_id:
            query = query.filter(ReflectionRunRow.user_id == user_id)
        rows = (
            query.order_by(ReflectionRunRow.created_at.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [_run_view(row) for row in rows]
