"""V2.6.1 P1：Flag 治理（登记/启用链）与 Manager 退避守卫。"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.core.settings.enablement import (
    enablement_violations,
    validate_enablement_chain,
)
from app.core.settings._shared import SettingsError
from app.core.settings.action_execution import V26_SUB_FLAGS
from app.models.action import ActionResult
from app.repositories import action_repository
from app.services.action import manager


class TestEnvExampleRegistration:
    def test_env_example_has_v26_flags(self):
        from pathlib import Path

        example = Path(__file__).resolve().parents[2] / ".env.example"
        text = example.read_text(encoding="utf-8")
        for flag in (
            "ACTION_EXECUTION_ENABLED",
            "ACTION_SCHEDULER_ENABLED",
            "ACTION_RESULT_ENABLED",
            "ACTION_FEEDBACK_ENABLED",
            "ACTION_DEBUG_ENABLED",
            "ACTION_EXECUTING_TIMEOUT_MINUTES",
        ):
            assert flag in text, f".env.example 缺少 {flag}"


class TestEnablementChain:
    def test_master_requires_action_enabled(self):
        settings = get_settings()
        original = settings.action_enabled
        original_v26 = settings.action_execution_enabled
        try:
            settings.action_enabled = False
            settings.action_execution_enabled = True
            violations = enablement_violations(settings)
            assert any("action_execution_enabled 要求 action_enabled" in v for v in violations)
        finally:
            settings.action_enabled = original
            settings.action_execution_enabled = original_v26

    def test_sub_flag_requires_master(self):
        settings = get_settings()
        original_v26 = settings.action_execution_enabled
        original_sched = settings.action_scheduler_enabled
        original_action = settings.action_enabled
        try:
            settings.action_enabled = True
            settings.action_execution_enabled = False
            settings.action_scheduler_enabled = True
            violations = enablement_violations(settings)
            assert any(
                "action_scheduler_enabled 要求 action_execution_enabled" in v
                for v in violations
            )
        finally:
            settings.action_enabled = original_action
            settings.action_execution_enabled = original_v26
            settings.action_scheduler_enabled = original_sched

    def test_sub_flags_cover_master_gate(self):
        assert "action_scheduler_enabled" in V26_SUB_FLAGS


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
        monkeypatch.setattr(settings, "action_execution_enabled", False)
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
