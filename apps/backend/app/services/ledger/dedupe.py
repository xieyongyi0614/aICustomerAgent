from __future__ import annotations

import hashlib

from app.models.ledger import LedgerExtraction


def extraction_key(message_id: str, extraction: LedgerExtraction) -> str:
    payload = "|".join(
        [
            message_id or "",
            extraction.amount_value or "",
            extraction.direction or "",
            extraction.category_hint or "",
            extraction.merchant_hint or "",
            extraction.occurred_at_hint or "",
        ]
    )
    return "led_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
