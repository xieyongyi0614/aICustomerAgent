from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services.governance import (
    DomainHandlers,
    FinancialDetailInPrompt,
    ProvenanceRef,
    assert_no_financial_detail,
    delete_user_data,
    export_user_data,
    record_provenance,
    register_domain,
    registered_domains,
    resolve_provenance,
)
from app.services.governance import core as governance_core

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_registry():
    governance_core.reset_registry()
    governance_core.reset_provenance_store()
    yield
    governance_core.reset_registry()
    governance_core.reset_provenance_store()


def _handlers(name: str, *, export=None, delete=None, provenance=None):
    store = {"rows": []}

    def _export(user_id: str):
        return {"items": list(store["rows"]), "user_id": user_id}

    def _delete(user_id: str) -> int:
        count = len(store["rows"])
        store["rows"].clear()
        return count

    return DomainHandlers(
        name=name,
        export=export or _export,
        delete=delete or _delete,
        provenance=provenance,
    ), store


def test_register_domain_idempotent():
    handlers, _ = _handlers("ledger")
    register_domain(handlers)
    register_domain(handlers)
    assert registered_domains() == ("ledger",)


def test_export_is_read_only():
    handlers, store = _handlers("memories")
    store["rows"] = [{"id": 1}]
    register_domain(handlers)
    before = list(store["rows"])
    bundle = export_user_data("u1")
    assert bundle.domains["memories"]["items"] == before
    assert store["rows"] == before


def test_export_aggregates_all_registered_domains():
    h1, s1 = _handlers("a")
    h2, s2 = _handlers("b")
    s1["rows"] = [1]
    s2["rows"] = [2, 3]
    register_domain(h1)
    register_domain(h2)
    bundle = export_user_data("u1")
    assert set(bundle.domains) == {"a", "b"}
    assert bundle.domains["a"]["items"] == [1]
    assert bundle.domains["b"]["items"] == [2, 3]


def test_export_is_repeatable():
    handlers, store = _handlers("a")
    store["rows"] = [1, 2]
    register_domain(handlers)
    first = export_user_data("u1")
    second = export_user_data("u1")
    assert first.domains == second.domains
    assert first.user_id == second.user_id


def test_delete_returns_per_domain_counts():
    h1, s1 = _handlers("a")
    h2, s2 = _handlers("b")
    s1["rows"] = [1, 2]
    s2["rows"] = [3]
    register_domain(h1)
    register_domain(h2)
    report = delete_user_data("u1")
    assert report.per_domain == {"a": 2, "b": 1}
    assert report.total == 3
    assert report.failed_domains == ()
    assert s1["rows"] == [] and s2["rows"] == []


def test_delete_reports_failed_domains():
    def _boom(user_id: str) -> int:
        raise RuntimeError("db down")

    ok, store = _handlers("ok")
    bad, _ = _handlers("bad", delete=_boom)
    store["rows"] = [1]
    register_domain(ok)
    register_domain(bad)
    report = delete_user_data("u1")
    assert report.failed_domains == ("bad",)
    assert report.per_domain == {"ok": 1}
    assert store["rows"] == []


def test_delete_goes_through_repositories():
    source = (BACKEND / "app" / "services" / "governance" / "core.py").read_text(
        encoding="utf-8"
    )
    assert "Base.metadata" not in source
    assert "drop_all" not in source
    assert "text(" not in source
    assert "handlers.delete" in source


def test_provenance_roundtrip():
    ref = ProvenanceRef(
        domain="ledger",
        record_id="e1",
        source="conversation",
        source_ref="msg-9",
    )
    record_provenance(ref)
    found = resolve_provenance("ledger", "e1")
    assert found == ref
    assert found.source == "conversation"
    assert found.source_ref == "msg-9"


def test_prompt_guard_detects_amount():
    for text in ("花了20块", "￥20", "20元", "消费 35.5 元"):
        with pytest.raises(FinancialDetailInPrompt):
            assert_no_financial_detail(text)


def test_prompt_guard_allows_aggregate():
    assert (
        assert_no_financial_detail("本月餐饮合计 320 元")
        == "本月餐饮合计 320 元"
    )


def test_governance_module_has_no_forbidden_imports():
    for path in (BACKEND / "app" / "services" / "governance").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for banned in ("app.chains", "app.prompts", "app.channels", "app.channels.feishu"):
            assert not any(
                name == banned or name.startswith(banned + ".") for name in imported
            ), path.name
