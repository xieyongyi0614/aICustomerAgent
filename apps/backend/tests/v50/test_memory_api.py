"""API-007 记忆端点契约与分层合规测试。"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import memory as memory_api
from app.api.v1.schemas import MemoryEditIn
from app.core.db import Memory
from app.repositories import memory_repository

pytestmark = pytest.mark.unit


def _memory(**overrides) -> Memory:
    now = overrides.pop("now", datetime.now())
    values = {
        "id": "m1",
        "user_id": "u1",
        "content": "喜欢海边旅行",
        "type": "user_preference",
        "importance": 0.6,
        "character_id": "asuna",
        "confidence": 0.7,
        "source": "user_stated",
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Memory(**values)


def _seed(*rows: Memory) -> None:
    with memory_repository.SessionLocal() as session:
        session.add_all(list(rows))
        session.commit()


def test_api_module_imports_no_forbidden_layer():
    """判据 ①：api 层零仓储 / 零 ORM / 零 langchain / 零 application 依赖。

    用 AST 取真实 import 节点，而非文本扫描——docstring 里提到这些名字不应算依赖。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(memory_api))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = sorted(
        name
        for name in imported
        if name.startswith(
            ("app.repositories", "app.core.db", "app.application", "langchain")
        )
    )
    assert forbidden == []
    assert "app.services.memory2" in imported


def test_list_items_returns_grouped_envelope(db_session_factory):
    _seed(_memory(id="m1", type="user_preference"), _memory(id="m2", type="user_fact"))
    payload = memory_api.list_items(limit=200, user_id="u1")
    assert payload.total == 2
    assert [group.kind for group in payload.groups] == [
        "preference",
        "habit",
        "goal",
        "now",
    ]
    assert payload.groups[0].items[0].id == "m1"
    assert payload.groups[3].items[0].id == "m2"
    assert payload.degraded is False
    assert payload.generated_at


def test_list_items_does_not_leak_mechanism_fields(db_session_factory):
    _seed(_memory(id="m1"))
    payload = memory_api.list_items(limit=200, user_id="u1")
    dumped = payload.groups[0].items[0].model_dump()
    for forbidden in ("status", "salience", "confidence", "importance", "embedding"):
        assert forbidden not in dumped


def test_patch_returns_updated_item(db_session_factory):
    _seed(_memory(id="m1"))
    item = memory_api.update_item(
        memory_id="m1",
        body=MemoryEditIn(content="改成新的偏好"),
        user_id="u1",
    )
    assert item.content == "改成新的偏好"
    assert item.last_updated


def test_patch_maps_forbidden_to_403(db_session_factory):
    _seed(_memory(id="m1", user_id="u2"))
    with pytest.raises(HTTPException) as exc:
        memory_api.update_item(
            memory_id="m1", body=MemoryEditIn(content="x"), user_id="u1"
        )
    assert exc.value.status_code == 403


def test_patch_maps_missing_to_404(db_session_factory):
    with pytest.raises(HTTPException) as exc:
        memory_api.update_item(
            memory_id="nope", body=MemoryEditIn(content="x"), user_id="u1"
        )
    assert exc.value.status_code == 404


def test_patch_non_active_returns_404_not_403(db_session_factory):
    _seed(_memory(id="m1", status="forgotten", forgotten_at=datetime.now()))
    with pytest.raises(HTTPException) as exc:
        memory_api.update_item(
            memory_id="m1", body=MemoryEditIn(content="x"), user_id="u1"
        )
    assert exc.value.status_code == 404


def test_forget_returns_audit_timestamp(db_session_factory):
    _seed(_memory(id="m1"))
    payload = memory_api.forget_item(memory_id="m1", user_id="u1")
    assert payload.id == "m1"
    assert payload.status == "forgotten"
    assert payload.forgotten_at


def test_forget_maps_forbidden_to_403(db_session_factory):
    _seed(_memory(id="m1", user_id="u2"))
    with pytest.raises(HTTPException) as exc:
        memory_api.forget_item(memory_id="m1", user_id="u1")
    assert exc.value.status_code == 403


def test_forget_maps_missing_to_404(db_session_factory):
    with pytest.raises(HTTPException) as exc:
        memory_api.forget_item(memory_id="nope", user_id="u1")
    assert exc.value.status_code == 404


@pytest.mark.parametrize("bad", ["", "   ", "x" * 501])
def test_edit_content_out_of_range_is_rejected(bad):
    with pytest.raises(ValidationError):
        MemoryEditIn(content=bad)


def test_edit_content_is_trimmed():
    assert MemoryEditIn(content="  海边  ").content == "海边"


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_edit_importance_out_of_range_is_rejected(bad):
    with pytest.raises(ValidationError):
        MemoryEditIn(content="x", importance=bad)


def test_edit_importance_defaults_to_none():
    assert MemoryEditIn(content="x").importance is None
