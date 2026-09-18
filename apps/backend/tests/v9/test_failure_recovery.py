"""V9 Failure Recovery（execution-engine.md §3/§4，testing.md 第 7 套件主观）。

transient 退避重试曲线 / 超限终态 / permanent 不重试；失败→行动段\"待补救\"；
integrate 单通道失败降级不回滚。
"""

from datetime import datetime

import pytest

from app.application import action_engine
from app.application.action_engine import execute_plan, integrate_result, new_record
from app.models.action import (
    ActionIntent,
    ActionPlan,
    ActionSchema,
    ActionStep,
    ActionResult,
    CapabilityResult,
)
from app.repositories import action_repository
from app.services.action.registry import CapabilityRegistry, ExecutionContext


class FlakyCapability:
    name = "flaky"
    description = "可重试瞬时失败"
    actions = {"go": ActionSchema()}

    def validate(self, action, params):
        return []

    async def execute(self, action, params, ctx):
        return CapabilityResult(
            status="failed", error="transient hiccup", payload={"failure_kind": "transient"}
        )


class PermanentCapability:
    name = "perma"
    description = "不可重试永久失败"
    actions = {"go": ActionSchema()}

    def validate(self, action, params):
        return []

    async def execute(self, action, params, ctx):
        return CapabilityResult(
            status="failed", error="permanent", payload={"failure_kind": "permanent"}
        )


def _intent(action_type="remember_fact", **params):
    return ActionIntent(
        action_type=action_type, confidence="confident", params=params, dedupe_key=""
    )


def _plan(intent, capability):
    return ActionPlan(
        intent=intent,
        steps=[ActionStep(index=0, capability=capability, action="go", params={})],
    )


def _stub_tools(*implementations):
    """V2.4.0 起步骤经工具面解析：为打桩能力补最小工具声明（实现体一并传入以过解析校验）。"""
    from app.models.tool import PermissionProfile, ToolDefinition, ToolSchema
    from app.services.tool.registry import ToolRegistry

    registry = ToolRegistry()
    for implementation in implementations:
        registry.register(
            ToolDefinition(
                id=f"stub.{implementation.name}.go",
                name=implementation.name,
                description=implementation.description,
                namespace="builtin",
                capability=implementation.name,
                action="go",
                input_schema=ToolSchema(),
                permission=PermissionProfile(level="normal", scope=("world",)),
                side_effects=("read",),
            ),
            capability=implementation,
        )
    return registry

@pytest.mark.asyncio
async def test_transient_retry_schedules_backoff(db_session_factory, monkeypatch, override_settings):
    override_settings(
        action_enabled=True,
        action_retry_backoff_seconds=30,
        action_retry_max_attempts=2,
    )
    reg = CapabilityRegistry()
    reg.register(FlakyCapability())
    monkeypatch.setattr(action_engine, "get_capability_registry", lambda: reg)
    monkeypatch.setattr(action_engine, "get_tool_registry", lambda: _stub_tools(FlakyCapability()))
    intent = _intent()
    record = new_record(intent, "rec-user", session_id=None)
    ctx = ExecutionContext(
        user_id="rec-user", character_id="asuna", record_id=record.id,
        now=datetime.now(), settings=ctx_settings(),
    )
    result = await execute_plan(record, _plan(intent, "flaky"), ctx)
    assert result.status == "failed"
    assert record.status == "executing"
    assert record.attempt == 2
    base = ctx.settings.action_retry_backoff_seconds
    expected = base * (2 ** (record.attempt - 1))
    assert record.next_retry_at is not None
    assert abs((record.next_retry_at - datetime.now()).total_seconds() - expected) < 2


@pytest.mark.asyncio
async def test_transient_exceeded_attempts_terminal(db_session_factory, monkeypatch, override_settings):
    override_settings(
        action_enabled=True,
        action_retry_backoff_seconds=30,
        action_retry_max_attempts=2,
    )
    reg = CapabilityRegistry()
    reg.register(FlakyCapability())
    monkeypatch.setattr(action_engine, "get_capability_registry", lambda: reg)
    monkeypatch.setattr(action_engine, "get_tool_registry", lambda: _stub_tools(FlakyCapability()))
    intent = _intent()
    record = new_record(intent, "rec-user-2", session_id=None)
    record.attempt = 2  # 已达上限
    ctx = ExecutionContext(
        user_id="rec-user-2", character_id="asuna", record_id=record.id,
        now=datetime.now(), settings=ctx_settings(),
    )
    result = await execute_plan(record, _plan(intent, "flaky"), ctx)
    assert result.status == "failed"
    assert record.status == "failed"


@pytest.mark.asyncio
async def test_permanent_no_retry_fails(db_session_factory, monkeypatch, override_settings):
    override_settings(action_enabled=True)
    reg = CapabilityRegistry()
    reg.register(PermanentCapability())
    monkeypatch.setattr(action_engine, "get_capability_registry", lambda: reg)
    monkeypatch.setattr(action_engine, "get_tool_registry", lambda: _stub_tools(PermanentCapability()))
    intent = _intent()
    record = new_record(intent, "rec-user-3", session_id=None)
    ctx = ExecutionContext(
        user_id="rec-user-3", character_id="asuna", record_id=record.id,
        now=datetime.now(), settings=ctx_settings(),
    )
    result = await execute_plan(record, _plan(intent, "perma"), ctx)
    assert result.status == "failed"
    assert record.status == "failed"
    assert record.attempt == 1


@pytest.mark.asyncio
async def test_failed_action_context_shows_remedy_hint(db_session_factory, override_settings):
    from app.services.action.context import build_action_context, render_action_section

    override_settings(action_enabled=True)
    record = new_record(
        _intent("create_reminder", content="开会", due_at="2026-09-05T08:00:00"),
        "rec-user-4", session_id=None,
    )
    record.status = "failed"
    action_repository.save_record(record)
    ctx = build_action_context("rec-user-4")
    if ctx is not None:
        rendered = render_action_section(ctx, 400)
        assert "上次失败" in rendered


def test_memory_bridge_failure_degrades_to_none(db_session_factory, monkeypatch, override_settings):
    from app.repositories import memory_repository
    from app.services.action.memory_bridge import deliver_action_memory

    override_settings(action_enabled=True, action_memory_policy_enabled=True)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(memory_repository, "create_memory", boom)
    record = new_record(
        _intent("create_reminder", content="提醒吃药", due_at="2026-09-05T08:00:00"),
        "rec-user-5", session_id=None,
    )
    record.status = "succeeded"
    assert deliver_action_memory(record, "rec-user-5") is None


def ctx_settings():
    from app.core.settings import get_settings

    return get_settings()
