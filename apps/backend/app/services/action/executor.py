"""V9 CapabilityExecutor（execution-engine.md §2）。

超时包裹 wait_for、异常归一、usage 统计；重试决策在 ActionEngine，不在能力。
"""

import asyncio
import logging
import time

from app.models.action import ActionStep, CapabilityResult
from app.services.action.registry import CapabilityRegistry, ExecutionContext

logger = logging.getLogger(__name__)


class CapabilityExecutor:
    def __init__(self, registry: CapabilityRegistry, timeout_seconds: float):
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    async def run(self, step: ActionStep, ctx: ExecutionContext) -> CapabilityResult:
        capability = self.registry.get(step.capability)
        if capability is None:
            return CapabilityResult(status="failed", error=f"能力未注册: {step.capability}", payload={"failure_kind": "permanent"})
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                capability.execute(step.action, step.params, ctx),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            result = CapabilityResult(
                status="timeout",
                error=f"能力执行超时（>{self.timeout_seconds}s）",
                payload={"failure_kind": "timeout"},
            )
        except Exception as exc:
            logger.exception("能力执行异常，归一为 failed")
            result = CapabilityResult(
                status="failed",
                error=f"{exc.__class__.__name__}: {exc}"[:80],
                payload={"failure_kind": "transient"},
            )
        duration_ms = (time.perf_counter() - started) * 1000
        usage = dict(result.usage)
        usage["duration_ms"] = round(duration_ms, 2)
        result.usage = usage
        return result
