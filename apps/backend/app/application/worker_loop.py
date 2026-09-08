"""常驻 Worker 循环统一助手：异常不终止循环，但连续失败按指数退避，防止静默死循环刷日志。

- 成功后恢复基础间隔；
- 首次失败保持基础间隔（保留快速重试语义，兼容既有测试节拍）；
- 连续失败第 2 次起按指数退避（1s 起步，封顶 max_backoff），成功后清零；
- 连续失败达到 worker_circuit_breaker_threshold（可覆盖）时触发熔断：
  日志升级 CRITICAL 并调用 on_circuit_open 一次，恢复后重新闭合。
"""

import asyncio
import inspect
import logging

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 300.0


async def run_worker_loop(
    name: str,
    tick,
    interval: float,
    max_backoff_seconds: float = MAX_BACKOFF_SECONDS,
    offload: bool = False,
    max_consecutive_failures: int | None = None,
    on_circuit_open=None,
) -> None:
    """常驻循环：异常退避 + 可选线程下放 + 连续失败熔断。

    offload=True 时同步 tick 经 asyncio.to_thread 执行，避免同步 DB/网络
    调用阻塞事件循环；offload 适用于与事件循环无共享可变内存状态、
    不使用 loop 绑定原语的 tick。

    max_consecutive_failures=None 时读 Settings.worker_circuit_breaker_threshold；
    0 表示关闭熔断。熔断开启只告警不停止循环（退避封顶已由 max_backoff 兜底）。
    """
    settings = get_settings()
    threshold = (
        settings.worker_circuit_breaker_threshold
        if max_consecutive_failures is None
        else max_consecutive_failures
    )
    base_interval = interval
    failures = 0
    circuit_open = False
    while True:
        await asyncio.sleep(interval)
        try:
            if offload and not inspect.iscoroutinefunction(tick):
                await asyncio.to_thread(tick)
            else:
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
            if 0 < threshold <= failures and not circuit_open:
                circuit_open = True
                logger.critical(
                    "%s 连续失败 %d 次，熔断开启（保持退避重试，等待恢复）",
                    name,
                    failures,
                )
                if on_circuit_open is not None:
                    on_circuit_open()
        else:
            if failures > 0:
                logger.info("%s 恢复正常，重置退避", name)
                if circuit_open:
                    logger.info("%s 熔断恢复，重新闭合", name)
            failures = 0
            circuit_open = False
            interval = base_interval
