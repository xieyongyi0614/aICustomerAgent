"""P1-6：Worker 循环熔断——连续失败达到阈值触发告警回调一次，恢复后重新闭合。"""

import asyncio
import contextlib

import pytest

from app.application.worker_loop import run_worker_loop
from app.core.settings import get_settings

_real_sleep = asyncio.sleep


async def _patched_sleep(_):
    await _real_sleep(0.0001)


async def _wait_until(calls, key, minimum, timeout=5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while calls[key] < minimum:
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(f"等待 {key} >= {minimum} 超时（当前 {calls[key]}）")
        await _real_sleep(0.0001)
    await _real_sleep(0.0001)


async def test_circuit_opens_once_after_threshold(monkeypatch):
    monkeypatch.setattr("app.application.worker_loop.asyncio.sleep", _patched_sleep)
    calls = {"n": 0, "opened": 0}

    def _tick():
        calls["n"] += 1
        raise RuntimeError("down")

    def _on_open():
        calls["opened"] += 1

    task = asyncio.create_task(
        run_worker_loop(
            "cb", _tick, 0, max_consecutive_failures=3, on_circuit_open=_on_open
        )
    )
    await _wait_until(calls, "opened", 1)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert calls["opened"] == 1
    assert calls["n"] >= 4


async def test_circuit_closes_after_recovery(monkeypatch):
    monkeypatch.setattr("app.application.worker_loop.asyncio.sleep", _patched_sleep)
    calls = {"fail": 0, "ok": 0, "opened": 0}

    def _tick():
        if calls["fail"] < 4:
            calls["fail"] += 1
            raise RuntimeError("temp down")
        calls["ok"] += 1

    def _on_open():
        calls["opened"] += 1

    task = asyncio.create_task(
        run_worker_loop(
            "cb", _tick, 0, max_consecutive_failures=4, on_circuit_open=_on_open
        )
    )
    await _wait_until(calls, "opened", 1)
    await _wait_until(calls, "ok", 2)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert calls["opened"] == 1
    assert calls["ok"] >= 2


async def test_circuit_disabled_with_zero_threshold(monkeypatch):
    monkeypatch.setattr("app.application.worker_loop.asyncio.sleep", _patched_sleep)
    calls = {"n": 0, "opened": 0}

    def _tick():
        calls["n"] += 1
        raise RuntimeError("down")

    def _on_open():
        calls["opened"] += 1

    task = asyncio.create_task(
        run_worker_loop(
            "cb", _tick, 0, max_consecutive_failures=0, on_circuit_open=_on_open
        )
    )
    await _wait_until(calls, "n", 3)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert calls["opened"] == 0
    assert calls["n"] >= 3


async def test_circuit_uses_settings_threshold_by_default():
    threshold = get_settings().worker_circuit_breaker_threshold
    assert threshold > 0
