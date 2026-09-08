"""常驻 Worker 循环统一助手：异常不终止循环，但连续失败按指数退避，防止静默死循环刷日志。

- 成功后恢复基础间隔；
- 首次失败保持基础间隔（保留快速重试语义，兼容既有测试节拍）；
- 连续失败第 2 次起按指数退避（1s 起步，封顶 max_backoff），成功后清零。
"""

import asyncio
import inspect
import logging

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 300.0


async def run_worker_loop(
    name: str,
    tick,
    interval: float,
    max_backoff_seconds: float = MAX_BACKOFF_SECONDS,
) -> None:
    base_interval = interval
    failures = 0
    while True:
        await asyncio.sleep(interval)
        try:
            result = tick()
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            logger.exception("%s tick 失败（连续第 %d 次）", name, failures)
            if failures > 1:
                interval = min(
                    max(interval, 1.0) * (2 ** (failures - 1)),
                    max_backoff_seconds,
                )
        else:
            if failures > 0:
                logger.info("%s 恢复正常，重置退避", name)
            failures = 0
            interval = base_interval
