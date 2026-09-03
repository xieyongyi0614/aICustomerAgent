"""V9-004 CapabilityExecutor 单元测试（execution-engine.md §2）。"""

import asyncio

import pytest

from app.models.action import ActionSchema, ActionStep, CapabilityResult
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import CapabilityRegistry, ExecutionContext


class SlowCapability:
    name = "slow"
    description = "超时能力"
    actions = {"go": ActionSchema()}

    def validate(self, action, params):
        return []

    async def execute(self, action, params, ctx):
        await asyncio.sleep(5)
        return CapabilityResult(status="succeeded")


class BoomCapability:
    name = "boom"
    description = "异常能力"
    actions = {"go": ActionSchema()}

    def validate(self, action, params):
        return []

    async def execute(self, action, params, ctx):
        raise RuntimeError("boom!")


class OkCapability:
    name = "ok"
    description = "正常能力"
    actions = {"go": ActionSchema()}

    def validate(self, action, params):
        return []

    async def execute(self, action, params, ctx):
        return CapabilityResult(status="succeeded", payload={"x": 1})


@pytest.mark.asyncio
async def test_success_with_usage():
    registry = CapabilityRegistry()
    registry.register(OkCapability())
    executor = CapabilityExecutor(registry, timeout_seconds=2)
    result = await executor.run(ActionStep(index=0, capability="ok", action="go", params={}), ExecutionContext(user_id="u"))
    assert result.status == "succeeded"
    assert "duration_ms" in result.usage


@pytest.mark.asyncio
async def test_exception_normalized_to_failed_transient():
    registry = CapabilityRegistry()
    registry.register(BoomCapability())
    executor = CapabilityExecutor(registry, timeout_seconds=2)
    result = await executor.run(ActionStep(index=0, capability="boom", action="go", params={}), ExecutionContext(user_id="u"))
    assert result.status == "failed"
    assert result.payload["failure_kind"] == "transient"


@pytest.mark.asyncio
async def test_timeout():
    registry = CapabilityRegistry()
    registry.register(SlowCapability())
    executor = CapabilityExecutor(registry, timeout_seconds=0.1)
    result = await executor.run(ActionStep(index=0, capability="slow", action="go", params={}), ExecutionContext(user_id="u"))
    assert result.status == "timeout"
    assert result.payload["failure_kind"] == "timeout"


@pytest.mark.asyncio
async def test_unregistered_capability():
    registry = CapabilityRegistry()
    executor = CapabilityExecutor(registry, timeout_seconds=2)
    result = await executor.run(ActionStep(index=0, capability="nope", action="go", params={}), ExecutionContext(user_id="u"))
    assert result.status == "failed"
    assert result.payload["failure_kind"] == "permanent"