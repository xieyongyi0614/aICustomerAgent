"""PLA-014 消费洞察与零金额边界用例。"""

from __future__ import annotations

import ast
import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from app.core.db import MemoryCandidateRow
from app.models.ledger import LedgerEntryDraft
from app.models.memory import MemoryType
from app.repositories import ledger_repository
from app.services.ledger import insight, memory_bridge
from app.services.ledger.service import ensure_user_bootstrap, record_entry
from app.services.memory import ingest as memory_ingest

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 23, 10, 0)
USER = "insight-user"


@pytest.fixture()
def setup(override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    account = ledger_repository.list_accounts(USER)[0]
    for i, (amount, hour) in enumerate(((5000, 23), (4000, 23), (3000, 12), (2000, 23))):
        record_entry(
            LedgerEntryDraft(
                user_id=USER,
                account_id=account.id,
                amount_minor=amount,
                direction="expense",
                occurred_at=NOW.replace(hour=hour, minute=i),
                source="manual",
                idempotency_key=f"ins-{i}",
            ),
            idempotency_key=f"ins-{i}",
            now=NOW,
        )
    return account


def test_features_have_no_amount_field():
    names = {field.name for field in dataclasses.fields(insight.SpendingFeatures)}
    banned = ("amount", "total", "min", "max", "money")
    for name in names:
        for token in banned:
            assert token not in name.lower()
    source = (BACKEND / "app/services/ledger/insight.py").read_text(encoding="utf-8")
    class_src = source.split("class SpendingFeatures")[1].split("def ")[0]
    assert "amount" not in class_src.lower()


def test_features_ratios_computed_correctly(setup):
    features = insight.project_features(USER, now=NOW)
    assert features is not None
    assert 0.0 <= features.late_night_ratio <= 1.0
    assert 0.0 <= features.unclassified_ratio <= 1.0
    assert features.entry_count == 4
    assert abs(sum(features.top_category_share.values()) - 1.0) < 1e-6


def test_late_night_ratio_uses_local_time(setup):
    features = insight.project_features(USER, now=NOW)
    # 4 笔中 3 笔在 23 点
    assert features.late_night_ratio == 0.75


def test_unclassified_ratio_matches_summary(setup):
    features = insight.project_features(USER, now=NOW)
    assert features.unclassified_ratio == 1.0


def test_insight_text_never_contains_amount():
    outcome = memory_bridge.filter_and_ingest(
        user_id=USER,
        insight_id="i1",
        insight_type="behavior_pattern",
        statement="本月花了 320 元在外卖",
        now=NOW,
    )
    assert outcome.accepted is False
    assert outcome.reason == "financial_detail"


def test_only_behavior_pattern_ingested():
    outcome = memory_bridge.filter_and_ingest(
        user_id=USER,
        insight_id="i2",
        insight_type="belief",
        statement="用户喜欢外卖",
        now=NOW,
    )
    assert outcome.accepted is False
    assert outcome.reason.startswith("type_not_allowed")


def test_candidate_text_passes_amount_guard(monkeypatch):
    calls = []
    real = memory_bridge.assert_no_financial_detail

    def spy(text):
        calls.append(text)
        return real(text)

    monkeypatch.setattr(memory_bridge, "assert_no_financial_detail", spy)
    memory_bridge.filter_and_ingest(
        user_id=USER,
        insight_id="i3",
        insight_type="behavior_pattern",
        statement="消费高度集中在餐饮",
        now=NOW,
    )
    assert calls == ["消费高度集中在餐饮"]


def test_ingest_goes_through_memory_entry(monkeypatch):
    calls = []

    def spy(**kwargs):
        calls.append(kwargs)
        class Row:
            id = "cand-1"

        return Row()

    monkeypatch.setattr(memory_bridge.memory_ingest, "_create_candidate", spy)
    memory_bridge.filter_and_ingest(
        user_id=USER,
        insight_id="i4",
        insight_type="behavior_pattern",
        statement="夜间消费占比偏高",
        now=NOW,
    )
    assert calls and calls[0]["proposed_type"] == "behavior_pattern"


def test_ingest_is_idempotent(setup):
    first = memory_bridge.filter_and_ingest(
        user_id=USER,
        insight_id="i5",
        insight_type="behavior_pattern",
        statement="夜间消费占比偏高",
        now=NOW,
    )
    second = memory_bridge.filter_and_ingest(
        user_id=USER,
        insight_id="i5",
        insight_type="behavior_pattern",
        statement="夜间消费占比偏高",
        now=NOW,
    )
    assert first.accepted and second.accepted
    assert first.candidate_id == second.candidate_id
    with memory_ingest.SessionLocal() as session:
        rows = (
            session.query(MemoryCandidateRow)
            .filter(MemoryCandidateRow.user_id == USER)
            .all()
        )
        assert len([r for r in rows if r.source_id == "i5"]) == 1


def test_memories_contain_zero_amount_digits(setup):
    features = insight.project_features(USER, now=NOW)
    statements = insight.derive_pattern_statements(features)
    memory_bridge.ingest_patterns(user_id=USER, statements=statements, now=NOW)
    with memory_ingest.SessionLocal() as session:
        rows = (
            session.query(MemoryCandidateRow)
            .filter(MemoryCandidateRow.user_id == USER)
            .all()
        )
        for row in rows:
            assert "元" not in (row.content or "")
            assert not any(ch.isdigit() for ch in (row.content or "").replace("%", ""))


def test_insight_does_not_write_personality_state():
    source = (BACKEND / "app/services/ledger/insight.py").read_text(encoding="utf-8")
    source_bridge = (BACKEND / "app/services/ledger/memory_bridge.py").read_text(
        encoding="utf-8"
    )
    assert "personality_state" not in source
    assert "personality_state" not in source_bridge


def test_no_new_memory_type():
    assert "behavior_pattern" in MemoryType.__args__
    assert len(MemoryType.__args__) == 9


def test_no_advice_language(setup):
    features = insight.project_features(USER, now=NOW)
    for text in insight.derive_pattern_statements(features):
        for marker in ("建议", "应该", "最好", "推荐"):
            assert marker not in text


def test_reflection_gates_unchanged():
    for name in ("reflector.py", "evidence.py", "evaluation.py"):
        path = BACKEND / "app/services/reflection" / name
        if path.exists():
            source = path.read_text(encoding="utf-8")
            assert "SpendingFeatures" not in source
            assert "ledger/insight" not in source


def test_memory_untouched():
    source = (BACKEND / "app/services/memory/ingest.py").read_text(encoding="utf-8")
    assert "SpendingFeatures" not in source
    assert "ledger.insight" not in source


def test_hooked_into_existing_reflection_path():
    source = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "ledger_insight" not in source
    assert "run_ledger_insight" not in source
    bridge = (BACKEND / "app/services/ledger/memory_bridge.py").read_text(encoding="utf-8")
    assert "memory_ingest._create_candidate" in bridge


def test_audit_records_filtered_insights():
    outcome = memory_bridge.filter_and_ingest(
        user_id=USER,
        insight_id="i-audit",
        insight_type="belief",
        statement="用户喜欢咖啡",
        now=NOW,
    )
    assert outcome.accepted is False
    assert outcome.reason
