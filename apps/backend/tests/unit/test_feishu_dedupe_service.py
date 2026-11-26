"""持久化去重服务：fail-open 语义、TTL 截止点与摊还清理（FEISHU-010）。"""

import logging
from datetime import timedelta

import pytest

from app.repositories import feishu_dedupe_ledger_repository
from app.services.delivery import dedupe as feishu_dedupe_service


@pytest.fixture(autouse=True)
def _reset_service_state():
    feishu_dedupe_service.reset_dedupe_service_state()
    yield
    feishu_dedupe_service.reset_dedupe_service_state()


def test_claim_first_true_then_false(override_settings):
    override_settings(feishu_dedupe_ttl_seconds=600)
    assert feishu_dedupe_service.claim("evt-1") is True
    assert feishu_dedupe_service.claim("evt-1") is False


def test_claim_passes_ttl_cutoff_to_repository(override_settings, monkeypatch):
    """服务负责把 TTL 折算成「过期截止点」交给仓储；仓储不读配置。"""
    override_settings(feishu_dedupe_ttl_seconds=600)
    seen = {}

    def _record(event_id, received_at, expired_before):
        seen["event_id"] = event_id
        seen["ttl"] = received_at - expired_before
        return True

    monkeypatch.setattr(feishu_dedupe_ledger_repository, "claim", _record)
    assert feishu_dedupe_service.claim("evt-cutoff") is True
    assert seen["event_id"] == "evt-cutoff"
    assert seen["ttl"] == timedelta(seconds=600)


def test_claim_fail_open_when_store_unavailable(override_settings, monkeypatch, caplog):
    """存储不可用时必须放行：fail-closed 会直接丢掉用户消息。"""
    override_settings(feishu_dedupe_ttl_seconds=600)

    def _boom(event_id, received_at, expired_before):
        raise RuntimeError("db down")

    monkeypatch.setattr(feishu_dedupe_ledger_repository, "claim", _boom)
    with caplog.at_level(logging.WARNING, logger="app.services.delivery.dedupe"):
        assert feishu_dedupe_service.claim("evt-boom") is True
    assert any("fail-open" in record.getMessage() for record in caplog.records)


def test_amortized_purge_runs_once_per_window(override_settings, monkeypatch):
    override_settings(feishu_dedupe_ttl_seconds=600)
    calls = []

    def _purge(cutoff):
        calls.append(cutoff)
        return 0

    monkeypatch.setattr(feishu_dedupe_ledger_repository, "purge_before", _purge)
    for index in range(feishu_dedupe_service.PURGE_EVERY):
        assert feishu_dedupe_service.claim(f"evt-purge-{index}") is True
    assert len(calls) == 1


def test_duplicate_claim_does_not_trigger_purge(override_settings, monkeypatch):
    override_settings(feishu_dedupe_ttl_seconds=600)
    calls = []
    monkeypatch.setattr(
        feishu_dedupe_ledger_repository, "purge_before", lambda cutoff: calls.append(cutoff) or 0
    )
    feishu_dedupe_service.claim("evt-dup")
    for _ in range(feishu_dedupe_service.PURGE_EVERY * 2):
        feishu_dedupe_service.claim("evt-dup")
    assert calls == []


def test_purge_failure_does_not_affect_claim(override_settings, monkeypatch, caplog):
    override_settings(feishu_dedupe_ttl_seconds=600)

    def _boom(cutoff):
        raise RuntimeError("purge down")

    monkeypatch.setattr(feishu_dedupe_ledger_repository, "purge_before", _boom)
    with caplog.at_level(logging.WARNING, logger="app.services.delivery.dedupe"):
        for index in range(feishu_dedupe_service.PURGE_EVERY):
            assert feishu_dedupe_service.claim(f"evt-pf-{index}") is True
    assert any("purge failed" in record.getMessage() for record in caplog.records)
