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


def test_create_collapses_double_submit(db_session_factory):
    first = task_service.create("u-dup", "完成备忘录开发")
    second = task_service.create("u-dup", "完成备忘录开发")
    assert second.id == first.id
    assert len(task_service.list_tasks("u-dup")) == 1


def test_create_keeps_distinct_titles(db_session_factory):
    task_service.create("u-distinct", "完成备忘录开发")
    task_service.create("u-distinct", "写周报")
    assert len(task_service.list_tasks("u-distinct")) == 2


def test_create_keeps_same_title_across_kinds(db_session_factory):
    memo = task_service.create("u-kind", "看牙医", kind="memo")
    task = task_service.create("u-kind", "看牙医", kind="task")
    assert memo.id != task.id
    assert len(task_service.list_tasks("u-kind")) == 2


def test_api_router_has_no_repositories_import():
    import inspect

    src = inspect.getsource(tasks_api)
    assert "app.repositories" not in src


def test_list_tasks_status_done_carries_completed_at(db_session_factory):
    row = task_service.create("u-done", "回复导师邮件")
    task_service.complete(row.id)
    done_rows = task_service.list_tasks("u-done", status="done")
    assert [r["id"] for r in done_rows] == [row.id]
    assert done_rows[0]["status"] == "done"
    assert done_rows[0]["completed_at"] is not None


def test_list_tasks_all_includes_open_and_done_not_cancelled(
    db_session_factory,
):
    open_row = task_service.create("u-all", "给妈妈回电话")
    done_row = task_service.create("u-all", "回复导师邮件")
    task_service.complete(done_row.id)
    cancelled_row = task_service.create("u-all", "已取消的事")
    task_service.delete(cancelled_row.id)
    rows = task_service.list_tasks("u-all", status="all")
    ids = {r["id"] for r in rows}
    assert ids == {open_row.id, done_row.id}
    statuses = {r["id"]: r["status"] for r in rows}
    assert statuses[open_row.id] == "open"
    assert statuses[done_row.id] == "done"


def test_list_tasks_default_status_stays_open(db_session_factory):
    row = task_service.create("u-default", "买菜")
    done_row = task_service.create("u-default", "回复导师邮件")
    task_service.complete(done_row.id)
    rows = task_service.list_tasks("u-default")
    assert [r["id"] for r in rows] == [row.id]


def test_completed_at_survives_endpoint_mapping(db_session_factory):
    row = task_service.create("u-api", "15:00 产品方案对齐")
    done = task_service.complete(row.id)
    assert done.completed_at is not None
