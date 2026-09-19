"""V2.6.1 REF-004/005：到期调度执行消费端 + trigger 终态收口。"""

import asyncio
from datetime import datetime, timedelta

from app.application import world_engine
from app.repositories import action_repository, trigger_registry_repository
from app.repositories.trigger_registry_repository import TERMINAL_STATUSES
from app.services.action import manager, scheduler


def _enabled(monkeypatch, **extra):
    from app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "action_enabled", True)
    monkeypatch.setattr(settings, "world_enabled", True)
    for key, value in extra.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def _schedule_due(user_id: str, content: str = "早上学习"):
    world_engine.ensure_world(user_id)
    action = manager.create(
        user_id=user_id,
        action_type="create_reminder",
        params={
            "content": content,
            "due_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        },
    )
    item = scheduler.schedule(
        action, when="delay", scheduled_at=datetime.now() - timedelta(minutes=1)
    )
    return action, item


class TestScheduleExecution:
    def test_due_schedule_executes_and_closes(self, monkeypatch):
        _enabled(monkeypatch)
        action, _ = _schedule_due("u_t3_exec")
        result = asyncio.run(scheduler.step_action_schedule(datetime.now()))
        assert result["status"] == "done"
        assert result["claimed"] >= 1
        assert result["executed"] >= 1

        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        schedule = action_repository.get_schedule(action.id)
        assert schedule is not None
        assert schedule.status == "executed"

    def test_trigger_done_after_execute(self, monkeypatch):
        _enabled(monkeypatch)
        action, _ = _schedule_due("u_t3_trig")
        asyncio.run(scheduler.step_action_schedule(datetime.now()))
        row = trigger_registry_repository.get(f"action_schedule:{action.id}")
        assert row is not None
        assert row.status == "done"

    def test_second_tick_does_not_revive_trigger(self, monkeypatch):
        _enabled(monkeypatch)
        action, _ = _schedule_due("u_t3_norevive")
        first = asyncio.run(scheduler.step_action_schedule(datetime.now()))
        assert first["executed"] >= 1
        second = asyncio.run(scheduler.step_action_schedule(datetime.now() + timedelta(seconds=1)))
        assert second["executed"] == 0
        row = trigger_registry_repository.get(f"action_schedule:{action.id}")
        assert row is not None
        assert row.status == "done"
        # register 防复活
        status = trigger_registry_repository.register(
            user_id="u_t3_norevive",
            trigger_type="action_due",
            trigger_key=f"action_schedule:{action.id}",
            due_at=datetime.now(),
            payload={"kind": "action_schedule", "action_id": action.id},
        )
        assert status in TERMINAL_STATUSES

    def test_not_due_schedule_skipped(self, monkeypatch):
        _enabled(monkeypatch)
        world_engine.ensure_world("u_t3_future")
        action = manager.create(
            user_id="u_t3_future",
            action_type="create_reminder",
            params={"content": "未到期", "due_at": (datetime.now() + timedelta(hours=2)).isoformat()},
        )
        scheduler.schedule(
            action, when="delay", scheduled_at=datetime.now() + timedelta(hours=1)
        )
        result = asyncio.run(scheduler.step_action_schedule(datetime.now()))
        assert result["executed"] == 0
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "planned"
        schedule = action_repository.get_schedule(action.id)
        assert schedule is not None
        assert schedule.status == "scheduled"

    def test_terminal_record_closes_schedule_without_reexec(self, monkeypatch):
        _enabled(monkeypatch)
        action, _ = _schedule_due("u_t3_pre")
        loaded = action_repository.get_record(action.id)
        loaded.status = "succeeded"
        action_repository.save_record(loaded)
        result = asyncio.run(scheduler.step_action_schedule(datetime.now()))
        schedule = action_repository.get_schedule(action.id)
        assert schedule is not None
        assert schedule.status == "executed"
        row = trigger_registry_repository.get(f"action_schedule:{action.id}")
        assert row is None or row.status == "done"

    def test_end_to_end_morning_reminder(self, monkeypatch):
        """「明天早上提醒我」：Plan-like 建 Action → schedule → 到期执行 → 成功。"""
        _enabled(monkeypatch)
        action, item = _schedule_due("u_t3_e2e", content="明早学习")
        assert item.status == "scheduled"
        assert action_repository.get_record(action.id).status == "planned"
        stats = asyncio.run(scheduler.step_action_schedule(datetime.now() + timedelta(minutes=2)))
        assert stats["executed"] >= 1
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        step_result = (loaded.steps[0] or {}).get("result") or {}
        assert step_result.get("payload") or step_result.get("output")


class TestClaimSchedule:
    def test_claim_cas(self):
        world_engine.ensure_world("u_t3_cas")
        action = manager.create(
            user_id="u_t3_cas",
            action_type="create_reminder",
            params={"content": "CAS", "due_at": (datetime.now() + timedelta(hours=1)).isoformat()},
        )
        scheduler.schedule(action, when="delay", scheduled_at=datetime.now() - timedelta(minutes=1))
        claimed = action_repository.claim_due_schedule(action.id)
        assert claimed is not None
        assert claimed.status == "due"
        action_repository.mark_schedule_executed(action.id)
        assert action_repository.claim_due_schedule(action.id) is None
