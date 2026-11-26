"""Memory 2.0 归因查询（MEM-008）。

聚合 memory_candidates / memories / memory_links / runtime_traces，回答「为什么
记住/没记住/为什么召回这条/谁触发/LLM 调用几次」。历史数据缺 trace 时标注
no_data，不报错；只读旁路，不写任何业务状态。
"""

from app.core import timeutil
from app.core.db import Memory, MemoryCandidateRow, MemoryLinkRow, SessionLocal
from app.repositories import trace_repository

MEMORY_TRACE_STEPS = (
    "memory_ingest",
    "memory_evaluate",
    "memory_embed",
    "memory_lifecycle",
    "memory_recall",
    "memory_command",
)


def _row_dict(row, fields: tuple[str, ...]) -> dict:
    return {field: getattr(row, field, None) for field in fields}


def memory_attribution(memory_id: str) -> dict | None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is None:
            return None
        memory = _row_dict(
            row,
            (
                "id",
                "user_id",
                "content",
                "type",
                "status",
                "importance",
                "confidence",
                "source",
                "salience",
                "visibility",
                "source_ref",
                "merge_chain",
                "superseded_by",
                "created_at",
                "last_reinforced_at",
                "last_decayed_at",
                "forgotten_at",
            ),
        )
        source_ref = row.source_ref
        user_id = row.user_id
        candidate = (
            session.query(MemoryCandidateRow)
            .filter(
                MemoryCandidateRow.user_id == user_id,
                MemoryCandidateRow.source_ref == source_ref,
            )
            .first()
        )
        links = (
            session.query(MemoryLinkRow)
            .filter(
                (MemoryLinkRow.memory_id == memory_id)
                | (MemoryLinkRow.related_memory_id == memory_id)
            )
            .all()
        )
        link_views = []
        for link in links:
            other_id = (
                link.related_memory_id
                if link.memory_id == memory_id
                else link.memory_id
            )
            other = session.get(Memory, other_id)
            link_views.append(
                {
                    "relation": link.relation,
                    "memory_id": link.memory_id,
                    "related_memory_id": link.related_memory_id,
                    "other_status": other.status if other is not None else None,
                    "created_at": link.created_at,
                }
            )
        candidate_id = candidate.id if candidate is not None else None
    steps = _collect_steps(user_id, memory_id=memory_id, candidate_id=candidate_id)
    return {
        "memory": memory,
        "candidate": _candidate_view(candidate),
        "links": link_views,
        "steps": steps,
        "trace_status": "ok" if steps else "no_data",
    }


def candidate_attribution(candidate_id: str) -> dict | None:
    with SessionLocal() as session:
        row = session.get(MemoryCandidateRow, candidate_id)
        if row is None:
            return None
        candidate = _candidate_view(row)
        promoted = None
        if row.status == "approved":
            memory_row = (
                session.query(Memory)
                .filter(
                    Memory.user_id == row.user_id,
                    Memory.source_ref == row.source_ref,
                )
                .first()
            )
            if memory_row is not None:
                promoted = {"memory_id": memory_row.id, "status": memory_row.status}
        steps = _collect_steps(row.user_id, candidate_id=candidate_id)
    return {
        "candidate": candidate,
        "promoted_memory": promoted,
        "steps": steps,
        "trace_status": "ok" if steps else "no_data",
    }


def _candidate_view(row: MemoryCandidateRow | None) -> dict | None:
    if row is None:
        return None
    return _row_dict(
        row,
        (
            "id",
            "user_id",
            "content",
            "proposed_type",
            "source",
            "source_ref",
            "source_table",
            "source_id",
            "salience",
            "status",
            "reason",
            "visibility",
            "created_at",
        ),
    )


def _collect_steps(
    user_id: str, memory_id: str | None = None, candidate_id: str | None = None
) -> list[dict]:
    from datetime import datetime, timedelta

    cutoff = timeutil.now() - timedelta(days=7)
    traces = trace_repository.list_since(cutoff, limit=2000)
    steps: list[dict] = []
    for trace in traces:
        if trace.user_id != user_id:
            continue
        for step in trace.steps or []:
            if step.name not in MEMORY_TRACE_STEPS:
                continue
            extra = step.extra or {}
            if not _step_matches(extra, memory_id=memory_id, candidate_id=candidate_id):
                continue
            steps.append(
                {
                    "step": step.name,
                    "turn_id": trace.turn_id,
                    "status": step.status,
                    "duration_ms": step.duration_ms,
                    "ts": trace.started_at,
                    "extra": extra,
                }
            )
    return steps


def _step_matches(
    extra: dict, memory_id: str | None = None, candidate_id: str | None = None
) -> bool:
    """memory_id 与 candidate_id 命中其一即可（OR 语义）。"""
    if memory_id is None and candidate_id is None:
        return False
    if memory_id is not None:
        if memory_id in (extra.get("memory_id"), extra.get("target_id")):
            return True
        if memory_id in (extra.get("memory_ids") or []):
            return True
        entries = (extra.get("returned") or []) + (extra.get("filtered") or [])
        if any(
            isinstance(entry, dict) and entry.get("id") == memory_id
            for entry in entries
        ):
            return True
    if candidate_id is not None:
        if extra.get("candidate_id") == candidate_id:
            return True
        if candidate_id in (extra.get("candidate_ids") or []):
            return True
    return False
