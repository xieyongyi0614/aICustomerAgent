"""对话记账的单写面：同一条消息不得既直接入账、又被待确认确认一次。

回归背景（线上实测，2026-10-06）：用户说「记账吃中午饭240元，吃的牛杂」——
词表链路（第 12 步）先无条件入了账，LLM 抽取链路（第 7 步）又按 100 元阈值登记了
待确认，用户一点确认就落第二笔（note 只剩「240元」、类目落到回退的「其他」）。
"""

from __future__ import annotations

from datetime import datetime

from app.application.post_process import (
    PostProcessContext,
    _defer_to_ledger_pending,
    run_ledger_confirmation,
)
from app.models.action import ActionIntent
from app.models.ledger import LedgerExtraction
from app.repositories import ledger_repository
from app.services.action.detector import detect_action_intent
from app.services.ledger import pending as pending_service

NOW = datetime(2026, 10, 6, 16, 57, 24)
USER = "ledger-single-writer"
INPUT = "记账吃中午饭240元，吃的牛杂"


class _Trace:
    def __init__(self) -> None:
        self.steps: list[tuple[str, str, dict]] = []

    def record(self, name: str, _elapsed_ms: float, status: str, **extra) -> None:
        self.steps.append((name, status, extra))


def _context(trace=None) -> PostProcessContext:
    intent = detect_action_intent(INPUT, now=NOW)
    assert intent is not None and intent.action_type == "record_ledger_entry"
    return PostProcessContext(
        session_id="s-single-writer",
        user_id=USER,
        user_input=INPUT,
        ai_reply="好",
        state=None,
        analysis=None,
        action_intent=intent,
        trace=trace,
    )


def _extraction_240() -> LedgerExtraction:
    """LLM 抽取（实测形态）：金额对得上、超阈值；类目提示是单字「饭」。"""
    return LedgerExtraction(
        is_ledger_intent=True,
        amount_value="240",
        currency_hint="元",
        direction="expense",
        category_hint="饭",
        occurred_at_hint="中午",
        evidence_span="240元",
        confidence=0.95,
    )


def _category_id(user_id: str, name: str) -> str | None:
    rows = ledger_repository.list_categories(user_id, kind="expense")
    return next((row.id for row in rows if row.name == name), None)


async def test_threshold_utterance_defers_then_records_exactly_one_entry(
    override_settings, db_session_factory, monkeypatch
):
    override_settings()
    monkeypatch.setattr(
        "app.chains.ledger_extraction_chain.extract_ledger",
        lambda *_args, **_kwargs: _extraction_240(),
    )
    ctx = _context()

    await run_ledger_confirmation(ctx)

    assert ctx.ledger_pending_amount == 24000
    assert ledger_repository.count_entries(USER) == 0, "已登记待确认，确定性链路不得入账"
    items = pending_service.list_pending(USER).items
    assert len(items) == 1
    assert items[0].amount_minor == 24000
    assert items[0].category_hint == "午餐", "判断取词表链路的归一结果，不是 LLM 的单字提示"

    outcome = pending_service.confirm_pending(USER, items[0].pending_key, now=NOW)

    assert outcome.created is True
    entries = ledger_repository.list_entries(USER)
    assert len(entries) == 1, "确认后只能落一笔"
    assert entries[0].note == "吃中午饭，吃的牛杂"
    assert entries[0].category_id == _category_id(USER, "午餐")


async def test_non_ledger_message_never_registers_pending(
    override_settings, db_session_factory, monkeypatch
):
    """回归：非记账消息（提醒类）不得被登记成待确认账目。

    实测：用户说「明天早上8点，叫我起床签到」，账本页却出现「这笔记多少？」。
    """
    override_settings()
    monkeypatch.setattr(
        "app.chains.ledger_extraction_chain.extract_ledger",
        lambda *_args, **_kwargs: LedgerExtraction(is_ledger_intent=False),
    )
    user = "ledger-non-intent-user"
    ctx = PostProcessContext(
        session_id="s-reminder",
        user_id=user,
        user_input="明天早上8点，叫我起床签到",
        ai_reply="好",
        state=None,
        analysis=None,
        action_intent=detect_action_intent("明天早上8点，叫我起床签到", now=NOW),
        trace=None,
    )

    await run_ledger_confirmation(ctx)

    assert ctx.ledger_pending_amount is None
    assert pending_service.list_pending(user).items == ()


def test_defer_only_for_same_amount_ledger_intent(
    override_settings, db_session_factory
):
    override_settings()
    trace = _Trace()
    ctx = _context(trace)
    ctx.ledger_pending_amount = 24000
    intent = ctx.action_intent

    assert _defer_to_ledger_pending(ctx, intent) is True
    assert trace.steps[-1][1] == "deferred"

    other_amount = intent.model_copy(
        update={"params": {**intent.params, "amount_minor": 2000}}
    )
    assert _defer_to_ledger_pending(ctx, other_amount) is False

    non_ledger = ActionIntent(
        action_type="create_reminder",
        confidence="confident",
        params={"amount_minor": 24000},
    )
    assert _defer_to_ledger_pending(ctx, non_ledger) is False
