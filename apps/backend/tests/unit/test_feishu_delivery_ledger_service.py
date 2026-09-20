"""出站幂等持久化服务 + 注入 seam：fail-open、TTL 一致性与跨进程生效（FEISHU-011）。"""

import asyncio
import logging

import pytest

from app.channels.feishu import delivery
from app.repositories import feishu_delivery_ledger_repository as repo
from app.services import feishu_delivery_ledger_service as service


@pytest.fixture(autouse=True)
def _reset_state():
    service.reset_delivery_ledger_state()
    delivery.reset_delivery_state()
    delivery.clear_persistent_idempotency()
    yield
    service.reset_delivery_ledger_state()
    delivery.reset_delivery_state()
    delivery.clear_persistent_idempotency()


def test_ttl_matches_delivery_module(override_settings):
    """两处 TTL 表达式必须一致，否则会出现「内存已过期、DB 仍判重」的隐性差异。"""
    for outbound, dedupe in ((0, 600), (30, 600), (0, 120)):
        override_settings(
            feishu_outbound_idempotency_ttl_seconds=outbound,
            feishu_dedupe_ttl_seconds=dedupe,
        )
        assert service.idempotency_ttl_seconds() == delivery._idempotency_ttl_seconds()


@pytest.mark.asyncio
async def test_claim_then_duplicate(override_settings):
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    assert await service.claim("reply:om_svc:0") is True
    assert await service.claim("reply:om_svc:0") is False


@pytest.mark.asyncio
async def test_release_allows_reclaim(override_settings):
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    assert await service.claim("reply:om_rel:0") is True
    await service.release("reply:om_rel:0")
    assert await service.claim("reply:om_rel:0") is True


@pytest.mark.asyncio
async def test_claim_fail_open_when_store_unavailable(override_settings, monkeypatch, caplog):
    """存储故障时**必须放行投递**：fail-closed 会让用户收不到任何回复。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)

    def _boom(key, delivered_at, expired_before):
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "claim", _boom)
    with caplog.at_level(logging.WARNING, logger="app.services.feishu_delivery_ledger_service"):
        assert await service.claim("reply:om_fo:0") is True
    assert any("fail-open" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_release_failure_is_ignored(override_settings, monkeypatch, caplog):
    """回滚失败只记 warning：残留占位会在 TTL 后自然淘汰，不应影响发送结果。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)

    def _boom(key):
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "release", _boom)
    with caplog.at_level(logging.WARNING, logger="app.services.feishu_delivery_ledger_service"):
        await service.release("reply:om_rf:0")
    assert any("release failed" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_amortized_purge_runs_once_per_window(override_settings, monkeypatch):
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    calls = []

    def _purge(cutoff):
        calls.append(cutoff)
        return 0

    monkeypatch.setattr(repo, "purge_before", _purge)
    for index in range(service.PURGE_EVERY):
        assert await service.claim(f"reply:om_purge:{index}") is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_installed_hook_routes_claim_to_persistent_store(override_settings):
    """安装 hook 后 `delivery` 的占位走持久化存储（跨进程），而非进程内表。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    delivery.set_persistent_idempotency(service.claim, service.release)

    assert await delivery._claim_delivery("reply:om_hook:0") is True
    assert delivery._delivered == {}  # 进程内表未被使用
    assert repo.exists("reply:om_hook:0") is True


@pytest.mark.asyncio
async def test_persistent_hook_survives_process_local_reset(override_settings):
    """对照组核心：清空进程内表后重投仍被判重（等价于换一个实例）。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    delivery.set_persistent_idempotency(service.claim, service.release)

    assert await delivery._claim_delivery("reply:om_xproc:0") is True
    delivery.reset_delivery_state()  # 模拟另一实例：进程内表为空
    assert await delivery._claim_delivery("reply:om_xproc:0") is False


@pytest.mark.asyncio
async def test_memory_hook_does_not_survive_process_local_reset(override_settings):
    """对照：未安装 hook 时清空进程内表即失去判重——这正是多实例的缺口。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    assert await delivery._claim_delivery("reply:om_mem:0") is True
    delivery.reset_delivery_state()
    assert await delivery._claim_delivery("reply:om_mem:0") is True


@pytest.mark.asyncio
async def test_hook_release_rolls_back_persistent_claim(override_settings):
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    delivery.set_persistent_idempotency(service.claim, service.release)

    assert await delivery._claim_delivery("reply:om_rb:0") is True
    await delivery._release_delivery("reply:om_rb:0")
    assert repo.exists("reply:om_rb:0") is False


@pytest.mark.asyncio
async def test_clear_hook_restores_memory_path(override_settings):
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    delivery.set_persistent_idempotency(service.claim, service.release)
    delivery.clear_persistent_idempotency()

    assert await delivery._claim_delivery("reply:om_back:0") is True
    assert list(delivery._delivered) == ["reply:om_back:0"]


@pytest.mark.asyncio
async def test_hook_ttl_expiry_allows_resend(override_settings):
    """跨过 TTL 后同一幂等键可重发（DB 路径的 TTL 语义与内存路径一致）。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=1)
    delivery.set_persistent_idempotency(service.claim, service.release)

    assert await delivery._claim_delivery("reply:om_exp:0") is True
    await asyncio.sleep(1.1)
    assert await delivery._claim_delivery("reply:om_exp:0") is True
