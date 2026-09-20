"""feishu_dedupe_ledger 仓储：跨进程去重的原子性、TTL 语义与清理（FEISHU-010）。"""

from datetime import datetime, timedelta

import pytest

from app.repositories import feishu_dedupe_ledger_repository

BASE = datetime(2026, 9, 20, 10, 0, 0)
TTL = 600
NOT_EXPIRED = BASE - timedelta(seconds=TTL)


def test_claim_first_true_then_false():
    assert feishu_dedupe_ledger_repository.claim("evt-1", BASE, NOT_EXPIRED) is True
    assert feishu_dedupe_ledger_repository.claim("evt-1", BASE, NOT_EXPIRED) is False
    assert feishu_dedupe_ledger_repository.claim("evt-2", BASE, NOT_EXPIRED) is True


def test_claim_is_visible_to_other_processes():
    """核心价值：判定不再依赖进程内状态。

    模拟「另一个实例已经处理过该事件」——本地内存表为空，但库里已有该 event_id。
    """
    assert feishu_dedupe_ledger_repository.claim("evt-cross", BASE, NOT_EXPIRED) is True
    assert feishu_dedupe_ledger_repository.exists("evt-cross") is True
    assert feishu_dedupe_ledger_repository.claim("evt-cross", BASE, NOT_EXPIRED) is False


def test_claim_after_ttl_expiry_is_accepted_again():
    """TTL 语义与进程内表一致：过期即可重新受理（主键约束本身不知道过期）。"""
    stored = BASE - timedelta(seconds=TTL + 1)
    assert feishu_dedupe_ledger_repository.claim("evt-ttl", stored, stored - timedelta(seconds=TTL)) is True
    cutoff = BASE - timedelta(seconds=TTL)
    assert feishu_dedupe_ledger_repository.claim("evt-ttl", BASE, cutoff) is True
    assert feishu_dedupe_ledger_repository.claim("evt-ttl", BASE, cutoff) is False


def test_claim_within_ttl_still_duplicate():
    assert feishu_dedupe_ledger_repository.claim("evt-live", BASE, NOT_EXPIRED) is True
    later = BASE + timedelta(seconds=599)
    assert feishu_dedupe_ledger_repository.claim("evt-live", later, later - timedelta(seconds=TTL)) is False


def test_purge_before_removes_only_expired():
    feishu_dedupe_ledger_repository.claim("evt-old", BASE - timedelta(seconds=601), NOT_EXPIRED)
    feishu_dedupe_ledger_repository.claim("evt-fresh", BASE, NOT_EXPIRED)
    removed = feishu_dedupe_ledger_repository.purge_before(BASE - timedelta(seconds=600))
    assert removed == 1
    assert feishu_dedupe_ledger_repository.exists("evt-old") is False
    assert feishu_dedupe_ledger_repository.exists("evt-fresh") is True


def test_purge_before_noop_when_nothing_expired():
    feishu_dedupe_ledger_repository.claim("evt-keep", BASE, NOT_EXPIRED)
    assert feishu_dedupe_ledger_repository.purge_before(BASE - timedelta(seconds=1)) == 0
    assert feishu_dedupe_ledger_repository.exists("evt-keep") is True


def test_exists_false_for_unknown_event():
    assert feishu_dedupe_ledger_repository.exists("evt-never-seen") is False


@pytest.mark.parametrize("event_id", ["", "evt-with-dash", "事件-中文"])
def test_claim_accepts_arbitrary_event_id(event_id):
    assert feishu_dedupe_ledger_repository.claim(event_id, BASE, NOT_EXPIRED) is True
    assert feishu_dedupe_ledger_repository.claim(event_id, BASE, NOT_EXPIRED) is False
