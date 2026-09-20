"""feishu_deliveries 仓储：跨进程出站幂等的原子性、回滚与 TTL（FEISHU-012）。"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.db import Base

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


@pytest.mark.asyncio
async def test_concurrent_claim_arbitrated_by_unique_constraint(tmp_path, monkeypatch):
    """跨连接并发占位：唯一约束必须让两者**只有一个**成功。

    这是幂等的核心保证。必须用**独立连接**（文件库 + NullPool）才复现得出来——
    conftest 的内存 SQLite 用 StaticPool 共享单连接，两个线程会在同一连接上交错，
    双双判为「首次」。
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ledger.db'}",
        poolclass=NullPool,
        connect_args={"timeout": 5},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        repo,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    for trial in range(5):
        key = f"reply:om_conc:{trial}"
        results = await asyncio.gather(
            asyncio.to_thread(repo.claim, key, BASE, NOT_EXPIRED),
            asyncio.to_thread(repo.claim, key, BASE, NOT_EXPIRED),
        )
        assert sorted(results) == [False, True], (trial, results)
