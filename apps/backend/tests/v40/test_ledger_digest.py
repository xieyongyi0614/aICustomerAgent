"""PLA-011 账务节律投递用例。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.channels.base import ChannelErrorKind, SendResult
from app.core.settings import get_settings
from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository, proactive_repository
from app.services.ledger import digest
from app.services.ledger.format import format_minor
from app.services.ledger.query import Period, summary
from app.services.ledger.service import ensure_user_bootstrap, record_entry

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 21, 35, 0)  # 周二 21:35
USER = "digest-user"


@pytest.fixture()
def settings(override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    account = ledger_repository.list_accounts(USER)[0]
    record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=account.id,
            amount_minor=2500,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            idempotency_key="digest-1",
        ),
        idempotency_key="digest-1",
        now=NOW,
    )
    return get_settings()


def test_daily_digest_numbers_match_summary(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    assert payload is not None
    data = summary(
        USER,
        period=Period.custom(
            NOW.replace(hour=0, minute=0, second=0, microsecond=0),
            NOW.replace(hour=23, minute=59, second=59, microsecond=999999),
            label="day",
        ),
        now=NOW,
    )
    assert format_minor(data.expense_minor) in payload.body
    assert str(data.entry_count) in payload.body


def test_weekly_digest_numbers_match_summary(settings):
    payload = digest.build_weekly_digest(USER, now=NOW, settings=settings)
    assert payload is not None
    data = summary(USER, period=Period.week(NOW), now=NOW)
    assert format_minor(data.expense_minor) in payload.body


def test_zero_entries_returns_none(override_settings):
    override_settings()
    ensure_user_bootstrap("empty-user", now=NOW)
    assert digest.build_daily_digest("empty-user", now=NOW) is None


def test_should_send_false_before_send_time(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    early = NOW.replace(hour=20, minute=0)
    assert digest.should_send(payload, now=early, settings=settings) is False


def test_should_send_true_at_send_time(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    assert digest.should_send(payload, now=NOW, settings=settings) is True


def test_should_send_false_in_quiet_hours(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    quiet = NOW.replace(hour=23, minute=30)
    assert digest.should_send(payload, now=quiet, settings=settings) is False


def test_should_send_false_when_dedupe_hit(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    digest.deliver_for_user(user_id=USER, payload=payload, now=NOW)
    assert digest.should_send(payload, now=NOW, settings=settings) is False


def test_dedupe_key_contains_period_start(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    assert payload.dedupe_key.startswith("ledger_digest:daily:")
    assert payload.period.since.isoformat() in payload.dedupe_key
    again = digest.build_daily_digest(USER, now=NOW + timedelta(minutes=1), settings=settings)
    assert again.dedupe_key == payload.dedupe_key


def test_digest_module_has_no_llm_import():
    source = (BACKEND / "app/services/ledger/digest.py").read_text(encoding="utf-8")
    for forbidden in ("chains", "llm_factory", "ChatOpenAI", "langchain", "get_llm"):
        assert forbidden not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "llm" not in alias.name.lower()
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "llm" not in node.module.lower()
            assert "chain" not in node.module.lower()


def test_template_uses_placeholders_only():
    from app.prompts import ledger_clarify

    # digest 文案由 digest.py 字符串拼接 format_minor；模板侧澄清问句无硬编码金额
    for text in ledger_clarify.TEMPLATES.values():
        assert not any(ch.isdigit() for ch in text.replace("{amount}", ""))


def test_deliver_failure_does_not_raise(monkeypatch, settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)

    class Boom:
        async def send(self, *args, **kwargs):
            raise RuntimeError("boom")

    from app.services import proactive_delivery

    proactive_delivery.register_proactive_outbound(
        proactive_delivery.ProactiveOutbound(channel="web", send=Boom().send)
    )
    try:
        result = digest.deliver_for_user(user_id=USER, payload=payload, now=NOW)
        assert result.ok is False
    finally:
        proactive_delivery.reset_proactive_outbound()


def test_no_inferential_wording(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    for word in digest.INFERENTIAL_WORDS:
        assert word not in payload.body


def test_maintenance_step_appended_only():
    source = (BACKEND / "app/application/life_loop.py").read_text(encoding="utf-8")
    assert '_mark_maintenance("ledger_digest")' in source
    assert '_maintenance_due("ledger_digest"' in source
    # 既有六步 kind 不变（loop_runs.kind 零迁移）
    for kind in (
        "world_maintenance",
        "world_simulation",
        "action_retry",
        "action_schedule",
        "outbox_consume",
        "trigger_reconcile",
    ):
        assert f'_record_maintenance_run(\n            "{kind}"' in source or (
            f'"{kind}"' in source
        )


def test_no_new_resident_loop():
    source = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "ledger_digest" not in source
    assert "run_ledger" not in source


def test_digest_idempotent_across_ticks(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    first = digest.deliver_for_user(user_id=USER, payload=payload, now=NOW)
    second = digest.deliver_for_user(user_id=USER, payload=payload, now=NOW)
    assert first.ok is True
    assert second.ok is False
    rows = proactive_repository.list_since(NOW - timedelta(minutes=1))
    assert sum(1 for row in rows if row.dedupe_key == payload.dedupe_key) == 1


def test_digest_records_proactive_action(settings):
    payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
    digest.deliver_for_user(user_id=USER, payload=payload, now=NOW)
    rows = proactive_repository.list_since(NOW - timedelta(minutes=1))
    assert any(row.dedupe_key == payload.dedupe_key for row in rows)
    assert payload.dedupe_key.startswith("ledger_digest:daily:")


def test_digest_delivered_via_outbound_gateway(monkeypatch, settings):
    from app.services import proactive_delivery

    calls = []

    async def send(user_id, text, dedupe_key):
        calls.append((user_id, text, dedupe_key))
        return SendResult(ok=True, external_message_id="om-1")

    proactive_delivery.register_proactive_outbound(
        proactive_delivery.ProactiveOutbound(channel="web", send=send)
    )
    try:
        payload = digest.build_daily_digest(USER, now=NOW, settings=settings)
        result = digest.deliver_for_user(user_id=USER, payload=payload, now=NOW)
        assert result.ok is True
        assert calls and calls[0][2] == payload.dedupe_key
    finally:
        proactive_delivery.reset_proactive_outbound()
