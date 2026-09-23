"""PLA-010 账本澄清策略：何时回问、问什么（零 LLM，模板渲染）。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from app.core.settings import get_settings
from app.models.ledger import LedgerExtraction, to_minor

CONFIRM_TTL_HOURS = 24

REASON_MISSING_AMOUNT = "missing_amount"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_AMOUNT_OVER_THRESHOLD = "amount_over_threshold"
REASON_CATEGORY_AMBIGUOUS = "category_ambiguous"
REASON_DIRECTION_AMBIGUOUS = "direction_ambiguous"


@dataclass(frozen=True, slots=True)
class CandidateOption:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    reason: str
    question: str
    candidates: tuple[CandidateOption, ...]
    pending_key: str
    expires_at: datetime
    amount_minor: int | None = None
    source_ref: str = ""


def pending_key(source_ref: str, reason: str) -> str:
    material = f"{source_ref}|{reason}"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _question_for(
    reason: str,
    *,
    amount_minor: int | None,
    candidates: tuple[CandidateOption, ...],
) -> str:
    from app.prompts.ledger_clarify import render_clarify_question

    return render_clarify_question(
        reason,
        amount_minor=amount_minor,
        candidates=[option.label for option in candidates],
    )


def should_confirm(
    candidate: LedgerExtraction,
    *,
    settings=None,
    now: datetime | None = None,
    source_ref: str = "",
    category_fallback: bool = False,
    top_categories: tuple[str, ...] = (),
) -> ConfirmationRequest | None:
    cfg = settings if settings is not None else get_settings()
    timestamp = now or datetime.now()
    expires_at = timestamp + timedelta(hours=CONFIRM_TTL_HOURS)
    amount_minor: int | None = None
    if candidate.amount_value:
        try:
            amount_minor = to_minor(candidate.amount_value)
        except Exception:
            amount_minor = None

    def _request(
        reason: str,
        *,
        candidates: tuple[CandidateOption, ...] = (),
        amount: int | None = amount_minor,
    ) -> ConfirmationRequest:
        return ConfirmationRequest(
            reason=reason,
            question=_question_for(reason, amount_minor=amount, candidates=candidates),
            candidates=candidates,
            pending_key=pending_key(source_ref or "anon", reason),
            expires_at=expires_at,
            amount_minor=amount,
            source_ref=source_ref,
        )

    if amount_minor is None or "amount_value" in (candidate.missing_fields or ()):
        return _request(REASON_MISSING_AMOUNT)
    if candidate.confidence < float(cfg.ledger_extraction_min_confidence):
        options = (
            CandidateOption(value=str(candidate.amount_value), label=str(candidate.amount_value)),
        )
        return _request(REASON_LOW_CONFIDENCE, candidates=options)
    if candidate.direction is None:
        options = (
            CandidateOption(value="expense", label="支出"),
            CandidateOption(value="income", label="收入"),
        )
        return _request(REASON_DIRECTION_AMBIGUOUS, candidates=options)
    if category_fallback:
        options = tuple(
            CandidateOption(value=name, label=name) for name in top_categories[:3]
        )
        return _request(REASON_CATEGORY_AMBIGUOUS, candidates=options)
    threshold_minor = to_minor(str(cfg.ledger_confirm_threshold_amount))
    if amount_minor >= threshold_minor:
        return _request(REASON_AMOUNT_OVER_THRESHOLD, amount=amount_minor)
    return None


def request_from_mapping(payload: Mapping[str, Any]) -> ConfirmationRequest:
    candidates = tuple(
        CandidateOption(value=str(item["value"]), label=str(item["label"]))
        for item in payload.get("candidates") or ()
    )
    return ConfirmationRequest(
        reason=str(payload.get("reason") or ""),
        question=str(payload.get("question") or ""),
        candidates=candidates,
        pending_key=str(payload.get("pending_key") or ""),
        expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        amount_minor=payload.get("amount_minor"),
        source_ref=str(payload.get("source_ref") or ""),
    )


def request_to_mapping(request: ConfirmationRequest) -> dict[str, Any]:
    return {
        "reason": request.reason,
        "question": request.question,
        "candidates": [
            {"value": option.value, "label": option.label} for option in request.candidates
        ],
        "pending_key": request.pending_key,
        "expires_at": request.expires_at.isoformat(),
        "amount_minor": request.amount_minor,
        "source_ref": request.source_ref,
    }


__all__ = [
    "CONFIRM_TTL_HOURS",
    "CandidateOption",
    "ConfirmationRequest",
    "REASON_AMOUNT_OVER_THRESHOLD",
    "REASON_CATEGORY_AMBIGUOUS",
    "REASON_DIRECTION_AMBIGUOUS",
    "REASON_LOW_CONFIDENCE",
    "REASON_MISSING_AMOUNT",
    "pending_key",
    "request_from_mapping",
    "request_to_mapping",
    "should_confirm",
]
