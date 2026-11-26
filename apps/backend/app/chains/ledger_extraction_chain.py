from __future__ import annotations

from datetime import datetime

from app.chains.structured import build_structured_chain
from app.models.ledger import LedgerExtraction
from app.prompts.ledger_extraction import LEDGER_EXTRACTION_PROMPT
from app.services.ledger.dedupe import extraction_key
from app.services.ledger.evidence import verify_amount_evidence
from app.services.ledger.timeparse import resolve_occurred_at


def build_ledger_extraction_chain(llm=None):
    return build_structured_chain(
        [
            ("system", LEDGER_EXTRACTION_PROMPT),
            ("user", "用户消息：{user_input}"),
        ],
        LedgerExtraction,
        llm,
    )


def extract_ledger(
    message: str,
    *,
    message_id: str,
    now: datetime,
    world_time: datetime | None = None,
    timezone: str | None = None,
    llm=None,
) -> LedgerExtraction:
    chain = build_ledger_extraction_chain(llm)
    raw = chain.invoke({"user_input": message})
    if raw is None:
        return LedgerExtraction(
            is_ledger_intent=False, confidence=0.0, missing_fields=("extraction",)
        )
    extraction = raw
    if not extraction.is_ledger_intent:
        return LedgerExtraction(is_ledger_intent=False, confidence=0.0)

    check = verify_amount_evidence(extraction, message)
    confidence = max(0.0, extraction.confidence - check.confidence_penalty)
    missing = list(extraction.missing_fields or ())

    time_result = resolve_occurred_at(
        extraction.occurred_at_hint,
        world_time=world_time or now,
        timezone=timezone,
    )
    occurred_at_resolved = time_result.resolved
    if occurred_at_resolved is None and "occurred_at" not in missing:
        if extraction.occurred_at_hint:
            missing.append("occurred_at")

    if not extraction.amount_value and "amount_value" not in missing:
        missing.append("amount_value")

    return extraction.model_copy(
        update={
            "confidence": confidence,
            "missing_fields": tuple(missing),
            "occurred_at_resolved": occurred_at_resolved,
        }
    )


def classify_extraction(
    extraction: LedgerExtraction, *, min_confidence: float
) -> str:
    if not extraction.is_ledger_intent:
        return "ignore"
    if extraction.missing_fields:
        return "clarify"
    if extraction.confidence < min_confidence:
        return "clarify"
    return "confirmable"


__all__ = [
    "build_ledger_extraction_chain",
    "classify_extraction",
    "extract_ledger",
    "extraction_key",
]
