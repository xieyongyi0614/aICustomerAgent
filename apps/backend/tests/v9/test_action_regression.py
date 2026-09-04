"""V9 Golden Regression：action_enabled=false 时字节级还原 V8.5（不产生任何行动痕迹）。"""

from datetime import datetime

import pytest

from app.application.action_engine import run_action_planning
from app.models.action import ActionIntent
from app.repositories import action_repository
from app.services.action.context import build_action_context, ActionContext


def _intent(action_type="create_reminder", **params):
    return ActionIntent(action_type=action_type, confidence="confident", params=params, dedupe_key="")


@pytest.mark.asyncio
async def test_disabled_planning_is_noop(override_settings, db_session_factory):
    override_settings(action_enabled=False)
    record = await run_action_planning("reg-user", _intent(content="喝水", due_at="20:00"), session_id="s1")
    assert record is None
    assert action_repository.list_records("reg-user") == []


def test_disabled_context_is_none(override_settings, db_session_factory):
    override_settings(action_enabled=False)
    assert build_action_context("reg-user") is None


def test_disabled_no_intent_in_turn_meta(override_settings, db_session_factory):
    from app.services.action.detector import detect_action_intent

    override_settings(action_enabled=False)
    assert detect_action_intent("帮我设个提醒", scene_state=None, world_ctx=None) is None
