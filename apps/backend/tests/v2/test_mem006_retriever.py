import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, Memory as MemoryRow, MemoryCandidateRow, MemoryLinkRow
from app.core.settings import get_settings
from app.repositories import memory_repository
from app.services.memory2 import lifecycle, retriever


@pytest.fixture
def retrieve_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(retriever, "SessionLocal", testing_session)
    monkeypatch.setattr(memory_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(lifecycle, "SessionLocal", testing_session)
    monkeypatch.setattr(get_settings(), "v2_memory_enabled", True)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_buffer():
    lifecycle.reset_reinforce_buffer()
    yield
    lifecycle.reset_reinforce_buffer()


def _memory(
    id,
    content,
    type="user_preference",
    importance=0.8,
    salience=0.8,
    embedding=None,
    user_id="u1",
    character_id="asuna",
    status="active",
    superseded_by=None,
    visibility=None,
    last_accessed_at=None,
    created_at=None,
):
    now = datetime.datetime.now()
    with memory_repository.SessionLocal() as session:
        session.add(
            MemoryRow(
                id=id,
                user_id=user_id,
                character_id=character_id,
                content=content,
                type=type,
                importance=importance,
                status=status,
                salience=salience,
                embedding=embedding,
                visibility=visibility,
                superseded_by=superseded_by,
                created_at=created_at or now,
                updated_at=now,
                last_accessed_at=last_accessed_at,
            )
        )
        session.commit()


def _rejected_candidate(id, content, user_id="u1", created_at=None):
    with retriever.SessionLocal() as session:
        session.add(
            MemoryCandidateRow(
                id=id,
                user_id=user_id,
                character_id="asuna",
                content=content,
                proposed_type="user_preference",
                source="user_stated",
                source_table="conversation",
                source_id=f"src-{id}",
                status="rejected",
                reason="low_score:0.10",
                created_at=created_at or datetime.datetime.now(),
            )
        )
        session.commit()


def _contradicts_pair(survivor_id, dead_id, dead_updated_at=None):
    now = datetime.datetime.now()
    _memory(survivor_id, f"{survivor_id} 内容")
    _memory(dead_id, f"{dead_id} 内容", status="superseded")
    with retriever.SessionLocal() as session:
        session.add(
            MemoryLinkRow(
                id=f"link-{survivor_id}-{dead_id}",
                memory_id=survivor_id,
                related_memory_id=dead_id,
                relation="contradicts",
                created_at=now,
            )
        )
        if dead_updated_at is not None:
            row = session.get(MemoryRow, dead_id)
            row.updated_at = dead_updated_at
        session.commit()


def _embed_stub(monkeypatch, mapping):
    def _embed(text):
        return mapping.get(text)

    monkeypatch.setattr(retriever.memory_embeddings, "embed_query", _embed)


class TestScoring:
    def test_cosine_identical_and_orthogonal(self):
        assert retriever._cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert retriever._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
        assert retriever._cosine([], []) == 0.0
        assert retriever._cosine([1.0], [1.0, 2.0]) == 0.0

    def test_structured_components(self):
        now = datetime.datetime.now()
        memory = memory_repository.UserMemory(
            id="m1", user_id="u1", character_id="asuna", type="user_preference",
            content="内容", importance=0.9, created_at=now, updated_at=now,
        )
        score = retriever._structured_score(memory, 0.6, now)
        assert score == pytest.approx((1.0 + 0.9 + 0.6) / 3.0)

    def test_recency_half_life(self):
        now = datetime.datetime.now()
        memory = memory_repository.UserMemory(
            id="m1", user_id="u1", character_id="asuna", type="user_fact",
            content="内容", importance=0.5, created_at=now, updated_at=now,
        )
        fresh = retriever._recency(memory, now)
        old = retriever._recency(
            memory, now + datetime.timedelta(days=30)
        )
        assert fresh == pytest.approx(1.0)
        assert old == pytest.approx(0.5)

    def test_affinity_detection(self):
        assert retriever._detect_query_types("我喜欢吃什么") == {"user_preference"}
        assert retriever._detect_query_types("今天天气") == set()

    def test_hybrid_score_weighting(self, retrieve_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_vector_enabled", True)
        monkeypatch.setattr(get_settings(), "v2_memory_weight_semantic", 0.5)
        monkeypatch.setattr(get_settings(), "v2_memory_weight_structured", 0.3)
        monkeypatch.setattr(get_settings(), "v2_memory_weight_affinity", 0.2)
        now = datetime.datetime.now()
        _memory("m1", "用户喜欢吃西瓜", embedding=json.dumps([1.0, 0.0]), created_at=now)
        _embed_stub(monkeypatch, {"我喜欢吃水果": [1.0, 0.0]})
        result = retriever.retrieve("u1", "我喜欢吃水果", top_k=5)
        item = result.items[0]
        assert result.mode == "hybrid"
        assert item.semantic == pytest.approx(1.0)
        assert item.affinity == pytest.approx(1.0)
        expected = 0.5 * 1.0 + 0.3 * item.structured + 0.2 * 1.0
        assert item.score == pytest.approx(expected)


class TestRecall:
    def test_paraphrase_recall_via_semantic(self, retrieve_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_vector_enabled", True)
        _memory("m1", "用户喜欢吃西瓜", embedding=json.dumps([0.9, 0.1]))
        _memory("m2", "用户在深圳工作", type="user_fact", embedding=json.dumps([0.0, 1.0]))
        _embed_stub(
            monkeypatch,
            {"爱吃西瓜吗": [0.9, 0.1], "在哪里上班": [0.0, 1.0]},
        )
        result = retriever.retrieve("u1", "爱吃西瓜吗", top_k=1)
        assert result.items[0].memory.id == "m1"
        result2 = retriever.retrieve("u1", "在哪里上班", top_k=1)
        assert result2.items[0].memory.id == "m2"

    def test_structured_only_when_vector_disabled(self, retrieve_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_vector_enabled", False)
        _memory("m1", "用户喜欢吃西瓜")
        _embed_stub(monkeypatch, {"爱吃西瓜吗": [0.9, 0.1]})
        result = retriever.retrieve("u1", "爱吃西瓜吗")
        assert result.mode == "structured"
        assert all(item.semantic == 0.0 for item in result.items)
        assert result.items

    def test_degraded_when_embedding_unavailable(self, retrieve_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_vector_enabled", True)
        _memory("m1", "用户喜欢吃西瓜")
        _embed_stub(monkeypatch, {"爱吃西瓜吗": None})
        result = retriever.retrieve("u1", "爱吃西瓜吗")
        assert result.mode == "degraded"
        assert result.items[0].memory.id == "m1"

    def test_null_embedding_row_still_structured(self, retrieve_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_vector_enabled", True)
        _memory("m1", "无向量记忆", embedding=None)
        _embed_stub(monkeypatch, {"查询": [1.0, 0.0]})
        result = retriever.retrieve("u1", "查询")
        assert result.items[0].memory.id == "m1"
        assert result.items[0].semantic == 0.0

    def test_top_k_and_empty_result(self, retrieve_db, monkeypatch):
        _memory("m1", "记忆一")
        _memory("m2", "记忆二")
        _memory("m3", "记忆三")
        result = retriever.retrieve("u1", "任意查询", top_k=2)
        assert len(result.items) == 2
        empty = retriever.retrieve("nobody", "任意查询")
        assert empty.items == []


class TestFilters:
    def test_hypothetical_excluded(self, retrieve_db):
        _memory("m1", "假装的记忆", visibility="hypothetical")
        _memory("m2", "正常记忆")
        result = retriever.retrieve("u1", "查询")
        assert [item.memory.id for item in result.items] == ["m2"]

    def test_superseded_excluded(self, retrieve_db):
        _memory("m1", "旧记忆", status="superseded", superseded_by="m2")
        _memory("m2", "新记忆")
        result = retriever.retrieve("u1", "查询")
        assert [item.memory.id for item in result.items] == ["m2"]

    def test_recently_rejected_content_filtered(self, retrieve_db):
        _memory("m1", "用户喜欢吃香菜")
        _rejected_candidate("rc1", "用户喜欢吃香菜")
        result = retriever.retrieve("u1", "查询")
        assert result.items == []

    def test_rejected_beyond_cooldown_not_filtered(self, retrieve_db):
        _memory("m1", "用户喜欢吃香菜")
        _rejected_candidate(
            "rc1", "用户喜欢吃香菜",
            created_at=datetime.datetime.now() - datetime.timedelta(hours=25),
        )
        result = retriever.retrieve("u1", "查询")
        assert [item.memory.id for item in result.items] == ["m1"]

    def test_contradicts_cooldown_survivor_filtered(self, retrieve_db):
        now = datetime.datetime.now()
        _contradicts_pair("survivor", "dead", dead_updated_at=now)
        result = retriever.retrieve("u1", "查询")
        assert [item.memory.id for item in result.items] == []

    def test_contradicts_beyond_cooldown_survivor_visible(self, retrieve_db):
        stale = datetime.datetime.now() - datetime.timedelta(hours=25)
        _contradicts_pair("survivor", "dead", dead_updated_at=stale)
        result = retriever.retrieve("u1", "查询")
        assert [item.memory.id for item in result.items] == ["survivor"]


class TestReinforceSignal:
    def test_hits_go_to_buffer_not_direct_write(self, retrieve_db):
        _memory("m1", "记忆一")
        before = memory_repository.get_memory("m1")
        retriever.retrieve("u1", "查询", top_k=5)
        after = memory_repository.get_memory("m1")
        assert after.last_accessed_at == before.last_accessed_at
        assert lifecycle._reinforce_pending == ["m1"]
        assert len(lifecycle.flush_reinforce_buffer()) == 1


class TestTrace:
    def test_trace_records_scores_and_filters(self, retrieve_db):
        _memory("m1", "用户喜欢吃西瓜", embedding=json.dumps([1.0, 0.0]))
        _memory("m2", "被拒内容")
        _rejected_candidate("rc1", "被拒内容")

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

        trace = _TraceSpy()
        retriever.retrieve("u1", "查询", trace=trace)
        steps = [s for s in trace.records if s.name == "memory_retrieve_v2"]
        assert len(steps) == 1
        returned_ids = [entry["id"] for entry in steps[0].extra["returned"]]
        assert returned_ids == ["m1"]
        filtered = steps[0].extra["filtered"]
        assert filtered[0]["penalty_reason"] == "recently_rejected"


class TestContextBuilderWiring:
    def test_v2_branch_feeds_select_for_context(self, retrieve_db, monkeypatch):
        from app.models.character_state import CharacterState
        from app.models.relationship import RelationshipState
        from app.services import context_builder

        monkeypatch.setattr(get_settings(), "v2_memory_vector_enabled", False)
        _memory("m1", "用户喜欢吃西瓜")

        class _Conversation:
            mode = "default"
            mode_entered_at = None

        monkeypatch.setattr(
            context_builder.conversation_service,
            "ensure_conversation",
            lambda session_id, user_id: _Conversation(),
        )
        monkeypatch.setattr(
            context_builder.conversation_service,
            "load_window",
            lambda session_id: [],
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

        result = asyncio.run(
            context_builder.build("s1", "u1", "查询", trace=None)
        )
        assert [m.id for m in result.memories] == ["m1"]
