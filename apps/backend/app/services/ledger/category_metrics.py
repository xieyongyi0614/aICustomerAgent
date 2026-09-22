from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.ledger.category import NormalizationResult, normalize


@dataclass(frozen=True, slots=True)
class Sample:
    hint: str
    expected_name: str
    kind: str = "expense"


@dataclass(frozen=True, slots=True)
class CategoryMetricsReport:
    total: int
    hits: int
    fallbacks: int
    hit_rate: float
    fallback_rate: float
    consistent: bool
    mismatches: tuple[str, ...]


def evaluate(
    samples: Sequence[Sample], *, user_id: str, expected_hit_rate: float = 0.8
) -> CategoryMetricsReport:
    hits = 0
    fallbacks = 0
    mismatches: list[str] = []
    seen: dict[str, str] = {}
    consistent = True
    for sample in samples:
        result: NormalizationResult = normalize(user_id, sample.hint, kind=sample.kind)
        if result.reason == "fallback" or result.reason == "empty_hint":
            fallbacks += 1
        elif result.category_name == sample.expected_name:
            hits += 1
        else:
            mismatches.append(f"{sample.hint}->{result.category_name}!={sample.expected_name}")
        previous = seen.get(sample.hint)
        if previous is not None and previous != result.category_name:
            consistent = False
        seen[sample.hint] = result.category_name
    total = len(samples) or 1
    return CategoryMetricsReport(
        total=len(samples),
        hits=hits,
        fallbacks=fallbacks,
        hit_rate=hits / total,
        fallback_rate=fallbacks / total,
        consistent=consistent,
        mismatches=tuple(mismatches),
    )
