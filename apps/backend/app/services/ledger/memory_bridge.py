"""PLA-014 记忆桥：仅 behavior_pattern + 文本零金额双保险。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.services.governance.prompt_guard import (
    FinancialDetailInPrompt,
    assert_no_financial_detail,
)
from app.services.memory import ingest as memory_ingest

logger = logging.getLogger(__name__)

ALLOWED_MEMORY_TYPE = "behavior_pattern"
SOURCE_TABLE = "ledger_insights"
ADVICE_MARKERS = ("建议", "应该", "最好", "推荐")


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    accepted: bool
    candidate_id: str | None
    reason: str


def filter_and_ingest(
    *,
    user_id: str,
    insight_id: str,
    insight_type: str,
    statement: str,
    now: datetime | None = None,
) -> IngestOutcome:
    if insight_type != ALLOWED_MEMORY_TYPE:
        return IngestOutcome(False, None, f"type_not_allowed:{insight_type}")
    text = statement.strip()
    for marker in ADVICE_MARKERS:
        if marker in text:
            return IngestOutcome(False, None, f"advice_language:{marker}")
    try:
        assert_no_financial_detail(text)
    except FinancialDetailInPrompt:
        return IngestOutcome(False, None, "financial_detail")
    row = memory_ingest._create_candidate(
        user_id=user_id,
        character_id="asuna",
        source_table=SOURCE_TABLE,
        source_id=insight_id,
        content=text,
        proposed_type=ALLOWED_MEMORY_TYPE,
        source_kind="ai_inferred",
        salience_init=0.55,
        created_at=now,
    )
    return IngestOutcome(True, row.id, "ok" if row else "noop")


def ingest_patterns(
    *,
    user_id: str,
    statements: list[str],
    now: datetime | None = None,
) -> list[IngestOutcome]:
    outcomes = []
    for index, statement in enumerate(statements):
        outcomes.append(
            filter_and_ingest(
                user_id=user_id,
                insight_id=f"ledger-pattern-{index}",
                insight_type=ALLOWED_MEMORY_TYPE,
                statement=statement,
                now=now,
            )
        )
    return outcomes


__all__ = [
    "ALLOWED_MEMORY_TYPE",
    "IngestOutcome",
    "filter_and_ingest",
    "ingest_patterns",
]
