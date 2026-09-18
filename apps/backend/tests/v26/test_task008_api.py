"""TASK-008 API / Interface Layer 测试。"""

import pytest
from fastapi import HTTPException

from app.api.v1 import action_execution as api
from app.services.action import contracts, manager, scheduler
from datetime import timedelta


class TestDebugEndpointsFlagOff:
    def test_list_404_when_flag_off(self):
        with pytest.raises(HTTPException) as exc:
            api.list_execution_actions(user_id="u1")
        assert exc.value.status_code == 404

    def test_detail_404_when_flag_off(self):
        with pytest.raises(HTTPException):
            api.get_execution_action("act_x")

    def test_metrics_404_when_flag_off(self):
        with pytest.raises(HTTPException):
            api.execution_metrics()


class TestDebugEndpointsFlagOn:
    def test_list_detail_schedule_metrics(self, monkeypatch):
        from app.core.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "action_execution_enabled", True)
        monkeypatch.setattr(settings, "action_debug_enabled", True)

        action = manager.create(
            user_id="u_api",
            action_type="create_reminder",
            params={"content": "调试"},
        )
        scheduler.schedule(
            action, when="delay", delay=timedelta(minutes=30), priority=120
        )
        rows = api.list_execution_actions(user_id="u_api")
        assert any(row["id"] == action.id for row in rows)

        detail = api.get_execution_action(action.id)
        assert detail["id"] == action.id
        assert detail["schedule"] is not None
        assert detail["schedule"]["priority"] == 120

        schedules = api.list_execution_schedules(limit=20)
        assert isinstance(schedules, list)

        metrics = api.execution_metrics(window_hours=24)
        assert "total" in metrics
        assert "success_rate" in metrics
        assert "by_status" in metrics
        assert metrics["total"] >= 1


class TestContractsFreeze:
    def test_three_api_contracts(self):
        frozen = contracts.freeze_contracts()
        assert frozen["manager"] is True
        assert frozen["executor"] is True
        assert frozen["result"] is True
        assert frozen["integration_feedback"] is True
        assert frozen["scheduler_schedule"] is True

    def test_log_event_names(self):
        assert len(contracts.LOG_EVENTS) == 7
        assert "Action Created" in contracts.LOG_EVENTS
        assert "Action Retried" in contracts.LOG_EVENTS

    def test_manager_source_logs_events(self):
        source = open(manager.__file__, encoding="utf-8").read()
        assert "Action Created" in source
        assert "Action Cancelled" in source
        assert "Action Retried" in source
        sched_src = open(scheduler.__file__, encoding="utf-8").read()
        assert "Action Scheduled" in sched_src
