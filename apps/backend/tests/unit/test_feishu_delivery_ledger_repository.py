"""feishu_deliveries 仓储：跨进程出站幂等的原子性、回滚与 TTL（FEISHU-011）。"""

from datetime import datetime, timedelta

import pytest

from app.repositories import feishu_delivery_ledger_repository as repo

BASE = datetime(2026, 9, 20, 10, 0, 0)
TTL = 600
NOT_EXPIRED = BASE - timedelta(seconds=TTL)


def test_claim_first_true_then_false():
    assert repo.claim("reply:om_1:0", BASE, NOT_EXPIRED) is True
    assert repo.claim("reply:om_1:0", BASE, NOT_EXPIRED) is False
    assert repo.claim("reply:om_1:1", BASE, NOT_EXPIRED) is True


def test_claim_is_visible_to_other_processes():
    """核心价值：占位不再依赖进程内状态（模拟另一实例已投递过）。"""
    assert repo.claim("reply:om_cross:0", BASE, NOT_EXPIRED) is True
    assert repo.exists("reply:om_cross:0") is True
    assert repo.claim("reply:om_cross:0", BASE, NOT_EXPIRED) is False


def test_release_allows_retry():
    """发送失败回滚占位后，重试必须能再次投递（否则回复永久丢失）。"""
    assert repo.claim("reply:om_retry:0", BASE, NOT_EXPIRED) is True
    repo.release("reply:om_retry:0")
    assert repo.exists("reply:om_retry:0") is False
    assert repo.claim("reply:om_retry:0", BASE, NOT_EXPIRED) is True


def test_release_unknown_key_is_noop():
    repo.release("reply:never:0")
    assert repo.exists("reply:never:0") is False


def test_claim_after_ttl_expiry_is_accepted_again():
    stored = BASE - timedelta(seconds=TTL + 1)
    assert repo.claim("reply:om_ttl:0", stored, stored - timedelta(seconds=TTL)) is True
    cutoff = BASE - timedelta(seconds=TTL)
    assert repo.claim("reply:om_ttl:0", BASE, cutoff) is True
    assert repo.claim("reply:om_ttl:0", BASE, cutoff) is False


def test_claim_within_ttl_still_duplicate():
    assert repo.claim("reply:om_live:0", BASE, NOT_EXPIRED) is True
    later = BASE + timedelta(seconds=599)
    assert repo.claim("reply:om_live:0", later, later - timedelta(seconds=TTL)) is False


def test_purge_before_removes_only_expired():
    repo.claim("reply:om_old:0", BASE - timedelta(seconds=601), NOT_EXPIRED)
    repo.claim("reply:om_fresh:0", BASE, NOT_EXPIRED)
    assert repo.purge_before(BASE - timedelta(seconds=600)) == 1
    assert repo.exists("reply:om_old:0") is False
    assert repo.exists("reply:om_fresh:0") is True


def test_segments_are_independent():
    """分段幂等键互相独立：第 2 段失败不应让第 1 段重发。"""
    for index in range(3):
        assert repo.claim(f"reply:om_seg:{index}", BASE, NOT_EXPIRED) is True
    repo.release("reply:om_seg:1")
    assert repo.exists("reply:om_seg:0") is True
    assert repo.exists("reply:om_seg:1") is False
    assert repo.exists("reply:om_seg:2") is True


@pytest.mark.parametrize("key", ["", "proactive:feishu:ou_x:key-1:0", "键-中文"])
def test_claim_accepts_arbitrary_key(key):
    assert repo.claim(key, BASE, NOT_EXPIRED) is True
    assert repo.claim(key, BASE, NOT_EXPIRED) is False
