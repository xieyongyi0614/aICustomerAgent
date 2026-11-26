"""TASK-003 Action Manager 六能力测试。"""

from datetime import datetime

import pytest

from app.models.action import Action, ActionResult, ActionIntent
from app.repositories import action_repository
from app.services.action import manager


def _create(user_id="u1", content="开会", source="conversation"):
    return manager.create(
        user_id=user_id,
        action_type="create_reminder",
        params={"content": content, "due": "明天"},
        source=source,
    )


class TestCreate:
    def test_create_defaults(self):
        action = _create()
        assert action.status == "created"
        assert action.type == "create_reminder"
        assert action.source == "conversation"
        assert action.priority == 100
        assert action.dedupe_key
        assert action.is_terminal() is False

    def test_create_from_intent(self):
        intent = ActionIntent(
            action_type="remember_fact",
            confidence="confident",
            params={"fact": "生日7月30日"},
            dedupe_key="intentkey123456",
        )
        action = manager.create(
            user_id="u1",
            action_type="remember_fact",
            source="plan",
            intent=intent,
            priority=150,
        )
        assert action.type == "remember_fact"
        assert action.source == "plan"
        assert action.dedupe_key == "intentkey123456"
        assert action.priority == 150
        assert action.parameters["fact"] == "生日7月30日"

    def test_create_same_dedupe_key(self):
        a = _create(content="买牛奶")
        b = _create(content="买牛奶")
        assert a.dedupe_key == b.dedupe_key
        assert a.id != b.id

    def test_create_event_driven_source(self):
        action = _create(source="event_driven")
        assert action.source == "event_driven"


class TestUpdate:
    def test_update_priority_and_params(self):
        action = _create()
        updated = manager.update(action.id, priority=200, params={"content": "改会"})
        assert updated is not None
        assert updated.priority == 200
        assert updated.parameters["content"] == "改会"
        assert updated.id == action.id
        assert updated.type == action.type
        assert updated.dedupe_key == action.dedupe_key

    def test_update_immutable_rejected(self):
        action = _create()
        with pytest.raises(ValueError):
            manager.update(action.id, action_type="query_environment")
        with pytest.raises(ValueError):
            manager.update(action.id, dedupe_key="newkey")
        with pytest.raises(ValueError):
            manager.update(action.id, id="other")
        with pytest.raises(ValueError):
            manager.update(action.id, status="failed")

    def test_update_unknown_rejected(self):
        action = _create()
        with pytest.raises(ValueError):
            manager.update(action.id, weird_field=1)

    def test_update_missing_returns_none(self):
        assert manager.update("act_missing", priority=1) is None


class TestQuery:
    def test_query_by_id(self):
        action = _create()
        loaded = manager.query(action.id)
        assert isinstance(loaded, Action)
        assert loaded.id == action.id

    def test_query_missing_returns_none(self):
        assert manager.query("act_missing") is None

    def test_query_by_user_and_status(self):
        _create(user_id="uq", content="a")
        action_b = _create(user_id="uq", content="b")
        manager.cancel(action_b.id, reason="test")
        created = manager.query(user_id="uq", status="created")
        assert isinstance(created, list)
        assert all(a.status == "created" for a in created)
        cancelled = manager.query(user_id="uq", status="cancelled")
        assert len(cancelled) >= 1

    def test_query_requires_filter(self):
        with pytest.raises(ValueError):
            manager.query()


class TestCancel:
    def test_cancel_created(self):
        action = _create()
        assert manager.cancel(action.id, reason="user_cancel") is True
        assert manager.get_status(action.id) == "cancelled"
        cancelled = manager.query(action.id)
        assert cancelled.result is None

    def test_cancel_twice_false(self):
        action = _create()
        assert manager.cancel(action.id) is True
        assert manager.cancel(action.id) is False

    def test_cancel_terminal_false(self):
        action = _create()
        record = action_repository.get_record(action.id)
        for status in ("succeeded", "failed", "executing"):
            record.status = status
            action_repository.save_record(record)
            assert manager.cancel(action.id) is False

    def test_cancel_missing_false(self):
        assert manager.cancel("act_missing") is False

    def test_cancel_does_not_touch_world(self):
        action = _create()
        source = open(
            manager.__file__, encoding="utf-8"
        ).read()
        # create/cancel path must not import world/memory bridges for side effects
        assert "world_engine" not in source
        assert "memory_policy" not in source
        assert "relationship_bridge" not in source


class TestGetStatus:
    def test_status_progression(self):
        action = _create()
        assert manager.get_status(action.id) == "created"
        manager.cancel(action.id)
        assert manager.get_status(action.id) == "cancelled"
        assert manager.get_status("act_missing") is None


class TestRetry:
    def test_retry_non_failed_returns_none(self):
        action = _create()
        import asyncio

        assert asyncio.run(manager.retry(action.id)) is None
        manager.cancel(action.id)
        assert asyncio.run(manager.retry(action.id)) is None

    def test_retry_missing_returns_none(self):
        import asyncio

        assert asyncio.run(manager.retry("act_missing")) is None

    def test_retry_reuses_dedupe_key(self):
        action = _create(content="重试测试")
        record = action_repository.get_record(action.id)
        record.status = "failed"
        action_repository.save_record(record)
        import asyncio

        asyncio.run(manager.retry(action.id))
        reloaded = manager.query(action.id)
        assert reloaded is not None
        assert reloaded.dedupe_key == action.dedupe_key
