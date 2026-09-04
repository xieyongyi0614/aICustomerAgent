"""V9 Capability System：注册表 + 校验 + 能力执行（V9-002 capability-system.md）。"""

import pytest

from app.models.action import ActionSchema, ActionStep
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import CapabilityRegistry, ExecutionContext, get_capability_registry
from app.core.settings import get_settings


def test_registry_has_expected_capabilities():
    reg = get_capability_registry()
    for name in ("reminder", "memory", "world_action", "environment_query", "search", "notification"):
        assert reg.has(name), f"missing capability {name}"


def test_schema_validation_required():
    schema = ActionSchema(required=["content", "due_at"], optional={})
    errors = schema.validate({"content": "喝水"})
    assert any("due_at" in e for e in errors)


def test_schema_validation_ok():
    schema = ActionSchema(required=["content"], optional={})
    assert schema.validate({"content": "喝水"}) == []


@pytest.mark.asyncio
async def test_executor_unknown_capability_fails():
    executor = CapabilityExecutor(get_capability_registry(), 5.0)
    step = ActionStep(index=0, capability="nope", action="x", params={})
    ctx = ExecutionContext(user_id="cap-user", character_id="asuna", record_id="r1", now=None, settings=get_settings())
    result = await executor.run(step, ctx)
    assert result.status == "failed"
    assert "未注册" in (result.error or "")

