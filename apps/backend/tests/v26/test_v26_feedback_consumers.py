"""V2.6.1 REF-003：反馈唯一入口与三面消费者。"""

import asyncio
from datetime import datetime, timedelta

from app.application import action_engine, world_engine
from app.application.autonomy_engine import collect_facts
from app.models.action import ActionEffect, ActionResult
from app.repositories import action_repository
from app.services.action import integration, manager
from app.services.planning.executor_bridge import PlanExecutorBridge, _normalize
from app.services.reflection import evidence as reflection_evidence


def _due_at(hours: int = 2) -> str:
    return (datetime.now() + timedelta(hours=hours)).isoformat()


def _enabled(monkeypatch, **flags):
    settings_flags = {
        "action_enabled": True,
        "world_enabled": True,
    }
    settings_flags.update(flags)
    from app.core.settings import get_settings

    settings = get_settings()
    for key, value in settings_flags.items():
        monkeypatch.setattr(settings, key, value)
    return settings


class TestUniqueEntry:
    def test_main_path_calls_apply_result_feedback(self):
        source = open(action_engine.__file__, encoding="utf-8").read()
        assert "apply_result_feedback" in source
        assert "_apply_feedback" in source
        assert "integrate_result(record, result)" not in source

    def test_integrate_result_does_not_inline_feedback(self):
        source = open(action_engine.__file__, encoding="utf-8").read()
        assert "feedback_payload" not in source

    def test_feedback_on_writes_projection_keys(self, monkeypatch):
        _enabled(monkeypatch)
        world_engine.ensure_world("u_fb_main")
        action = manager.create(
            user_id="u_fb_main",
            action_type="create_reminder",
            params={"content": "反馈主路径", "due_at": _due_at()},
        )
        result = asyncio.run(manager.execute(action.id))
        assert result is not None
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert isinstance(loaded.result, dict)
        assert "feedback_kinds" in loaded.result
        assert "temporary_execution" in loaded.result
        assert "plan_step" in loaded.result
        assert "world" in loaded.result["feedback_kinds"]
        assert "payload" in loaded.result


class TestAutonomyConsumer:
    def test_collect_facts_reads_recent_feedback(self, monkeypatch):
        _enabled(monkeypatch)
        world_engine.ensure_world("u_fb_aut")
        action = manager.create(
            user_id="u_fb_aut",
            action_type="create_reminder",
            params={"content": "自治反馈", "due_at": _due_at()},
        )
        asyncio.run(manager.execute(action.id))
        facts = collect_facts("u_fb_aut")
        assert facts, "action_enabled on 时 facts 不能为空"
        recent = facts.get("recent_feedback") or []
        assert recent, "collect_facts 必须消费 feedback 投影"
        assert recent[0]["action"] == "create_reminder"
        assert "world" in (recent[0].get("feedback_kinds") or [])
        assert recent[0].get("temporary_execution") is False


class TestReflectionConsumer:
    def test_window_facts_include_feedback_kinds(self, monkeypatch):
        _enabled(monkeypatch)
        world_engine.ensure_world("u_fb_ref")
        action = manager.create(
            user_id="u_fb_ref",
            action_type="create_reminder",
            params={"content": "反思反馈", "due_at": _due_at()},
        )
        asyncio.run(manager.execute(action.id))
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        # 内部能力无 tool_id 时证据窗跳过——手工补一步带 tool_id 的步骤验证反馈透传
        if loaded.steps:
            step = dict(loaded.steps[0])
            step["tool_id"] = "builtin.reminder.create"
            loaded.steps = [step]
            action_repository.save_record(loaded)
        facts = reflection_evidence._window_facts(
            "u_fb_ref", datetime.now(), window_days=7
        )
        assert facts, "带 tool_id 的步骤必须进证据窗"
        # v26 去门控裁决 B：工具路径效果含 memory+world，断言改子集语义。
        assert "world" in facts[0].observations.get("feedback_kinds")
        assert facts[0].observations.get("temporary_execution") is False


class TestPlanningConsumer:
    def test_normalize_uses_to_plan_step_outcome_projection(self, monkeypatch):
        _enabled(monkeypatch)
        world_engine.ensure_world("u_fb_plan")
        action = manager.create(
            user_id="u_fb_plan",
            action_type="create_reminder",
            params={"content": "计划反馈", "due_at": _due_at()},
            source="plan",
        )
        asyncio.run(manager.execute(action.id))
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"

        class Step:
            index = 1
            tool_id = ""
            observation_keys = []

        outcome = _normalize(Step(), loaded, datetime.now())
        assert outcome.status == "succeeded"
        assert outcome.action_id == loaded.id
        assert outcome.attempt >= 1

    def test_to_plan_step_outcome_called_in_bridge_source(self):
        source = open(
            PlanExecutorBridge.__init__.__code__.co_filename, encoding="utf-8"
        ).read()
        assert "to_plan_step_outcome" in source
        assert "_outcome_from_result_projection" in source


class TestApplyResultFeedbackDirect:
    def test_apply_feedback_extends_stored_result(self, monkeypatch):
        _enabled(monkeypatch)
        action = manager.create(
            user_id="u_fb_direct",
            action_type="remember_fact",
            params={"fact": "直接反馈事实"},
        )
        record = action_repository.get_record(action.id)
        record.status = "succeeded"
        record.result = {
            "status": "succeeded",
            "effects": [{"kind": "memory", "ref": "m9", "detail": "已记住"}],
            "payload": {"memory_id": "m9"},
        }
        action_repository.save_record(record)
        result = ActionResult(
            status="succeeded",
            effects=[ActionEffect(kind="memory", ref="m9", detail="已记住")],
            observations={"memory_id": "m9"},
        )
        summary = integration.apply_result_feedback(record, result)
        assert summary["mode"] == "v26"
        assert summary["feedback"]["feedback_kinds"] == ["memory"]
        assert summary["feedback"]["temporary_execution"] is False
        reloaded = action_repository.get_record(action.id)
        assert reloaded is not None
        assert reloaded.result.get("feedback_kinds") == ["memory"]
