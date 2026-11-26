"""API-007 记忆域产品读面 / 用户写面测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.core.db import Memory, RuntimeTraceRow
from app.repositories import memory_repository, trace_repository
from app.services.memory import product_view
from app.services.memory.types import CANONICAL_MEMORY_TYPES

pytestmark = pytest.mark.unit


def _memory(**overrides) -> Memory:
    now = overrides.pop("now", timeutil.now())
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


def _trace(
    *,
    trace_id: str,
    kind: str = "turn",
    returned: list[str] | None = None,
    filtered: list[str] | None = None,
    started_at: datetime | None = None,
    turn_id: str | None = "t1",
) -> RuntimeTraceRow:
    extra: dict = {}
    if returned is not None:
        extra["returned"] = [{"id": mid} for mid in returned]
    if filtered is not None:
        extra["filtered"] = [{"id": mid} for mid in filtered]
    return RuntimeTraceRow(
        id=trace_id,
        kind=kind,
        user_id="u1",
        turn_id=turn_id,
        status="complete",
        started_at=started_at or timeutil.now(),
        duration_ms=1.0,
        steps=[{"name": product_view.RECEIPT_TRACE_STEP, "extra": extra}],
        events=[],
        token_usage={},
        meta={},
        created_at=timeutil.now(),
    )


def _seed_traces(*rows: RuntimeTraceRow) -> None:
    with trace_repository.SessionLocal() as session:
        session.add_all(list(rows))
        session.commit()


# --- 分组映射（§4.1.3 冻结表） ---


def test_group_table_covers_every_canonical_type():
    assert set(product_view.TYPE_TO_GROUP) == set(CANONICAL_MEMORY_TYPES)


def test_group_table_is_frozen():
    assert product_view.TYPE_TO_GROUP == {
        "user_preference": "preference",
        "behavior_pattern": "habit",
        "commitment": "goal",
        "milestone_event": "goal",
        "user_fact": "now",
        "experience": "now",
        "relationship_fact": "now",
    }


def test_group_order_and_labels_are_frozen():
    assert product_view.GROUP_ORDER == ("preference", "habit", "goal", "now")
    assert product_view.GROUP_LABELS == {
        "preference": "长期偏好",
        "habit": "习惯",
        "goal": "目标",
        "now": "当下",
    }


def test_unmapped_type_fails_loudly():
    with pytest.raises(product_view.UnknownMemoryTypeError):
        product_view.group_for("not_a_memory_type")


# --- 读面口径（D5） ---


def test_groups_always_four_in_order_even_when_empty(db_session_factory):
    result = product_view.list_product_memories("u-none")
    assert [group.kind for group in result.groups] == ["preference", "habit", "goal", "now"]
    assert [group.label for group in result.groups] == ["长期偏好", "习惯", "目标", "当下"]
    assert result.total == 0
    assert all(group.items == [] for group in result.groups)


def test_only_active_rows_are_visible(db_session_factory):
    _seed(
        _memory(id="a", status="active"),
        _memory(id="f", status="forgotten", forgotten_at=timeutil.now()),
        _memory(id="d", status="decayed"),
        _memory(id="s", status="superseded"),
        _memory(id="i", status="invalidated"),
    )
    result = product_view.list_product_memories("u1")
    visible = [item.id for group in result.groups for item in group.items]
    assert visible == ["a"]
    assert result.total == 1


def test_total_matches_group_sum(db_session_factory):
    _seed(
        _memory(id="a", type="user_preference"),
        _memory(id="b", type="behavior_pattern"),
        _memory(id="c", type="commitment"),
        _memory(id="d", type="user_fact"),
    )
    result = product_view.list_product_memories("u1")
    assert result.total == sum(len(group.items) for group in result.groups) == 4





def test_added_this_week_counts_only_current_week(db_session_factory):
    _seed(
        _memory(id="fresh", created_at=timeutil.now()),
        _memory(id="old", created_at=timeutil.now() - timedelta(days=30)),
    )
    assert product_view.list_product_memories("u1").added_this_week == 1


# --- 来源追溯（§4.1.4） ---


def test_source_count_is_one_plus_merge_chain(db_session_factory):
    _seed(
        _memory(id="solo", merge_chain=None),
        _memory(id="merged", merge_chain=["x", "y"]),
    )
    items = {item.id: item for group in product_view.list_product_memories("u1").groups for item in group.items}
    assert items["solo"].source_count == 1
    assert items["merged"].source_count == 3


def test_source_kind_prefers_source_ref_table(db_session_factory):
    _seed(_memory(id="a", source_ref={"table": "action_records"}))
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert item.source_kind == "action_records"
    assert item.source_label == "任务完成"


def test_source_kind_falls_back_to_source_column(db_session_factory):
    _seed(_memory(id="a", source="user_stated", source_ref=None))
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert item.source_kind == "user_stated"
    assert item.source_label == "你亲口说过"


def test_unknown_source_kind_is_shown_verbatim(db_session_factory):
    _seed(_memory(id="a", source_ref={"table": "some_new_table"}))
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert item.source_label == "some_new_table"


def test_last_updated_is_updated_at(db_session_factory):
    stamp = datetime(2026, 9, 1, 8, 30)
    _seed(_memory(id="a", updated_at=stamp))
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert item.last_updated == timeutil.ensure_aware(stamp).isoformat()


# --- 用途回执（§4.1.5） ---


def test_receipt_derived_from_retrieval_step(db_session_factory):
    _seed(_memory(id="m1"))
    _seed_traces(_trace(trace_id="tr1", kind="turn", returned=["m1"]))
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert [(r.kind, r.label) for r in item.usage_receipts] == [
        ("recall_turn", "已用于对话")
    ]
    assert item.usage_receipts[0].ref == "t1"


def test_receipt_kind_maps_to_purpose_label(db_session_factory):
    _seed(_memory(id="m1"))
    _seed_traces(_trace(trace_id="tr1", kind="autonomy_tick", returned=["m1"]))
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert item.usage_receipts[0].label == "已用于任务排序"


def test_filtered_entries_do_not_count_as_usage(db_session_factory):
    _seed(_memory(id="m1"))
    _seed_traces(_trace(trace_id="tr1", kind="turn", filtered=["m1"]))
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert item.usage_receipts == []


def test_receipt_keeps_only_newest_per_kind(db_session_factory):
    _seed(_memory(id="m1"))
    _seed_traces(
        _trace(
            trace_id="tr-old",
            kind="turn",
            returned=["m1"],
            started_at=timeutil.now() - timedelta(days=2),
            turn_id="old",
        ),
        _trace(
            trace_id="tr-new",
            kind="turn",
            returned=["m1"],
            started_at=timeutil.now(),
            turn_id="new",
        ),
    )
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert len(item.usage_receipts) == 1
    assert item.usage_receipts[0].ref == "new"


def test_receipts_degrade_without_failing_the_list(db_session_factory, monkeypatch):
    _seed(_memory(id="m1"))

    def _boom(*_args, **_kwargs):
        raise RuntimeError("trace store down")

    monkeypatch.setattr(trace_repository, "list_since", _boom)
    result = product_view.list_product_memories("u1")
    assert result.degraded is True
    assert result.total == 1
    assert result.groups[0].items[0].usage_receipts == []


def test_traces_of_other_users_are_ignored(db_session_factory):
    _seed(_memory(id="m1"))
    row = _trace(trace_id="tr1", kind="turn", returned=["m1"])
    row.user_id = "someone-else"
    _seed_traces(row)
    item = product_view.list_product_memories("u1").groups[0].items[0]
    assert item.usage_receipts == []


# --- 编辑写面（§4.1.6） ---


def test_edit_updates_content_and_keeps_provenance(db_session_factory):
    _seed(_memory(id="m1", source="user_derived", source_ref={"table": "conversation"}))
    item = product_view.edit_memory("m1", "u1", content="改成了新的偏好")
    assert item.content == "改成了新的偏好"
    assert item.type == "user_preference"
    assert item.source_kind == "conversation"

    stored = memory_repository.get_memory("m1")
    assert stored.source == "user_derived"
    assert stored.status == "active"


def test_edit_rejects_non_active_row(db_session_factory):
    _seed(_memory(id="m1", status="forgotten", forgotten_at=timeutil.now()))
    with pytest.raises(product_view.MemoryNotFoundError):
        product_view.edit_memory("m1", "u1", content="x")


def test_edit_rejects_other_users_row(db_session_factory):
    _seed(_memory(id="m1", user_id="u2"))
    with pytest.raises(product_view.MemoryForbiddenError):
        product_view.edit_memory("m1", "u1", content="x")


def test_edit_missing_row(db_session_factory):
    with pytest.raises(product_view.MemoryNotFoundError):
        product_view.edit_memory("nope", "u1", content="x")


# --- 遗忘写面（§4.1.7） ---


def test_forget_soft_deletes_and_keeps_the_row(db_session_factory):
    _seed(_memory(id="m1"))
    forgotten_at = product_view.forget_memory_for_user("m1", "u1")
    assert forgotten_at

    facts = product_view.row_facts(["m1"])["m1"]
    assert facts["status"] == "forgotten"
    assert facts["forgotten_at"] is not None
    assert product_view.list_product_memories("u1").total == 0


def test_forget_is_idempotent_and_keeps_first_timestamp(db_session_factory):
    _seed(_memory(id="m1"))
    first = product_view.forget_memory_for_user("m1", "u1")
    second = product_view.forget_memory_for_user("m1", "u1")
    assert first == second


@pytest.mark.parametrize("status", ["decayed", "superseded", "invalidated"])
def test_forget_rejects_non_active_non_forgotten(db_session_factory, status):
    _seed(_memory(id="m1", status=status))
    with pytest.raises(product_view.MemoryNotFoundError):
        product_view.forget_memory_for_user("m1", "u1")


@pytest.mark.parametrize("status", ["decayed", "superseded", "invalidated"])
def test_edit_rejects_non_active(db_session_factory, status):
    """`decayed` / `forgotten` 不在 `UserMemory.status` 值域内，守卫必须走原始列读。"""
    _seed(_memory(id="m1", status=status))
    with pytest.raises(product_view.MemoryNotFoundError):
        product_view.edit_memory("m1", "u1", content="x")


def test_forget_rejects_other_users_row(db_session_factory):
    _seed(_memory(id="m1", user_id="u2"))
    with pytest.raises(product_view.MemoryForbiddenError):
        product_view.forget_memory_for_user("m1", "u1")


def test_forget_missing_row(db_session_factory):
    with pytest.raises(product_view.MemoryNotFoundError):
        product_view.forget_memory_for_user("nope", "u1")
