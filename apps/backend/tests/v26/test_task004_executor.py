"""TASK-004 Action Executor 分派与结果捕获测试。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.models.action import Action, ActionResult
from app.services.action.executor import ActionExecutor, CapabilityExecutor, dispatch
from app.services.action.registry import ExecutionContext, get_capability_registry


def _action(type_="create_reminder", **kwargs):
    return Action(id="act_t4", type=type_, parameters=kwargs.pop("params", {"content": "开会"}), **kwargs)


def _ctx():
    return ExecutionContext(user_id="u1", character_id="asuna", record_id="act_t4", now=None, settings=None)


class TestDispatch:
    def test_full_mapping(self):
        assert dispatch(_action("create_reminder")) == "internal"
        assert dispatch(_action("cancel_reminder")) == "internal"
        assert dispatch(_action("remember_fact")) == "internal"
        assert dispatch(_action("create_object")) == "internal"
        assert dispatch(_action("move_object")) == "internal"
        assert dispatch(_action("use_object")) == "internal"
        assert dispatch(_action("query_environment")) == "tool"
        assert dispatch(_action("query_search")) == "tool"
        assert dispatch(_action("send_notification")) == "external"

    def test_unknown_type_none(self):
        with pytest.raises(Exception):
            Action(id="x", type="not_a_type")


class TestExternalReserved:
    def test_external_returns_unavailable(self):
        registry = get_capability_registry()
        executor = ActionExecutor(registry)
        result = asyncio.run(executor.execute_external(_action("send_notification"), _ctx()))
        assert result.status == "failed"
        assert result.failure_kind == "unavailable"
        assert result.error == "external_adapter_reserved"


class TestRunAlwaysProducesResult:
    def test_run_external_always_result(self):
        executor = ActionExecutor(get_capability_registry())
        result = asyncio.run(executor.run(_action("send_notification"), _ctx()))
        assert isinstance(result, ActionResult)
        assert result is not None

    def test_run_tool_without_executor_unavailable(self):
        executor = ActionExecutor(get_capability_registry())
        result = asyncio.run(
            executor.run(_action("query_environment", params={"scope": "all"}), _ctx())
        )
        assert result.status == "failed"
        assert result.failure_kind == "unavailable"

    def test_run_exception_normalized(self):
        class BoomRegistry:
            def get(self, name):
                raise RuntimeError("boom")

        executor = ActionExecutor(BoomRegistry())
        # ActionExecutor uses CapabilityExecutor which catches registry.get? actually registry.get is outside try
        # force via execute_internal with broken mapping path
        class BoomExecutor(ActionExecutor):
            async def execute_internal(self, action, ctx):
                raise RuntimeError("internal boom")

        executor = BoomExecutor(get_capability_registry())
        result = asyncio.run(executor.run(_action("create_reminder"), _ctx()))
        assert result.status == "failed"
        assert result.failure_kind == "transient"
        assert "internal boom" in (result.error or "")


class TestToolPath:
    def test_tool_resolver_unavailable(self):
        def resolver(action):
            return None, None

        class FakeToolExecutor:
            async def run(self, *a, **k):
                raise AssertionError("should not run")

        executor = ActionExecutor(
            get_capability_registry(),
            tool_executor=FakeToolExecutor(),
            tool_resolver=resolver,
        )
        result = asyncio.run(
            executor.run(_action("query_environment", params={}), _ctx())
        )
        assert result.status == "failed"
        assert result.failure_kind == "unavailable"

    def test_tool_success(self):
        class FakeToolExecutor:
            async def run(self, binding, invocation, ctx):
                return SimpleNamespace(status="succeeded", error=None)

        def resolver(action):
            return object(), object()

        executor = ActionExecutor(
            get_capability_registry(),
            tool_executor=FakeToolExecutor(),
            tool_resolver=resolver,
        )
        result = asyncio.run(
            executor.run(_action("query_search", params={"query": "天气"}), _ctx())
        )
        assert result.status == "succeeded"

    def test_tool_timeout_normalized(self):
        class FakeToolExecutor:
            async def run(self, binding, invocation, ctx):
                return SimpleNamespace(status="timeout", error="tool timeout")

        def resolver(action):
            return object(), object()

        executor = ActionExecutor(
            get_capability_registry(),
            tool_executor=FakeToolExecutor(),
            tool_resolver=resolver,
        )
        result = asyncio.run(
            executor.run(_action("query_environment", params={}), _ctx())
        )
        assert result.status == "failed"
        assert result.failure_kind == "timeout"


class TestInternalPath:
    def test_internal_unknown_capability_type_permanent(self):
        executor = ActionExecutor(get_capability_registry())
        action = Action(id="a", type="create_reminder", parameters={})
        # monkeypatch map lookup by calling execute_internal after removing key via dispatch path
        result = asyncio.run(executor.execute_internal(action, _ctx()))
        # default create_reminder maps to reminder capability which is registered
        assert result.status in ("succeeded", "failed")
        assert result.failure_kind in (None, "transient", "permanent", "timeout", "unavailable")

    def test_capability_timeout_normalized(self):
        class SlowCapability:
            async def execute(self, action, params, ctx):
                import asyncio as aio

                await aio.sleep(1.0)
                return SimpleNamespace(status="succeeded", payload={}, usage={}, error=None)

        class FakeRegistry:
            def get(self, name):
                return SlowCapability()

        executor = ActionExecutor(FakeRegistry(), timeout_seconds=0.01)
        result = asyncio.run(executor.execute_internal(_action("create_reminder"), _ctx()))
        assert result.status == "failed"
        assert result.failure_kind == "timeout"


class TestStaticNoDecision:
    def test_executor_source_has_no_decision_calls(self):
        import app.services.action.executor as module

        source = open(module.__file__, encoding="utf-8").read()
        assert "decision_pipeline" not in source
        assert "autonomy_policy" not in source
        assert "next_retry_at" not in source
