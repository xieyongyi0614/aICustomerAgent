"""V9-003 CapabilityRegistry 单测（capability-system.md §2~§3）。"""

from datetime import datetime
from typing import Any

import pytest

from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import CapabilityRegistry, ExecutionContext


class DummyCapability:
    name = "dummy"
    description = "测试用能力"
    actions = {"act": ActionSchema(required=["x"])}

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        return schema.validate(params) if schema else [f"未知动作: {action}"]

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        return CapabilityResult(status="succeeded", payload={"x": params.get("x")})


class OtherCapability(DummyCapability):
    name = "other"


def test_register_and_get():
    registry = CapabilityRegistry()
    cap = DummyCapability()
    registry.register(cap)
    assert registry.get("dummy") is cap
    assert registry.get("missing") is None


def test_register_duplicate_rejected():
    registry = CapabilityRegistry()
    registry.register(DummyCapability())
    with pytest.raises(ValueError):
        registry.register(DummyCapability())


def test_has_with_and_without_action():
    registry = CapabilityRegistry()
    registry.register(DummyCapability())
    assert registry.has("dummy")
    assert registry.has("dummy", "act")
    assert not registry.has("dummy", "nope")
    assert not registry.has("missing")


def test_describe():
    registry = CapabilityRegistry()
    registry.register(DummyCapability())
    described = registry.describe()
    assert described[0]["name"] == "dummy"
    assert "act" in described[0]["actions"]


def test_builtin_registry_complete():
    from app.services.action.registry import get_capability_registry

    registry = get_capability_registry()
    names = {entry["name"] for entry in registry.describe()}
    assert names == {"reminder", "memory", "world_action", "environment_query", "search", "notification"}
