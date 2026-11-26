"""TASK-005 Action Scheduler 测试。"""

from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.models.action import Action
from app.services.action import manager, scheduler


def _action(content="学习", priority=100, action_id=None):
    action = manager.create(
        user_id="u1",
        action_type="create_reminder",
        params={"content": content, "due": "明早8点"},
        priority=priority,
    )
    if action_id is not None:
        return action.model_copy(update={"id": action_id})
    return action


class TestSchedule:
    def test_immediate(self):
        action = _action("立即")
        item = scheduler.schedule(action, when=None)
        assert item.when_type == "immediate"
        assert item.status == "scheduled"
        assert item.action_id == action.id

    def test_delay(self):
        action = _action("延迟")
        now = timeutil.now()
        item = scheduler.schedule(action, when="delay", delay=timedelta(minutes=30))
        assert item.when_type == "delay"
        assert item.scheduled_at >= now + timedelta(minutes=29)

    def test_cron_next_moment(self):
        action = _action("定时")
        item = scheduler.schedule(action, when="cron")
        assert item.when_type == "cron"
        assert item.scheduled_at > timeutil.now()

    def test_scheduled_at_explicit(self):
        action = _action("指定时刻")
        target = timeutil.now() + timedelta(hours=2)
        item = scheduler.schedule(action, when="delay", scheduled_at=target)
        assert abs((item.scheduled_at - target).total_seconds()) < 2

    def test_priority_override(self):
        action = _action("优先级", priority=50)
        item = scheduler.schedule(action, when="delay", delay=timedelta(minutes=1), priority=200)
        assert item.priority == 200

    def test_invalid_when(self):
        action = _action("非法")
        with pytest.raises(ValueError):
            scheduler.schedule(action, when="weekly")

    def test_delay_requires_offset(self):
        action = _action("缺参")
        with pytest.raises(ValueError):
            scheduler.schedule(action, when="delay")


class TestSortQueue:
    def test_priority_desc_then_time_then_id(self):
        now = timeutil.now()
        a = Action(id="b1", type="create_reminder", priority=100, scheduled_at=now)
        b = Action(id="a1", type="create_reminder", priority=200, scheduled_at=now + timedelta(minutes=5))
        c = Action(id="a0", type="create_reminder", priority=200, scheduled_at=now)
        d = Action(id="c1", type="create_reminder", priority=100, scheduled_at=now - timedelta(minutes=1))
        ordered = scheduler.sort_queue([a, b, c, d])
        assert [x.id for x in ordered] == ["a0", "a1", "c1", "b1"]

    def test_deterministic(self):
        now = timeutil.now()
        items = [
            Action(id="x", type="create_reminder", priority=100, scheduled_at=now),
            Action(id="y", type="create_reminder", priority=100, scheduled_at=now),
        ]
        first = [a.id for a in scheduler.sort_queue(items)]
        second = [a.id for a in scheduler.sort_queue(list(reversed(items)))]
        assert first == second == ["x", "y"]


class TestQueue:
    def test_due_and_next(self):
        past = _action("过去", priority=10)
        future = _action("未来", priority=90)
        scheduler.schedule(past, when="delay", scheduled_at=timeutil.now() - timedelta(minutes=1))
        scheduler.schedule(future, when="delay", scheduled_at=timeutil.now() + timedelta(hours=1))
        due = scheduler.due_actions(timeutil.now())
        due_ids = {a.id for a in due}
        assert past.id in due_ids
        assert future.id not in due_ids
        head = scheduler.next_action(timeutil.now())
        assert head is not None
        assert head.id == past.id

    def test_one_schedule_per_action(self):
        action = _action("唯一")
        scheduler.schedule(action, when="delay", delay=timedelta(minutes=5))
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            scheduler.schedule(action, when="delay", delay=timedelta(minutes=6))


class TestLifeLoopStep:
    def test_always_runs_when_mounted(self):
        """v26 去门控语义反转：双闸已删，维护步空载正常跑完（F.13 挂载点激活）。"""
        result = __import__("asyncio").run(scheduler.step_action_schedule(timeutil.now()))
        assert result["status"] == "done"
        assert result["claimed"] == 0

    def test_flag_on_claims_due(self, monkeypatch):
        from app.core.settings import get_settings

        settings = get_settings()
        action = _action("到期")
        scheduler.schedule(action, when="delay", scheduled_at=timeutil.now() - timedelta(minutes=1))
        result = __import__("asyncio").run(scheduler.step_action_schedule(timeutil.now()))
        assert result["status"] == "done"
        assert result["due"] >= 1


class TestReminderExample:
    def test_morning_reminder_chain(self):
        action = manager.create(
            user_id="u_morning",
            action_type="create_reminder",
            params={"content": "学习", "due_at": "2026-09-15T08:00:00"},
            source="conversation",
        )
        due_at = timeutil.now() + timedelta(hours=12)
        item = scheduler.schedule(
            action, when="delay", scheduled_at=due_at, priority=100
        )
        assert item.when_type == "delay"
        assert item.status == "scheduled"
        future_due = scheduler.due_actions(timeutil.now() + timedelta(hours=13))
        assert any(a.id == action.id for a in future_due)
