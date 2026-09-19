"""V2.6.1 P1：Flag 治理（v26 去门控语义反转：链规则已消失）与 Manager 退避守卫。"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.settings import Settings, get_settings
from app.core.settings.enablement import enablement_violations
from app.models.action import ActionResult
from app.repositories import action_repository
from app.services.action import manager

REMOVED_V26_FLAGS = (
    "action_execution_enabled",
    "action_scheduler_enabled",
    "action_result_enabled",
    "action_feedback_enabled",
    "action_debug_enabled",
)


class TestEnvExampleRegistration:
    def test_env_example_has_no_v26_flag_keys(self):
        from pathlib import Path

        example = Path(__file__).resolve().parents[2] / ".env.example"
        text = example.read_text(encoding="utf-8")
        for flag in REMOVED_V26_FLAGS:
            assert flag.upper() not in text, f".env.example 残留 {flag}"
        assert "ACTION_EXECUTING_TIMEOUT_MINUTES" in text


class TestEnablementChain:
    def test_v26_chain_rules_are_gone(self):
        settings = get_settings()
        assert enablement_violations(settings) == []

    def test_removed_flags_are_absent_from_settings(self):
        for flag in REMOVED_V26_FLAGS:
            assert flag not in Settings.model_fields, flag


class TestMultistepDecision:
    def test_plan_max_steps_stays_one(self):
        assert get_settings().action_plan_max_steps == 1


class TestExecuteBackoffGuard:
    def test_execute_holds_when_next_retry_in_future(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_enabled", True)
        action = manager.create(
            user_id="u_backoff",
            action_type="remember_fact",
            params={"fact": "退避守卫"},
        )
        record = action_repository.get_record(action.id)
        record.status = "executing"
        record.next_retry_at = datetime.now() + timedelta(minutes=5)
        action_repository.save_record(record)

        result = asyncio.run(manager.execute(action.id))
        assert result is None
        reloaded = action_repository.get_record(action.id)
        assert reloaded is not None
        assert reloaded.status == "executing"

    def test_execute_proceeds_when_backoff_elapsed(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_enabled", True)
        monkeypatch.setattr(settings, "world_enabled", True)
        from app.application import world_engine

        world_engine.ensure_world("u_backoff_ok")
        action = manager.create(
            user_id="u_backoff_ok",
            action_type="create_reminder",
            params={
                "content": "过期退避",
                "due_at": (datetime.now() + timedelta(hours=1)).isoformat(),
            },
        )
        record = action_repository.get_record(action.id)
        record.status = "planned"
        record.next_retry_at = datetime.now() - timedelta(seconds=1)
        action_repository.save_record(record)

        result = asyncio.run(manager.execute(action.id))
        assert result is not None
        assert isinstance(result, ActionResult)
        reloaded = action_repository.get_record(action.id)
        assert reloaded is not None
        assert reloaded.status == "succeeded"
