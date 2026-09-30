from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.character.asuna.ledger_categories import SEED_CATEGORY_TREE
from app.core.settings import get_settings
from app.repositories import ledger_repository

_SUFFIX_RE = re.compile(r"(费|钱|开支|支出)$")
_SPACE_RE = re.compile(r"\s+")
_SEED_ALIASES: dict[str, frozenset[str]] = {
    str(node["name"]): frozenset(node.get("aliases") or ()) for node in SEED_CATEGORY_TREE
}


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    category_id: str | None
    category_name: str
    matched_step: int
    reason: str
    confidence: float


@dataclass(frozen=True, slots=True)
class LearnedRule:
    keyword: str
    category_id: str
    category_name: str


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


def list_user_categories(user_id: str, *, kind: str | None = None):
    return ledger_repository.list_categories(user_id, kind=kind)


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


def list_learned_rules(user_id: str) -> list[LearnedRule]:
    learned: list[LearnedRule] = []
    for row in ledger_repository.list_categories(user_id):
        seeded = _SEED_ALIASES.get(row.name, frozenset())
        for alias in row.aliases or []:
            if alias in seeded:
                continue
            learned.append(
                LearnedRule(
                    keyword=str(alias), category_id=row.id, category_name=row.name
                )
            )
    return learned


FALLBACK_REASONS = ("empty_hint", "fallback")


def classify_preview(
    user_id: str,
    note: str | None,
    *,
    kind: str = "expense",
    now: datetime | None = None,
) -> NormalizationResult:
    return normalize(user_id, note, kind=kind, now=now)
