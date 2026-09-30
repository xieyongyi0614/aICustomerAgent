"""出站幂等持久化服务与注入 seam（FEISHU-012）。

生产由 `app/main.py` 在 `FEISHU_ENABLED` 时**无条件安装** hook；本文件既测服务本身，
也测「hook 未安装」这一配置缺陷的降级语义。
"""

import asyncio
import logging

import pytest

from app.channels.feishu import delivery
from app.repositories import feishu_delivery_ledger_repository as repo
from app.services.delivery import ledger as service


@pytest.fixture(autouse=True)
def _isolate_hook():
    """本文件默认在**未安装 hook** 状态下起步（conftest 的 autouse 会先装）。

    需要走持久化路径的用例显式调用 `set_persistent_idempotency`。
    """
    service.reset_delivery_ledger_state()
    delivery.clear_persistent_idempotency()
    yield
    service.reset_delivery_ledger_state()
    delivery.clear_persistent_idempotency()


@pytest.mark.parametrize(
    "outbound,dedupe,expected",
    [(0, 600, 600), (30, 600, 30), (0, 120, 120)],
)
def test_idempotency_ttl_inherits_shared_key(override_settings, outbound, dedupe, expected):
    """TTL 语义：独立键为 0 时沿用入站去重 TTL，否则用独立值。"""
    override_settings(
        feishu_outbound_idempotency_ttl_seconds=outbound,
        feishu_dedupe_ttl_seconds=dedupe,
    )
    assert service.idempotency_ttl_seconds() == expected


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
    with caplog.at_level(logging.WARNING, logger="app.services.delivery.ledger"):
        assert await service.claim("reply:om_fo:0") is True
    assert any("fail-open" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_release_failure_is_ignored(override_settings, monkeypatch, caplog):
    """回滚失败只记 warning：残留占位会在 TTL 后自然淘汰，不应影响发送结果。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)

    def _boom(key):
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "release", _boom)
    with caplog.at_level(logging.WARNING, logger="app.services.delivery.ledger"):
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
    """安装 hook 后 `delivery` 的占位落到持久化存储（跨进程共享）。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    delivery.set_persistent_idempotency(service.claim, service.release)

    assert await delivery._claim_delivery("reply:om_hook:0") is True
    assert repo.exists("reply:om_hook:0") is True


@pytest.mark.asyncio
async def test_persistent_claim_survives_instance_restart(override_settings):
    """核心价值：判定不依赖任何进程内状态。

    「重启实例」= 卸载 hook 再重新安装（进程内状态清零）；同一键仍必须被判重。
    """
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    delivery.set_persistent_idempotency(service.claim, service.release)
    assert await delivery._claim_delivery("reply:om_xproc:0") is True

    delivery.clear_persistent_idempotency()
    delivery.set_persistent_idempotency(service.claim, service.release)
    assert await delivery._claim_delivery("reply:om_xproc:0") is False


@pytest.mark.asyncio
async def test_hook_release_rolls_back_persistent_claim(override_settings):
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    delivery.set_persistent_idempotency(service.claim, service.release)

    assert await delivery._claim_delivery("reply:om_rb:0") is True
    await delivery._release_delivery("reply:om_rb:0")
    assert repo.exists("reply:om_rb:0") is False


@pytest.mark.asyncio
async def test_missing_hook_fails_open_with_error(override_settings, caplog):
    """hook 未安装属**配置缺陷**（组合根没跑）：记 error 后放行发送。

    放行而非跳过——「重复一条消息」远比「用户收不到回复」可接受。
    """
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    with caplog.at_level(logging.ERROR, logger="app.channels.feishu.delivery"):
        assert await delivery._claim_delivery("reply:om_nohook:0") is True
    assert any("hook 未安装" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_missing_hook_logs_error_only_once(override_settings, caplog):
    """缺 hook 的告警只记一次，避免每次发送刷爆日志。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    with caplog.at_level(logging.ERROR, logger="app.channels.feishu.delivery"):
        for index in range(5):
            assert await delivery._claim_delivery(f"reply:om_noise:{index}") is True
    assert len([r for r in caplog.records if "hook 未安装" in r.getMessage()]) == 1


@pytest.mark.asyncio
async def test_missing_hook_release_is_noop(override_settings):
    override_settings(feishu_outbound_idempotency_ttl_seconds=600)
    await delivery._release_delivery("reply:om_nohook:0")


@pytest.mark.asyncio
async def test_hook_ttl_expiry_allows_resend(override_settings):
    """跨过 TTL 后同一幂等键可重发（长时间后的重试不应被永久挡住）。"""
    override_settings(feishu_outbound_idempotency_ttl_seconds=1)
    delivery.set_persistent_idempotency(service.claim, service.release)

    assert await delivery._claim_delivery("reply:om_exp:0") is True
    await asyncio.sleep(1.1)
    assert await delivery._claim_delivery("reply:om_exp:0") is True
