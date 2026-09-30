"""AUTO-001 调度收敛测试（architecture.md §15/§24，Gap G4）。

life_loop 是唯一 tick 源（`autonomy_worker` 兜底源已随 v2 开关删除）；
同一 Trigger 跨 tick 不重复消费——一次性 followup 由 claim 一次性语义
保证，重检型 inactivity 由 proactive_actions dedupe_key/深度 1 抑制重复入队。
"""

import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.models.autonomy import ProactiveAction
from app.repositories import proactive_repository
from app.services.autonomy import trigger as trigger_evaluator

NOW = datetime(2026, 9, 7, 12, 0, 0)


@pytest.fixture()
def life_loop_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings()
    yield
    trigger_evaluator._followup_registry.clear()


def test_one_shot_trigger_claimed_once_across_tick_sources(
    db_session_factory, life_loop_on
):
    trigger_evaluator.register_followup(
        "u1",
        due_at=NOW - timedelta(minutes=1),
        summary="面试提醒",
        dedupe_key="followup:u1:面试",
    )
    first = trigger_evaluator.poll_due_followup("u1", NOW)
    assert first is not None
    assert first.type == "scheduled_followup"
    second = trigger_evaluator.poll_due_followup("u1", NOW)
    assert second is None


def test_recheck_trigger_duplicate_enqueue_suppressed(db_session_factory, life_loop_on):
    dedupe_key = f"inactivity:u1:m1:{uuid.uuid4().hex[:8]}"

    def _action() -> ProactiveAction:
        return ProactiveAction(
            id=uuid.uuid4().hex,
            user_id="u1",
            session_id="s1",
            trigger_type="conversation_inactivity",
            dedupe_key=dedupe_key,
            intention="check_in",
            reason="闲置关心",
            created_at=NOW,
            updated_at=NOW,
        )

    assert proactive_repository.enqueue(_action()) is True
    assert proactive_repository.enqueue(_action()) is False
    assert proactive_repository.has_non_terminal("u1") is True
