from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.core.llm_factory import set_llm
from app.models.ledger import LedgerExtraction
from app.services.ledger.dedupe import extraction_key
from app.services.ledger.evidence import verify_amount_evidence
from tests.conftest import FakeLLM

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 6, 15, 12, 0, 0)


def _llm(payload: dict) -> FakeLLM:
    return FakeLLM(structured_responses={"LedgerExtraction": payload})


def test_extract_basic_expense():
    from app.chains.ledger_extraction_chain import extract_ledger

    set_llm(
        _llm(
            {
                "is_ledger_intent": True,
                "amount_value": "20",
                "direction": "expense",
                "category_hint": "快餐",
                "evidence_span": "20块",
                "confidence": 0.95,
                "missing_fields": [],
            }
        )
    )
    result = extract_ledger(
        "中午吃了20块快餐", message_id="m1", now=NOW, world_time=NOW
    )
    assert result.amount_value == "20"
    assert result.direction == "expense"
    assert result.category_hint == "快餐"


def test_non_ledger_message_early_exit():
    from app.chains.ledger_extraction_chain import extract_ledger

    set_llm(_llm({"is_ledger_intent": False, "confidence": 0.0}))
    result = extract_ledger("今天天气不错", message_id="m2", now=NOW, world_time=NOW)
    assert result.is_ledger_intent is False
    assert result.amount_value is None


def test_missing_amount_goes_to_clarification():
    from app.chains.ledger_extraction_chain import classify_extraction, extract_ledger

    set_llm(
        _llm(
            {
                "is_ledger_intent": True,
                "amount_value": None,
                "direction": "expense",
                "category_hint": "快餐",
                "confidence": 0.8,
                "missing_fields": ["amount_value"],
            }
        )
    )
    result = extract_ledger("中午吃了快餐", message_id="m3", now=NOW, world_time=NOW)
    assert "amount_value" in result.missing_fields
    assert classify_extraction(result, min_confidence=0.70) == "clarify"


def test_low_confidence_goes_to_clarification():
    from app.chains.ledger_extraction_chain import classify_extraction

    extraction = LedgerExtraction(
        is_ledger_intent=True,
        amount_value="20",
        direction="expense",
        confidence=0.5,
        missing_fields=(),
    )
    assert classify_extraction(extraction, min_confidence=0.70) == "clarify"


def test_high_confidence_produces_candidate():
    from app.chains.ledger_extraction_chain import classify_extraction

    extraction = LedgerExtraction(
        is_ledger_intent=True,
        amount_value="20",
        direction="expense",
        confidence=0.95,
        missing_fields=(),
    )
    assert classify_extraction(extraction, min_confidence=0.70) == "confirmable"


def test_amount_not_in_message_penalized():
    extraction = LedgerExtraction(
        is_ledger_intent=True,
        amount_value="30",
        evidence_span="30元",
        confidence=0.9,
    )
    check = verify_amount_evidence(extraction, "中午吃了20块快餐")
    assert check.amount_in_message is False
    assert check.confidence_penalty > 0


def test_evidence_span_mismatch_penalized():
    extraction = LedgerExtraction(
        is_ledger_intent=True,
        amount_value="20",
        evidence_span="30元",
        confidence=0.9,
    )
    check = verify_amount_evidence(extraction, "中午吃了20块快餐")
    assert check.span_matches is False
    assert check.confidence_penalty > 0


def test_structured_chain_used_not_free_parse():
    source = (
        BACKEND / "app" / "chains" / "ledger_extraction_chain.py"
    ).read_text(encoding="utf-8")
    assert "build_structured_chain" in source
    assert "json.loads" not in source


def test_llm_from_factory():
    source = (
        BACKEND / "app" / "chains" / "ledger_extraction_chain.py"
    ).read_text(encoding="utf-8")
    assert "ChatOpenAI(" not in source


def test_extraction_chain_performs_no_db_write():
    source = (
        BACKEND / "app" / "chains" / "ledger_extraction_chain.py"
    ).read_text(encoding="utf-8")
    assert "app.repositories" not in source
    assert "SessionLocal" not in source
    assert "session.add" not in source


def test_dedupe_key_is_deterministic():
    extraction = LedgerExtraction(
        is_ledger_intent=True,
        amount_value="20",
        direction="expense",
        category_hint="快餐",
    )
    a = extraction_key("m1", extraction)
    b = extraction_key("m1", extraction)
    c = extraction_key("m2", extraction)
    assert a == b
    assert a != c
    assert a.startswith("led_")


def test_prompt_golden_snapshot():
    from app.prompts.ledger_extraction import LEDGER_EXTRACTION_PROMPT

    assert "原样摘出" in LEDGER_EXTRACTION_PROMPT
    assert "不得换算" in LEDGER_EXTRACTION_PROMPT
    assert "不得推断" in LEDGER_EXTRACTION_PROMPT or "绝不猜" in LEDGER_EXTRACTION_PROMPT
