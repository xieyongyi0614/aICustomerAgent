"""V9 /debug/actions 端点：列表 / 详情 / 手动重试 / 取消（V9-007 H-A7 审计入口）。"""

import pytest

from fastapi import HTTPException

from app.api.v1.action import (
    cancel_action,
    get_action,
    list_actions,
    retry_action,
)
from app.application.action_engine import new_record
from app.models.action import ActionIntent
from app.repositories import action_repository


def _intent(action_type="create_reminder", **params):
    return ActionIntent(action_type=action_type, confidence="confident", params=params, dedupe_key="")


def test_list_empty_returns_empty_list(override_settings, db_session_factory):
    override_settings()
    assert list_actions(user_id="dbg-user") == []


def test_list_and_get_roundtrip(override_settings, db_session_factory):
    override_settings()
    record = new_record(_intent(content="喝水", due_at="20:00"), "dbg-user", session_id="s1")
    record.status = "planned"
    action_repository.save_record(record)
    listed = list_actions(user_id="dbg-user")
    assert any(r["id"] == record.id for r in listed)
    got = get_action(record.id)
    assert got["id"] == record.id


def test_get_missing_404(override_settings, db_session_factory):
    override_settings()
    with pytest.raises(HTTPException) as exc:
        get_action("act_nonexistent_0000001")
    assert exc.value.status_code == 404


def test_cancel_planned_action(override_settings, db_session_factory):
    override_settings()
    record = new_record(_intent(content="取消测试", due_at="20:00"), "dbg-user", session_id="s1")
    record.status = "planned"
    action_repository.save_record(record)
    res = cancel_action(record.id)
    assert res["status"] == "cancelled"
    assert action_repository.get_record(record.id).gate_reason == "cancelled_by_user"


def test_retry_failed_action(override_settings, db_session_factory):
    override_settings()
    record = new_record(_intent(content="重试", due_at="20:00"), "dbg-user", session_id="s1")
    record.status = "failed"
    action_repository.save_record(record)
    res = retry_action(record.id)
    assert res["attempt"] == 2
