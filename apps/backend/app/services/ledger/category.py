from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.core.settings import get_settings
from app.repositories import ledger_repository

_SUFFIX_RE = re.compile(r"(费|钱|开支|支出)$")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    category_id: str | None
    category_name: str
    matched_step: int
    reason: str
    confidence: float


def _normalize_text(text: str) -> str:
    cleaned = _SPACE_RE.sub("", text.strip())
    cleaned = cleaned.replace("　", "")
    cleaned = _SUFFIX_RE.sub("", cleaned)
    return cleaned


def normalize(
    user_id: str,
    hint: str | None,
    *,
    kind: str = "expense",
    now: datetime | None = None,
) -> NormalizationResult:
    categories = ledger_repository.list_categories(user_id, kind=kind)
    fallback_name = get_settings().ledger_category_fallback
    fallback = next((row for row in categories if row.name == fallback_name), None)

    def _fallback(reason: str, step: int) -> NormalizationResult:
        return NormalizationResult(
            category_id=fallback.id if fallback else None,
            category_name=fallback_name,
            matched_step=step,
            reason=reason,
            confidence=0.1,
        )

    if not hint or not hint.strip():
        return _fallback("empty_hint", 1)

    raw = hint.strip()
    for row in categories:
        if row.name == raw:
            return NormalizationResult(row.id, row.name, 2, "exact", 0.98)
    for row in categories:
        if raw in (row.aliases or []):
            return NormalizationResult(row.id, row.name, 3, "alias", 0.95)

    rule = _normalize_text(raw)
    if rule and rule != raw:
        for row in categories:
            if row.name == rule or rule in (row.aliases or []):
                return NormalizationResult(row.id, row.name, 4, "rule", 0.85)

    best = None
    for row in categories:
        candidates = [row.name, *(row.aliases or [])]
        for candidate in candidates:
            if candidate and (candidate in raw or (rule and candidate in rule)):
                length = len(candidate)
                if best is None or length > best[0]:
                    best = (length, row)
    if best is not None:
        row = best[1]
        return NormalizationResult(row.id, row.name, 5, "substring", 0.7)

    return _fallback("fallback", 6)


def add_category(
    user_id: str,
    name: str,
    kind: str,
    *,
    parent_id: str | None = None,
    aliases: list[str] | None = None,
    now: datetime | None = None,
):
    return ledger_repository.create_category(
        user_id,
        name,
        kind,
        parent_id=parent_id,
        aliases=aliases or [],
        is_seed=False,
        now=now,
    )


def add_alias(user_id: str, category_id: str, alias: str) -> bool:
    if not alias:
        return False
    return ledger_repository.append_category_alias(user_id, category_id, alias)
