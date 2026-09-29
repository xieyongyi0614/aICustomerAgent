import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.core.settings import get_settings
from app.repositories import memory_repository
from app.services.context_builder import _select_retrieval_segment, _working_window
from app.services.memory import lifecycle, retriever
from app.services.memory.retriever import RankedMemories, RankedMemory


@pytest.fixture
def asm_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (memory_repository, retriever, lifecycle):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_buffer():
    lifecycle.reset_reinforce_buffer()
    yield
    lifecycle.reset_reinforce_buffer()


def _memory(id, content, importance=0.7, last_accessed_at=None, user_id="u1"):
    now = datetime.datetime.now()
    with memory_repository.SessionLocal() as session:
        session.add(
            memory_repository.Memory(
                id=id,
                user_id=user_id,
                character_id="asuna",
                content=content,
                type="user_fact",
                importance=importance,
                status="active",
                salience=0.8,
                created_at=now,
                updated_at=now,
                last_accessed_at=last_accessed_at,
            )
        )
        session.commit()


def _ranked(*contents, importance=0.7):
    now = datetime.datetime.now()
    items = []
    for index, content in enumerate(contents):
        memory = memory_repository.UserMemory(
            id=f"m{index}",
            user_id="u1",
            character_id="asuna",
            type="user_fact",
            content=content,
            importance=importance,
            created_at=now,
            updated_at=now,
        )
        items.append(RankedMemory(memory=memory, score=1.0 - index * 0.1))
    return RankedMemories(items=items, mode="structured")


class _Message:
    def __init__(self, content, role="human"):
        self.role = role
        self.content = content


class TestRetrievalBudget:
    def test_within_budget_all_selected(self, asm_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "memory_retrieval_budget", 800)
        ranked = _ranked("短记忆一", "短记忆二", "短记忆三")
        selected, used, dropped = _select_retrieval_segment(ranked)
        assert len(selected) == 3
        assert used == sum(len(c) for c in ("短记忆一", "短记忆二", "短记忆三"))
        assert dropped == 0

    def test_over_budget_truncated_by_freshness(self, asm_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "memory_retrieval_budget", 15)
        now = datetime.datetime.now()
        stale = now - datetime.timedelta(days=10)
        _memory("m-fresh", "新鲜的长记忆内容排在前面", last_accessed_at=now)
        _memory("m-stale", "陈旧的短记忆", last_accessed_at=stale)
        pool = memory_repository.list_active("u1", "asuna")
        items = [
            RankedMemory(memory=memory, score=0.5) for memory in pool
        ]
        selected, used, dropped = _select_retrieval_segment(RankedMemories(items=items))
        assert used <= 20
        assert [m.id for m in selected] == ["m-fresh"]
        assert dropped == 1
    def test_freshness_ordering_beats_score_order(self, asm_db):
        now = datetime.datetime.now()
        old = datetime.datetime.now() - datetime.timedelta(days=5)
        high_score_old = memory_repository.UserMemory(
            id="m-old", user_id="u1", character_id="asuna", type="user_fact",
            content="高分但旧", importance=0.9, created_at=now, updated_at=now,
            last_accessed_at=old,
        )
        low_score_new = memory_repository.UserMemory(
            id="m-new", user_id="u1", character_id="asuna", type="user_fact",
            content="低分但新", importance=0.5, created_at=now, updated_at=now,
            last_accessed_at=now,
        )
        items = [
            RankedMemory(memory=high_score_old, score=0.9),
            RankedMemory(memory=low_score_new, score=0.1),
        ]
        selected, _, _ = _select_retrieval_segment(RankedMemories(items=items))
        assert [m.id for m in selected] == ["m-new", "m-old"]

    def test_empty_retrieval_ok(self, asm_db):
        selected, used, dropped = _select_retrieval_segment(RankedMemories())
        assert (selected, used, dropped) == ([], 0, 0)

    def test_duplicate_ids_deduped(self, asm_db):
        ranked = _ranked("内容", "内容")
        ranked.items[1].memory.id = ranked.items[0].memory.id
        selected, _, _ = _select_retrieval_segment(ranked)
        assert len(selected) == 1


class TestWorkingWindow:
    def test_window_bounded(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "memory_recent_context_messages", 4)
        messages = [_Message(f"消息{i}") for i in range(50)]
        window = _working_window(messages)
        assert len(window) == 4
        assert [m.content for m in window] == ["消息46", "消息47", "消息48", "消息49"]


class TestAssembleTrace:
    def test_trace_records_budget_usage(self, asm_db, monkeypatch):
        from app.models.conversation import ChatMessage
        from app.services import context_builder

        _memory("m1", "用户喜欢吃西瓜")

        class _Step:
            def __init__(self, name, status, error, extra):
                self.name = name
                self.status = status
                self.error = error
                self.extra = extra

        class _TraceSpy:
            def __init__(self):
                self.records = []

            def record(self, name, duration_ms, status="ok", error=None, **extra):
                self.records.append(_Step(name, status, error, extra))

        class _Conversation:
            mode = "default"
            mode_entered_at = None

        from app.models.character_state import CharacterState
        from app.models.relationship import RelationshipState

        monkeypatch.setattr(
            context_builder.conversation_service,
            "ensure_conversation",
            lambda session_id, user_id: _Conversation(),
        )
        monkeypatch.setattr(
            context_builder.conversation_service,
            "load_window",
            lambda session_id: [
                ChatMessage(role="human" if i % 2 == 0 else "ai", content=f"近况{i}")
                for i in range(6)
            ],
        )
        monkeypatch.setattr(
            context_builder.summary_service, "get_summary", lambda session_id: None
        )
        monkeypatch.setattr(
            context_builder.state_service,
            "load_states",
            lambda user_id: (CharacterState(), RelationshipState()),
        )
        monkeypatch.setattr(
            context_builder.goal_service, "load_active", lambda user_id: []
        )
        import asyncio

        trace = _TraceSpy()
        result = asyncio.run(context_builder.build("s1", "u1", "查询", trace=trace))
        assert [m.id for m in result.memories] == ["m1"]
        steps = [s for s in trace.records if s.name == "context_assemble_v2"]
        assert len(steps) == 1
        extra = steps[0].extra
        assert extra["retrieval_selected"] == 1
        assert extra["retrieval_budget"] == get_settings().memory_retrieval_budget
        assert extra["working_messages"] == 4
        assert extra["retrieval_dropped"] == 0
