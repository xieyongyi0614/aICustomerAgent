"""API-003 turn_meta.memory_refs 契约测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.memory import UserMemory
from app.services.memory.refs import MEMORY_REF_LABEL_MAX, build_memory_refs, memory_ref_label

pytestmark = pytest.mark.unit


def _mem(content: str, *, mid: str = "m1", status: str = "active", kind: str = "user_preference") -> UserMemory:
    now = datetime.now(timezone.utc)
    return UserMemory(
        id=mid,
        user_id="u1",
        character_id="asuna",
        type=kind,  # type: ignore[arg-type]
        content=content,
        importance=0.5,
        status=status,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )


def test_no_refs_returns_none_not_empty_list():
    assert build_memory_refs(None) is None
    assert build_memory_refs([]) is None


def test_refs_when_memories_present():
    refs = build_memory_refs([_mem("喜欢海边旅行"), _mem("预算偏紧", mid="m2", kind="user_fact")])
    assert refs == [
        {"id": "m1", "kind": "user_preference", "label": "喜欢海边旅行"},
        {"id": "m2", "kind": "user_fact", "label": "预算偏紧"},
    ]


def test_label_truncates_at_12_chars():
    long = "一二三四五六七八九十一二三四是"
    label = memory_ref_label(long)
    assert len(label) == MEMORY_REF_LABEL_MAX + 1
    assert label.endswith("…")
    assert label.startswith("一二三")


def test_blank_content_excluded():
    assert build_memory_refs([_mem("   ")]) is None


def test_non_active_excluded():
    assert build_memory_refs([_mem("旧的", status="superseded")]) is None  # type: ignore[arg-type]


def test_label_no_llm_rewrite():
    assert memory_ref_label("午饭 35 元") == "午饭 35 元"
