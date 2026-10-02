"""对话自动记账落库：明细（note）与类目（category_id）不能丢。

回归背景：用户说「记账早餐20元，购买了2个鸡蛋」，库里只写 amount/direction/source，
账单页只能把这一笔显示成「一笔账」、分类条显示「未分类」——
明细在 detector 侧丢失，类目在能力链路上无人归一（PLA-009 D2 禁能力层解析自由文本）。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.application.action_engine import run_action_planning
from app.repositories import ledger_repository
from app.services.action.detector import detect_action_intent
from app.services.ledger import ensure_user_bootstrap

NOW = datetime(2026, 10, 2, 10, 51, 54)
USER = "ledger-conv-user"


@pytest.fixture()
def bootstrapped(override_settings, db_session_factory):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    return USER


def _category_id(user_id: str, name: str) -> str | None:
    rows = ledger_repository.list_categories(user_id, kind="expense")
    return next((row.id for row in rows if row.name == name), None)


async def test_conversation_entry_keeps_detail_and_category(bootstrapped):
    intent = detect_action_intent("记账早餐20元，购买了2个鸡蛋", now=NOW)
    assert intent is not None
    assert intent.action_type == "record_ledger_entry"
    assert intent.params.get("note") == "早餐，购买了2个鸡蛋"

    record = await run_action_planning(USER, intent, session_id="s1")

    assert record is not None
    assert record.status == "succeeded", record.gate_reason
    entry = ledger_repository.list_entries(USER)[0]
    assert entry.amount_minor == 2000
    assert entry.direction == "expense"
    assert entry.source == "conversation"
    assert entry.note == "早餐，购买了2个鸡蛋"
    assert entry.category_id == _category_id(USER, "早餐")


async def test_same_amount_different_detail_stays_two_entries(bootstrapped):
    """幂等键（同时是 entry_id）不能只按金额+方向：同额不同明细必须落成两笔。"""
    for text in ("记账早餐20元", "记账午餐20元"):
        intent = detect_action_intent(text, now=NOW)
        assert intent is not None
        record = await run_action_planning(USER, intent, session_id="s3")
        assert record is not None
        assert record.status == "succeeded", (text, record.gate_reason)

    entries = ledger_repository.list_entries(USER)
    assert len(entries) == 2
    assert {entry.note for entry in entries} == {"早餐", "午餐"}

    # 同一条消息重发仍是幂等（不新增第三笔）
    repeat = await run_action_planning(
        USER, detect_action_intent("记账早餐20元", now=NOW), session_id="s4"
    )
    assert repeat is not None
    assert repeat.gate_reason == "duplicate"
    assert ledger_repository.count_entries(USER) == 2


async def test_conversation_entry_without_detail_stays_uncategorized(bootstrapped):
    """只有金额没有明细时不猜类目（诚实留空，等价于账单页的「未分类」）。"""
    intent = detect_action_intent("记账20元", now=NOW)
    assert intent is not None
    assert "note" not in intent.params

    record = await run_action_planning(USER, intent, session_id="s2")

    assert record is not None
    assert record.status == "succeeded", record.gate_reason
    entry = ledger_repository.list_entries(USER)[0]
    assert entry.note is None
    assert entry.category_id is None
