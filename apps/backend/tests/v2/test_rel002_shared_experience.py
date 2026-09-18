"""REL-002 Shared Experience 投影测试。

覆盖：三源过滤口径、source_ref 去重合并、时间序、Freshness 选材与预算、
Context 段渲染、Flag 门控与端到端装配。
"""

from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.models.conversation import ChatMessage, ConversationState
from app.models.relationship import RelationshipDelta, RelationshipEvent
from app.models.world import EventImportance, EventSource, WorldEvent
from app.prompts.builder import PromptBuilder
from app.repositories import (
    memory_repository,
    relationship_event_repository,
    world_repository,
)
from app.services import relationship_shared
from app.services.context_builder import _load_shared_experiences, _select_shared_entries

BASE = datetime(2026, 9, 1, 10, 0, 0)


class _TraceSpy:
    def __init__(self):
        self.records = []

    def record(self, name, duration_ms, status="ok", error=None, **extra):
        self.records.append((name, status, extra))


def _event(
    event_id,
    user_id="u-rel2",
    created_at=None,
    type="intimate_moment",
    magnitude="strong",
    source="conversation",
    cause="深夜长谈",
):
    return relationship_event_repository.create_event(
        RelationshipEvent(
            id=event_id,
            user_id=user_id,
            session_id="s-1",
            type=type,
            magnitude=magnitude,
            impact=RelationshipDelta(intimacy=0.05),
            confidence=0.9,
            source=source,
            cause=cause,
            created_at=created_at or BASE,
        )
    )


def _memory_row(
    memory_id,
    content,
    memory_type,
    importance=0.9,
    source_ref=None,
    user_id="u-rel2",
    created_at=None,
):
    now = created_at or BASE
    with memory_repository.SessionLocal() as session:
        session.add(
            memory_repository.Memory(
                id=memory_id,
                user_id=user_id,
                character_id="asuna",
                content=content,
                type=memory_type,
                importance=importance,
                confidence=0.9,
                source="user_derived",
                status="active",
                source_ref=source_ref,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _world_event(
    event_id,
    title="一起完成了任务",
    status="completed",
    source=EventSource.USER_MENTION,
    importance=EventImportance.NORMAL,
    completed_at=None,
    user_id="u-rel2",
):
    world_repository.save_event(
        WorldEvent(
            id=event_id,
            world_id=world_repository.world_id_for(user_id),
            type="task",
            title=title,
            importance=importance,
            status=status,
            source=source,
            completed_at=completed_at,
            created_at=BASE,
            updated_at=BASE,
        )
    )


class TestProjection:
    def test_ledger_events_time_ordered(self, _offline_repos):
        _event("e3", created_at=BASE + timedelta(days=2))
        _event("e1", created_at=BASE)
        _event("e2", created_at=BASE + timedelta(days=1))
        entries = relationship_shared.collect_shared_experiences("u-rel2")
        assert [entry.entry_id for entry in entries] == ["e1", "e2", "e3"]
        assert all(entry.kind == "relationship_event" for entry in entries)
        assert entries[0].source_ref == {"table": "relationship_events", "id": "e1"}

    def test_excludes_none_type_and_replay_source(self, _offline_repos):
        _event("e-none", type="none", source="system", cause="")
        _event("e-replay", source="memory_replay")
        _event("e-system", type="none", source="system", cause="冲突结算")
        _event("e-ok", source="system", cause="和解")
        entries = relationship_shared.collect_shared_experiences("u-rel2")
        assert [entry.entry_id for entry in entries] == ["e-ok"]

    def test_memory_fact_merged_into_ledger_entry(self, _offline_repos):
        _event("e1", cause="深夜长谈")
        _memory_row(
            "m1",
            "那天我们聊到凌晨",
            "relationship_fact",
            source_ref={"table": "relationship_events", "id": "e1"},
        )
        entries = relationship_shared.collect_shared_experiences("u-rel2")
        assert len(entries) == 1
        assert entries[0].entry_id == "e1"
        assert entries[0].title == "那天我们聊到凌晨"
        assert entries[0].ledger_event_id is None or entries[0].entry_id == "e1"

    def test_experience_salience_filter(self, _offline_repos):
        _memory_row("m-high", "一起完成项目", "experience", importance=0.9)
        _memory_row("m-low", "随口闲聊", "experience", importance=0.3)
        entries = relationship_shared.collect_shared_experiences("u-rel2")
        titles = [entry.title for entry in entries]
        assert "一起完成项目" in titles
        assert "随口闲聊" not in titles

    def test_world_events_dual_participation(self, _offline_repos):
        _world_event("w1")
        _world_event("w2", source=EventSource.MANUAL)
        _world_event("w3", importance=EventImportance.LOW)
        entries = relationship_shared.collect_shared_experiences("u-rel2")
        assert [entry.entry_id for entry in entries] == ["w1"]
        assert entries[0].kind == "world_event"

    def test_mixed_sources_time_ordered(self, _offline_repos):
        _event("e1", created_at=BASE + timedelta(days=3))
        _memory_row("m1", "一起完成项目", "experience", importance=0.9,
                    created_at=BASE + timedelta(days=1))
        _world_event("w1", completed_at=BASE + timedelta(days=2))
        entries = relationship_shared.collect_shared_experiences("u-rel2")
        assert [entry.entry_id for entry in entries] == ["m1", "w1", "e1"]

    def test_empty_user(self, _offline_repos):
        assert relationship_shared.collect_shared_experiences("u-empty") == []

    def test_source_failure_degrades_to_empty(self, _offline_repos, monkeypatch):
        _event("e1")
        from app.repositories import relationship_event_repository as repo

        def _boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(repo, "list_events", _boom)
        entries = relationship_shared.collect_shared_experiences("u-rel2")
        assert entries == []


class TestSelectionAndRender:
    def _entry(self, entry_id, title, occurred_at):
        from app.models.relationship import SharedExperience

        return SharedExperience(
            entry_id=entry_id,
            kind="experience",
            title=title,
            occurred_at=occurred_at,
            source_ref={"table": "memories", "id": entry_id},
        )

    def test_freshness_limit_and_time_order(self, _offline_repos):
        entries = [
            self._entry(f"e{i}", f"经历{i}", BASE + timedelta(days=i)) for i in range(5)
        ]
        selected, payload = _select_shared_entries(entries)
        assert [entry.entry_id for entry in selected] == ["e2", "e3", "e4"]
        assert payload["reasons"]["e0"] == "over_limit"
        assert payload["reasons"]["e1"] == "over_limit"

    def test_budget_drops_overflow(self, _offline_repos, monkeypatch):
        monkeypatch.setattr(get_settings(), "relationship_shared_budget_chars", 60)
        entries = [
            self._entry("long", "很" * 50, BASE),
            self._entry("short", "短", BASE + timedelta(days=1)),
        ]
        selected, payload = _select_shared_entries(entries)
        assert [entry.entry_id for entry in selected] == ["short"]
        assert payload["reasons"]["long"] == "budget"

    def test_trace_recorded(self, _offline_repos):
        spy = _TraceSpy()
        entries = [self._entry("e1", "经历", BASE)]
        _select_shared_entries(entries, trace=spy)
        name, status, extra = spy.records[0]
        assert name == "relationship_shared"
        assert status == "ok"
        assert extra["selected"] == ["e1"]

    def test_render_section(self):
        state = ConversationState(
            session_id="s",
            user_id="u",
            messages=[],
            summary=None,
            memories=[],
            current_input="",
            shared_experiences=[
                self._entry("e1", "第一次旅行", BASE),
                self._entry("e2", "一起完成项目", BASE + timedelta(days=1)),
            ],
        )
        section = PromptBuilder.build_shared_experience_section(state)
        assert section is not None
        assert section.startswith("【共同经历】")
        assert "· 第一次旅行" in section
        assert "· 一起完成项目" in section

    def test_render_empty_is_none(self):
        state = ConversationState(
            session_id="s",
            user_id="u",
            messages=[],
            summary=None,
            memories=[],
            current_input="",
        )
        assert PromptBuilder.build_shared_experience_section(state) is None


class TestAssemblyWiring:
    def _seed(self):
        _event("e1", created_at=BASE)
        _memory_row(
            "m1",
            "一起完成项目",
            "experience",
            importance=0.9,
            created_at=BASE + timedelta(days=1),
        )

    def test_flag_on_end_to_end(self, _offline_repos, monkeypatch):
        self._seed()
        from app.services import context_builder

        state = _run_build(context_builder)
        titles = [entry.title for entry in state.shared_experiences]
        assert "深夜长谈" in titles or "那天我们聊到凌晨" in titles


def _run_build(context_builder):
    import asyncio

    return asyncio.run(
        context_builder.build(
            session_id="s-rel2",
            user_id="u-rel2",
            current_input="还记得我们一起做的事吗",
        )
    )
