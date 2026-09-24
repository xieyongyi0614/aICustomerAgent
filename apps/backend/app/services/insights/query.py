"""API-006 产品级洞察读面：零 LLM、可复算 domain 映射。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.db import EvidenceLinkRow, InsightRow, Memory, SessionLocal

HEADLINE_MAX = 40


@dataclass(frozen=True, slots=True)
class InsightEvidence:
    memory_id: str
    weight: float
    content: str | None
    memory_type: str | None
    status: str


@dataclass(frozen=True, slots=True)
class InsightItem:
    id: str
    domain: str
    headline: str
    narrative: str
    evidence: list[InsightEvidence]
    source_refs: list[dict]
    generated_at: str
    confidence: float


def headline_of(statement: str, limit: int = HEADLINE_MAX) -> str:
    text = (statement or "").strip()
    if not text:
        return ""
    first = text.split("。", 1)[0].split("\n", 1)[0].strip()
    if len(first) <= limit:
        return first
    return first[:limit] + "…"


def _derive_domain(row: InsightRow, evidence_types: set[str]) -> str | None:
    if row.status != "active":
        return None
    if row.type == "pattern" and "behavior_pattern" in evidence_types:
        return "ledger"
    if row.scope == "user":
        return "home"
    return None


def list_insights(
    user_id: str,
    domain: str | None = None,
    limit: int = 10,
) -> list[InsightItem]:
    """按冻结规则派生 domain；无洞察返空列表。"""
    if domain == "health":
        return []
    effective = domain or "home"
    with SessionLocal() as session:
        rows = (
            session.query(InsightRow)
            .filter(InsightRow.user_id == user_id, InsightRow.status == "active")
            .order_by(
                InsightRow.confidence.desc(),
                InsightRow.created_at.desc(),
                InsightRow.id.asc(),
            )
            .all()
        )
        items: list[InsightItem] = []
        for row in rows:
            links = (
                session.query(EvidenceLinkRow)
                .filter(EvidenceLinkRow.insight_id == row.id)
                .all()
            )
            evidence: list[InsightEvidence] = []
            evidence_types: set[str] = set()
            source_refs: list[dict] = []
            for link in links:
                memory = session.get(Memory, link.memory_id)
                if memory is not None:
                    evidence_types.add(getattr(memory, "type", "") or "")
                    source_refs.append(
                        {
                            "kind": memory.source or "conversation",
                            "ref": getattr(memory, "source_ref", None) or memory.id,
                            "label": headline_of(memory.content or "", 16),
                        }
                    )
                evidence.append(
                    InsightEvidence(
                        memory_id=link.memory_id,
                        weight=float(link.weight or 0.0),
                        content=memory.content if memory is not None else None,
                        memory_type=getattr(memory, "type", None) if memory else None,
                        status="ok" if memory is not None else "memory_purged",
                    )
                )
            derived = _derive_domain(row, evidence_types)
            if derived is None or derived != effective:
                continue
            items.append(
                InsightItem(
                    id=row.id,
                    domain=derived,
                    headline=headline_of(row.statement),
                    narrative=row.statement,
                    evidence=evidence,
                    source_refs=source_refs,
                    generated_at=row.created_at.isoformat() if row.created_at else "",
                    confidence=float(row.confidence or 0.0),
                )
            )
            if len(items) >= limit:
                break
        return items
