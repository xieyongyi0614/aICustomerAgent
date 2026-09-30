"""API-005 life_tasks 领域测试。"""

from __future__ import annotations

import pytest

from app.api.v1 import tasks as tasks_api
from app.services.life import tasks as task_service

pytestmark = pytest.mark.unit


def test_create_and_list_open(db_session_factory):
    row = task_service.create("u1", "回复导师邮件", tag="工作")
    assert row.status == "open"
    assert row.order_reason
    open_rows = task_service.list_open("u1")
    assert any(r["id"] == row.id for r in open_rows)


def test_complete_is_idempotent(db_session_factory):
    row = task_service.create("u2", "买菜")
    done = task_service.complete(row.id)
    assert done.status == "done"
    again = task_service.complete(row.id)
    assert again.status == "done"


def test_memo_kind_allowed(db_session_factory):
    row = task_service.create("u3", "下个月旅行", kind="memo")
    assert row.kind == "memo"
    assert task_service.memo_count("u3") == 1


def test_api_router_has_no_repositories_import():
    import inspect

    src = inspect.getsource(tasks_api)
    assert "app.repositories" not in src
