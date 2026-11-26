"""PLA-010 澄清与待确认用例。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.models.ledger import LedgerExtraction
from app.repositories import ledger_repository, scene_state_repository
from app.services.ledger.confirmation import (
    REASON_AMOUNT_OVER_THRESHOLD,
    REASON_CATEGORY_AMBIGUOUS,
    REASON_LOW_CONFIDENCE,
    REASON_MISSING_AMOUNT,
    pending_key,
    request_to_mapping,
    request_from_mapping,
    should_confirm,
)
from app.services.ledger.pending import (
    clear_pending,
    expire_if_due,
    load_pending,
    register_pending,
)
from app.services.ledger.service import ensure_user_bootstrap

NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "confirm-user"
SESSION = "sess-confirm"


@pytest.fixture()
def settings(override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    return get_settings()


def _extraction(**overrides) -> LedgerExtraction:
    base = {
        "is_ledger_intent": True,
        "amount_value": "20",
        "direction": "expense",
        "confidence": 0.9,
        "missing_fields": (),
    }
    base.update(overrides)
    return LedgerExtraction(**base)


def test_missing_amount_triggers_confirm(settings):
    request = should_confirm(
        _extraction(amount_value=None, missing_fields=("amount_value",)),
        settings=settings,
        now=NOW,
        source_ref="m1",
    )
    assert request is not None
    assert request.reason == REASON_MISSING_AMOUNT


def test_non_ledger_message_never_triggers_confirm(settings):
    """回归：抽取器说「这不是一笔账」时不得回问。

    实测形态：用户说「明天早上8点，叫我起床签到」，抽取结果是
    `is_ledger_intent=false` + 其余字段全空，却仍被登记成「这笔记多少？」——
    原因是本函数此前只看 amount 是否为空，没看 `is_ledger_intent`
    （提示词反例「今天天气不错」正是用该字段表达非记账）。
    """
    extraction = LedgerExtraction(is_ledger_intent=False)
    assert (
        should_confirm(extraction, settings=settings, now=NOW, source_ref="m-non-ledger")
        is None
    )


def test_low_confidence_triggers_confirm(settings):
    request = should_confirm(
        _extraction(confidence=0.2),
        settings=settings,
        now=NOW,
        source_ref="m2",
    )
    assert request is not None
    assert request.reason == REASON_LOW_CONFIDENCE
    assert request.candidates


def test_amount_over_threshold_triggers_confirm(settings):
    request = should_confirm(
        _extraction(amount_value="320"),
        settings=settings,
        now=NOW,
        source_ref="m3",
    )
    assert request is not None
    assert request.reason == REASON_AMOUNT_OVER_THRESHOLD
    assert request.amount_minor == 32000


def test_amount_below_threshold_no_confirm(settings):
    assert (
        should_confirm(
            _extraction(amount_value="20"),
            settings=settings,
            now=NOW,
            source_ref="m4",
        )
        is None
    )


def test_category_fallback_triggers_confirm(settings):
    request = should_confirm(
        _extraction(category_hint="奇怪的东西"),
        settings=settings,
        now=NOW,
        source_ref="m5",
        category_fallback=True,
        top_categories=("餐饮", "交通", "购物"),
    )
    assert request is not None
    assert request.reason == REASON_CATEGORY_AMBIGUOUS
    assert len(request.candidates) == 3


def test_single_confirm_per_source_ref(settings):
    extraction = _extraction(amount_value=None, missing_fields=("amount_value",))
    request = should_confirm(extraction, settings=settings, now=NOW, source_ref="same-ref")
    assert request is not None
    first = register_pending(
        user_id=USER,
        session_id=SESSION,
        request=request,
        extraction=extraction,
        now=NOW,
    )
    assert first is not None
    second = register_pending(
        user_id=USER,
        session_id=SESSION,
        request=request,
        extraction=extraction,
        now=NOW,
    )
    assert second is None


def test_timeout_produces_no_entry(settings):
    extraction = _extraction(amount_value=None, missing_fields=("amount_value",))
    request = should_confirm(extraction, settings=settings, now=NOW, source_ref="timeout-ref")
    assert request is not None
    register_pending(
        user_id=USER,
        session_id=SESSION,
        request=request,
        extraction=extraction,
        now=NOW,
    )
    assert ledger_repository.count_entries(USER) == 0
    expired = expire_if_due(SESSION, now=request.expires_at + timedelta(minutes=1))
    assert expired is True
    assert load_pending(SESSION) is None
    assert ledger_repository.count_entries(USER) == 0


def test_pending_uses_existing_mechanisms(settings):
    extraction = _extraction(amount_value=None, missing_fields=("amount_value",))
    request = should_confirm(extraction, settings=settings, now=NOW, source_ref="mech")
    record = register_pending(
        user_id=USER,
        session_id=SESSION,
        request=request,
        extraction=extraction,
        now=NOW,
    )
    assert record is not None
    state = scene_state_repository.get_scene_state(SESSION)
    assert state.pending_action is not None
    assert state.pending_action.action.startswith("ledger_confirm:")
    from app.repositories import action_repository

    schedule = action_repository.get_schedule(record.id)
    assert schedule is not None
    assert schedule.when_type == "delay"


def test_reply_reuses_extraction_chain(monkeypatch, settings):
    calls = []

    def fake_extract(message, **kwargs):
        calls.append(message)
        return _extraction(amount_value="30", confidence=0.95)

    monkeypatch.setattr(
        "app.chains.ledger_extraction_chain.extract_ledger", fake_extract
    )
    from app.chains.ledger_extraction_chain import extract_ledger

    result = extract_ledger("30块", message_id="x", now=NOW)
    assert calls == ["30块"]
    assert result.amount_value == "30"


def test_question_rendered_from_template(settings):
    from app.prompts.ledger_clarify import TEMPLATES, render_clarify_question

    assert render_clarify_question("missing_amount") == TEMPLATES["missing_amount"]
    text = render_clarify_question("low_confidence", amount_minor=2000)
    assert "20" in text
    assert "系统" not in text


def test_confirm_module_no_new_tables():
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    assert not (backend / "migrations/versions/0055").exists()
    source = (backend / "app/services/ledger/confirmation.py").read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source.upper()
    assert "*_enabled" not in source


def test_pending_key_roundtrip():
    key = pending_key("src", REASON_MISSING_AMOUNT)
    request = should_confirm(
        _extraction(amount_value=None, missing_fields=("amount_value",)),
        now=NOW,
        source_ref="src",
    )
    assert request.pending_key == key
    restored = request_from_mapping(request_to_mapping(request))
    assert restored.pending_key == request.pending_key
    assert restored.reason == request.reason
