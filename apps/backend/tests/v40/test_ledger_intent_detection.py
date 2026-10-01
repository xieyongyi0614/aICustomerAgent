"""PLA-009 记账意图词表用例（零 LLM）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.services.action.detector import detect_action_intent

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 12, 0, 0)


def _detect(content: str):
    return detect_action_intent(content, now=NOW)


def test_detects_basic_ledger_intent():
    intent = _detect("中午吃了20块快餐")
    assert intent is not None
    assert intent.action_type == "record_ledger_entry"
    assert intent.params.get("amount_minor") == 2000
    assert intent.params.get("direction") == "expense"
    assert intent.params.get("source") == "conversation"
    assert intent.params.get("idempotency_key")


def test_detects_spend_verbs():
    for text in ("花了30元买书", "付了15块打车", "买了水果20元"):
        intent = _detect(text)
        assert intent is not None, text
        assert intent.action_type == "record_ledger_entry", text


def test_detects_income():
    intent = _detect("收到报销200")
    assert intent is not None
    assert intent.action_type == "record_ledger_entry"
    assert intent.params.get("direction") == "income"
    assert intent.params.get("amount_minor") == 20000


def test_detects_revise_intent():
    intent = _detect("刚才那笔记错了，撤掉")
    assert intent is not None
    assert intent.action_type == "revise_ledger_entry"


def test_rejects_memory_verb_false_positive():
    assert _detect("我记得你昨天说过") is None


def test_rejects_non_amount_message():
    assert _detect("今天好累") is None


def test_detector_stays_zero_llm():
    source = (BACKEND / "app/services/action/detector.py").read_text(encoding="utf-8")
    for forbidden in ("get_llm", "llm_factory", "chains.", "ChatOpenAI", "langchain"):
        assert forbidden not in source
