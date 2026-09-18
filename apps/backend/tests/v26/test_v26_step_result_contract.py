"""V2.6.1 REF-001 T1：Flag on 主路径 steps/result 全形态契约（新键 + 旧读键）。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.application import world_engine
from app.models.action import ActionResult, CapabilityResult
from app.repositories import action_repository
from app.services.action import manager
from app.services.action.executor import (
    step_extras_from_result,
    step_result_payload,
)
from app.services.action.result import from_capability_result, from_tool_execution

REQUIRED_RESULT_KEYS = {
    "id",
    "action_id",
    "status",
    "effects",
    "error",
    "failure_kind",
    "output",
    "metadata",
    "observations",
    "created_at",
}


def _due_at(hours: int = 2) -> str:
    return (datetime.now() + timedelta(hours=hours)).isoformat()


class TestProjectionFunctions:
    def test_from_capability_result_keeps_output(self):
        result = from_capability_result(
            CapabilityResult(
                status="succeeded",
                payload={
                    "world_event_id": "evt_1",
                    "memory_id": "mem_1",
                    "deferred_world_op": {"op": "create_event", "args": ["u1"]},
                },
                usage={"tokens": 3},
            ),
            action_id="act_proj",
        )
        assert result.status == "succeeded"
        assert result.output["world_event_id"] == "evt_1"
        assert result.output["deferred_world_op"]["op"] == "create_event"
        assert result.observations.get("world_event_id") == "evt_1"
        assert result.metadata["usage"] == {"tokens": 3}

    def test_from_tool_execution_keeps_tool_facts(self):
        execution = ToolExecutionLike = SimpleNamespace(
            status="succeeded",
            error=None,
            tool_id="builtin.query.environment",
            duration_ms=42,
            permission={"decision": "allow"},
            validation={"ok": True},
            result={
                "status": "succeeded",
                "payload": {"objects": [{"id": "o1"}]},
                "effects": [{"kind": "world", "ref": "evt_t", "detail": "query"}],
                "observations": {"objects_count": 1},
            },
        )
        result = from_tool_execution(execution, action_id="act_tool")
        assert result.status == "succeeded"
        assert result.output["objects"][0]["id"] == "o1"
        assert result.observations.get("objects_count") == 1
        assert result.metadata["tool_id"] == "builtin.query.environment"
        assert result.metadata["duration_ms"] == 42
        assert result.effects[0].kind == "world"

    def test_step_result_payload_dual_write(self):
        result = from_capability_result(
            CapabilityResult(
                status="succeeded",
                payload={"world_event_id": "evt_9", "failure_kind": None},
            ),
            action_id="act_dual",
        )
        step_result = step_result_payload(result)
        assert set(REQUIRED_RESULT_KEYS).issubset(step_result.keys())
        assert step_result["payload"]["world_event_id"] == "evt_9"
        extras = step_extras_from_result(result)
        assert "tool_id" in extras
        assert "duration_ms" in extras
        assert extras["duration_ms"] >= 0


class TestFlagOnInternalMainPath:
    def test_create_reminder_steps_full_shape(self, override_settings):
        override_settings(
            action_enabled=True,
            action_execution_enabled=True,
            world_enabled=True,
        )
        world_engine.ensure_world("u_t1_rem")
        action = manager.create(
            user_id="u_t1_rem",
            action_type="create_reminder",
            params={"content": "T1 提醒", "due_at": _due_at()},
        )
        result = __import__("asyncio").run(manager.execute(action.id))
        assert result is not None
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert loaded.steps, "主路径必须写 steps"
        step = loaded.steps[0]
        step_result = step.get("result") or {}
        for key in REQUIRED_RESULT_KEYS:
            assert key in step_result, f"steps[0].result 缺少契约键 {key}"
        assert "payload" in step_result
        assert step_result["status"] == "succeeded"
        assert "tool_id" in step
        assert "duration_ms" in step
        assert loaded.result is not None
        assert "payload" in loaded.result
        assert "status" in loaded.result
        assert loaded.result["status"] == "succeeded"

    def test_remember_fact_steps_full_shape(self, override_settings):
        override_settings(
            action_enabled=True,
            action_execution_enabled=True,
            world_enabled=True,
        )
        action = manager.create(
            user_id="u_t1_fact",
            action_type="remember_fact",
            params={"fact": "T1 记住事实"},
        )
        result = __import__("asyncio").run(manager.execute(action.id))
        assert result is not None
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        step_result = (loaded.steps[0] or {}).get("result") or {}
        assert "payload" in step_result
        assert "output" in step_result
        assert "observations" in step_result
        memory_id = (step_result.get("payload") or {}).get("memory_id") or (
            step_result.get("output") or {}
        ).get("memory_id")
        assert memory_id, "记忆效果引用必须进入旧读键 payload 或 output"

    def test_failed_path_still_full_shape(self, override_settings):
        override_settings(
            action_enabled=True,
            action_execution_enabled=True,
            world_enabled=True,
        )
        world_engine.ensure_world("u_t1_fail")
        action = manager.create(
            user_id="u_t1_fail",
            action_type="create_reminder",
            params={"content": "会失败", "due_at": "not-a-datetime"},
        )
        result = __import__("asyncio").run(manager.execute(action.id))
        assert result is not None
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "failed"
        step_result = (loaded.steps[0] or {}).get("result") or {}
        assert "payload" in step_result
        assert "status" in step_result
        assert step_result.get("failure_kind") or (
            step_result.get("payload") or {}
        ).get("failure_kind")
