"""后台任务调度：返回值语义 + 未捕获异常可观测（F-06/F-07）。"""

import asyncio
import inspect
import logging

import pytest

from app.application import observability


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if (name == "app" or name.startswith("app.")) and isinstance(logger, logging.Logger):
            logger.disabled = False
    previous = observability._main_loop
    yield
    observability._main_loop = previous
    observability.background_tasks.clear()


def test_spawn_background_without_any_loop_closes_coroutine():
    observability._main_loop = None

    async def _work():
        raise AssertionError("不应被执行")

    coro = _work()
    assert observability.spawn_background(coro) is False
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


@pytest.mark.asyncio
async def test_spawn_background_retains_then_releases_task():
    observability._main_loop = asyncio.get_running_loop()
    done = asyncio.Event()

    async def _work():
        done.set()

    assert observability.spawn_background(_work()) is True
    await asyncio.wait_for(done.wait(), timeout=1.0)
    await asyncio.sleep(0.05)
    assert observability.background_tasks == set()


@pytest.mark.asyncio
async def test_spawn_background_logs_uncaught_exception(caplog):
    observability._main_loop = asyncio.get_running_loop()

    async def _boom():
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="app.application.observability"):
        assert observability.spawn_background(_boom()) is True
        await asyncio.sleep(0.05)

    assert any("后台任务异常未捕获" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_spawn_background_from_worker_thread_hops_to_main_loop():
    observability._main_loop = asyncio.get_running_loop()
    done = asyncio.Event()

    async def _work():
        done.set()

    assert await asyncio.to_thread(observability.spawn_background, _work()) is True
    await asyncio.wait_for(done.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_spawn_background_worker_thread_logs_uncaught_exception(caplog):
    observability._main_loop = asyncio.get_running_loop()

    async def _boom():
        raise RuntimeError("thread-boom")

    with caplog.at_level(logging.ERROR, logger="app.application.observability"):
        assert await asyncio.to_thread(observability.spawn_background, _boom()) is True
        await asyncio.sleep(0.1)

    assert any("跨线程投递" in record.getMessage() for record in caplog.records)
