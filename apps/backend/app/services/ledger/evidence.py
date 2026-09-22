from __future__ import annotations

from dataclasses import dataclass

from app.models.ledger import LedgerExtraction


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    amount_in_message: bool
    span_matches: bool
    confidence_penalty: float
    reason: str


def verify_amount_evidence(
    extraction: LedgerExtraction, message: str
) -> EvidenceCheck:
    if not extraction.amount_value:
        return EvidenceCheck(False, True, 0.0, "no_amount")
    amount = extraction.amount_value.strip()
    amount_in_message = amount in message
    span = (extraction.evidence_span or "").strip()
    span_matches = True
    if span:
        span_matches = span in message and amount in span
    penalty = 0.0
    reason = "ok"
    if not amount_in_message:
        penalty += 0.4
        reason = "amount_not_in_message"
    if not span_matches:
        penalty += 0.2
        reason = "span_mismatch" if reason == "ok" else f"{reason}+span_mismatch"
    return EvidenceCheck(amount_in_message, span_matches, penalty, reason)
