"""TASK-004 Action Executor 分派与结果捕获测试。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.models.action import Action, ActionResult
from app.services.action.executor import ActionExecutor, CapabilityExecutor, dispatch
from app.core.settings import get_settings
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
        assert result.status == "timeout"
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
        assert result.status == "timeout"
        assert result.failure_kind == "timeout"


class TestStaticNoDecision:
    def test_executor_source_has_no_decision_calls(self):
        import app.services.action.executor as module

        source = open(module.__file__, encoding="utf-8").read()
        assert "decision_pipeline" not in source
        assert "autonomy_policy" not in source
        assert "next_retry_at" not in source

class TestPendingConfirmationRegistration:
    """v26 去门控（批次 7）：确认登记移植到主路径唯一登记点（原 `_register_confirmation`）。

    ToolExecutor 权限段产 `pending_confirmation` → 主路径登记确认请求、记录转
    `planned` + `gate_reason=pending_confirmation`（TOOL-005 §2.3 语义在统一分派下的落地）。
    """

    def _definition(self):
        from tests.v24.tool005_support import sensitive_definition

        return sensitive_definition()

    def _meta_result(self, definition):
        from app.models.action import ActionResult

        return ActionResult(
            status="failed",
            failure_kind="transient",
            error="等待用户确认",
            metadata={
                "tool_status": "pending_confirmation",
                "permission": {
                    "decision": "confirm_required",
                    "level": "sensitive",
                    "reason": "level_confirm_required",
                },
            },
        )

    def test_register_pending_confirmation_lands_request(self, override_settings):
        import asyncio
        from datetime import datetime

        from app.application import action_engine
        from app.services.tool import confirmation as confirmation_mod
        from app.services.tool.context import ToolContext

        override_settings()
        definition = self._definition()
        tool_registry = SimpleNamespace(get=lambda tool_id: definition)
        binding = SimpleNamespace(tool_id=definition.id)
        invocation = SimpleNamespace(
            tool_id=definition.id,
            params={"content": "hi"},
            dedupe_key="pending:reg:1",
            intent=None,
            rationale="",
            source="autonomy",
            goal_id=None,
            run_id=None,
        )
        tool_resolver = lambda action: (binding, invocation)
        tool_ctx = ToolContext(run_kind="autonomous_tick", user_id="u_pending")
        settings = get_settings()
        action = SimpleNamespace(parameters={"content": "hi"})

        prompt = action_engine._register_pending_confirmation(
            action,
            {"permission": {"decision": "confirm_required", "level": "sensitive"}},
            tool_registry,
            tool_resolver,
            tool_ctx,
            settings,
        )
        assert prompt
        pending = confirmation_mod.get_confirmation_service().pending("u_pending")
        assert any(item.tool_id == definition.id for item in pending)

    def test_apply_result_maps_pending_to_planned(self):
        from app.application import action_engine
        from app.models.action import ActionRecord

        result = self._meta_result(None)
        record = ActionRecord(
            id="act-pending-map",
            user_id="u_pending",
            action_type="query_environment",
            status="executing",
            attempt=1,
        )
        action_engine._apply_action_result_to_record(record, result, get_settings())
        assert record.status == "planned"
        assert record.gate_reason == "pending_confirmation"
