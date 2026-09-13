"""V7 Autonomy Worker（scheduler.md）：lifespan 内 asyncio tick 循环。

AUTO-001 调度收敛：life_loop 为唯一周期入口（v2_life_loop_enabled=True），
本 worker 仅作为其关闭时的兜底 tick 源；lifespan 接线与本判定双保险，
避免双 tick 源对同一 Trigger 重复求值。
不阻塞聊天请求；tick 异常只记日志下轮继续；autonomy_enabled=False 由 lifespan 层不启动。
"""

import asyncio
import logging

from app.application import autonomy_engine
from app.application.worker_loop import run_worker_loop
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


async def run_autonomy_worker(tick_seconds: int | None = None, llm=None) -> None:
    settings = get_settings()
    if settings.v2_life_loop_enabled:
        logger.info("v2 life loop 已接管周期调度，autonomy worker 兜底退出")
        return
    interval = (
        settings.autonomy_tick_seconds if tick_seconds is None else tick_seconds
    )

    async def _tick():
        delivered = await autonomy_engine.tick(llm=llm)
        if delivered:
            logger.info("本轮主动消息：%d 条", len(delivered))

    await run_worker_loop("autonomy worker", _tick, interval)
