"""V7-007：Worker tick 循环容错与开关。"""

import asyncio
import contextlib
from datetime import datetime

from app.application import autonomy_engine, autonomy_worker


def test_tick_returns_empty_when_no_users(monkeypatch):
    from app.repositories import conversation_repository

    monkeypatch.setattr(
        conversation_repository, "list_user_ids", lambda: [], raising=False
    )
    import asyncio

    delivered = asyncio.run(autonomy_engine.tick(now=datetime(2026, 8, 30, 14, 0)))
    assert delivered == []


def test_tick_survives_user_evaluation_error(monkeypatch):
    from app.repositories import conversation_repository

    monkeypatch.setattr(
        conversation_repository, "list_user_ids", lambda: ["u1"], raising=False
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        conversation_repository, "get_latest_for_user", _boom, raising=False
    )
    import asyncio

    delivered = asyncio.run(
        autonomy_engine.tick(now=datetime(2026, 8, 30, 14, 0))
    )
    assert delivered == []


async def test_worker_loop_continues_after_tick_error(monkeypatch):
    calls = {"n": 0}

    async def _boom(**kwargs):
        calls["n"] += 1
        raise RuntimeError("tick down")

    monkeypatch.setattr(autonomy_engine, "tick", _boom)

    task = asyncio.create_task(autonomy_worker.run_autonomy_worker(tick_seconds=0))
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert calls["n"] >= 2
