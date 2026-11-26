import datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import timeutil
from app.core import llm_factory
from app.core.db import Base, BackgroundJobRow, Memory as MemoryRow
from app.core.settings import get_settings
from app.repositories import background_job_repository, memory_repository
from app.services.memory import embeddings


@pytest.fixture
def embed_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(memory_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(background_job_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(embeddings, "EMBED_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(get_settings(), "embedding_model", "fake-embedding")
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_state():
    embeddings.reset_queue()
    llm_factory.reset_llm()
    yield
    embeddings.reset_queue()
    llm_factory.reset_llm()


class _FakeEmbeddingClient:
    def __init__(self, dim=768, fail=False, wrong_dim=False):
        self.dim = dim
        self.fail = fail
        self.wrong_dim = wrong_dim
        self.calls: list[list[str]] = []

    @property
    def embeddings(self):
        return self

    def create(self, model, input):
        self.calls.append(list(input))
        if self.fail:
            raise RuntimeError("embed endpoint down")
        dimension = self.dim + 1 if self.wrong_dim else self.dim
        data = [
            SimpleNamespace(embedding=[0.1] * dimension, index=index)
            for index in range(len(input))
        ]
        return SimpleNamespace(data=data)


def _fake_client(monkeypatch, **kwargs):
    client = _FakeEmbeddingClient(**kwargs)
    monkeypatch.setattr(embeddings, "get_embedding_client", lambda: client)
    return client


def _memory(id, content, status="active", embedding=None):
    with memory_repository.SessionLocal() as session:
        session.add(
            MemoryRow(
                id=id,
                user_id="u1",
                character_id="asuna",
                content=content,
                type="user_preference",
                importance=0.6,
                status=status,
                embedding=embedding,
                created_at=timeutil.now(),
                updated_at=timeutil.now(),
            )
        )
        session.commit()


def _memory_row(memory_id):
    with memory_repository.SessionLocal() as session:
        row = session.get(MemoryRow, memory_id)
        session.expunge(row)
        return row


def _jobs():
    return background_job_repository.list_jobs(embeddings.JOB_TYPE_EMBEDDING_BACKFILL)


def test_embedding_client_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_model", "")
    assert llm_factory.get_embedding_client() is None


def test_embedding_client_reuses_profile_credentials(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_model", "fake-embedding")
    monkeypatch.setattr(get_settings(), "embedding_profile", "longcat")
    try:
        client = llm_factory.get_embedding_client()
        assert client is not None
        assert llm_factory.get_embedding_client() is client
    finally:
        llm_factory.reset_llm()


class TestBatching:
    def test_size_condition_triggers_flush(self, embed_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "embedding_batch_size", 2)
        client = _fake_client(monkeypatch)
        _memory("m1", "内容一")
        _memory("m2", "内容二")
        embeddings.enqueue("m1", "内容一")
        assert client.calls == []
        embeddings.enqueue("m2", "内容二")
        assert len(client.calls) == 1
        assert client.calls[0] == ["内容一", "内容二"]
        assert _memory_row("m1").embedding is not None
        assert _memory_row("m2").embedding is not None
        assert embeddings._queue == []

    def test_window_condition_triggers_flush(self, embed_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "embedding_batch_window_seconds", 60)
        client = _fake_client(monkeypatch)
        _memory("m1", "内容一")
        embeddings.enqueue("m1", "内容一")
        assert embeddings.flush_if_due() == 0
        assert client.calls == []
        embeddings._queue[0].enqueued_at -= 61
        assert embeddings.flush_if_due() == 1
        assert len(client.calls) == 1

    def test_duplicate_enqueue_generates_vector_once(self, embed_db, monkeypatch):
        client = _fake_client(monkeypatch)
        _memory("m1", "内容一")
        embeddings.enqueue("m1", "内容一")
        embeddings.enqueue("m1", "内容一")
        embeddings._flush()
        total_texts = [text for call in client.calls for text in call]
        assert total_texts.count("内容一") == 1

    def test_truncates_overlong_input(self, embed_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "embedding_max_input_chars", 10)
        client = _fake_client(monkeypatch)
        _memory("m1", "x" * 100)
        embeddings.enqueue("m1", "x" * 100)
        embeddings._flush()
        assert len(client.calls[0][0]) == 10


class TestBackfill:
    def test_scan_fills_only_active_null_rows(self, embed_db, monkeypatch):
        client = _fake_client(monkeypatch)
        _memory("m1", "待补一")
        _memory("m2", "已填", embedding=json.dumps([0.5] * 768))
        _memory("m3", "已废弃", status="superseded")
        updated = embeddings.backfill_scan()
        assert updated == 1
        assert _memory_row("m1").embedding is not None
        assert client.calls[0] == ["待补一"]

    def test_scan_recovers_after_service_recovery(self, embed_db, monkeypatch):
        failing = _fake_client(monkeypatch, fail=True)
        _memory("m1", "中断内容")
        assert embeddings.backfill_scan() == 0
        assert _memory_row("m1").embedding is None
        assert len(_jobs()) == 1
        assert _jobs()[0].last_error == "RuntimeError"

        recovered = _fake_client(monkeypatch)
        assert embeddings.backfill_scan() == 1
        assert _memory_row("m1").embedding is not None
        assert failing.calls and recovered.calls
        assert _jobs()[0].status == "done"

    def test_scan_skips_rows_already_in_queue(self, embed_db, monkeypatch):
        _fake_client(monkeypatch)
        _memory("m1", "排队中")
        embeddings.enqueue("m1", "排队中")
        assert embeddings.backfill_scan() == 0
        assert len(embeddings._queue) == 1


class TestFailures:
    def test_dimension_mismatch_fails_batch_into_job(self, embed_db, monkeypatch):
        _fake_client(monkeypatch, wrong_dim=True)
        _memory("m1", "内容")
        assert embeddings.backfill_scan() == 0
        assert _memory_row("m1").embedding is None
        jobs = _jobs()
        assert len(jobs) == 1
        assert jobs[0].last_error == "dimension_mismatch"
        payload = jobs[0].payload
        assert payload["memory_id"] == "m1"
        assert payload["content_hash"]

    def test_api_failure_retries_then_job(self, embed_db, monkeypatch):
        client = _fake_client(monkeypatch, fail=True)
        _memory("m1", "内容")
        embeddings.backfill_scan()
        assert len(client.calls) == 3
        assert _memory_row("m1").embedding is None
        assert len(_jobs()) == 1

    def test_job_idempotency_key_shape(self, embed_db, monkeypatch):
        _fake_client(monkeypatch, fail=True)
        _memory("m1", "内容")
        embeddings.backfill_scan()
        job = _jobs()[0]
        assert job.idempotency_key.startswith("embedding:m1:")
        assert job.job_type == "embedding_backfill"
        assert job.status == "pending"

    def test_unconfigured_client_no_jobs(self, embed_db, monkeypatch):
        monkeypatch.setattr(embeddings, "get_embedding_client", lambda: None)
        _memory("m1", "内容")
        assert embeddings.backfill_scan() == 0
        assert _memory_row("m1").embedding is None
        assert _jobs() == []


class TestIdempotentUpdate:
    def test_conditional_update_skips_filled_rows(self, embed_db):
        _memory("m1", "已填", embedding=json.dumps([0.9] * 768))
        updated = memory_repository.update_embeddings_batch([("m1", [0.1] * 768)])
        assert updated == 0
        assert json.loads(_memory_row("m1").embedding) == [0.9] * 768

    def test_conditional_update_skips_non_active(self, embed_db):
        _memory("m1", "已废弃", status="superseded")
        updated = memory_repository.update_embeddings_batch([("m1", [0.1] * 768)])
        assert updated == 0

    def test_single_update_embedding(self, embed_db):
        _memory("m1", "内容")
        assert memory_repository.update_embedding("m1", [0.2] * 768) is True
        assert memory_repository.update_embedding("m1", [0.3] * 768) is False
        assert json.loads(_memory_row("m1").embedding) == [0.2] * 768
        assert memory_repository.update_embedding("missing", [0.2] * 768) is False

    def test_flag_off_no_queue_no_scan(self, embed_db, monkeypatch):
        client = _fake_client(monkeypatch)
        _memory("m1", "内容")
        embeddings.enqueue("m1", "内容")
        assert embeddings.backfill_scan() == 0
        assert embeddings.flush_if_due() == 0
        assert client.calls == []
        assert _memory_row("m1").embedding is None


def _pending_candidate(id, content, source="user_stated"):
    from app.core.db import MemoryCandidateRow

    return MemoryCandidateRow(
        id=id,
        user_id="u1",
        character_id="asuna",
        content=content,
        proposed_type="user_fact",
        source=source,
        source_ref={"importance": 0.8, "confidence": 0.9},
        source_table="conversation",
        source_id=f"src-{id}",
        salience=0.8,
        status="pending",
        visibility="private",
        created_at=timeutil.now(),
    )


def _approve_candidate(monkeypatch, id, content):
    from app.services.memory import evaluator

    monkeypatch.setattr(evaluator, "SessionLocal", memory_repository.SessionLocal)
    monkeypatch.setattr(get_settings(), "memory_eval_threshold_high", 0.75)
    monkeypatch.setattr(get_settings(), "memory_eval_threshold_low", 0.35)
    for name, value in (
        ("memory_eval_weight_source", 1.0),
        ("memory_eval_weight_novelty", 0.0),
        ("memory_eval_weight_affinity", 0.0),
        ("memory_eval_weight_salience", 0.0),
    ):
        monkeypatch.setattr(get_settings(), name, value)
    row = _pending_candidate(id, content)
    with evaluator.SessionLocal() as session:
        session.add(row)
        session.commit()
    import asyncio

    return asyncio.run(
        evaluator.evaluate_candidate(row, [])
    )


class TestEvaluatorWiring:
    def test_promotion_enqueues_embedding(self, embed_db, monkeypatch):
        client = _fake_client(monkeypatch)
        monkeypatch.setattr(get_settings(), "embedding_batch_size", 32)
        decision = _approve_candidate(monkeypatch, "c1", "我在深圳工作")
        assert decision.action == "approve"
        assert [item.memory_id for item in embeddings._queue] == [decision.memory_id]
        embeddings._flush()
        assert client.calls == [["我在深圳工作"]]
        assert _memory_row(decision.memory_id).embedding is not None


class TestQueryEmbeddingBatch:
    def test_all_queries_embeds_in_one_call_and_keeps_order(self, monkeypatch):
        client = _fake_client(monkeypatch, dim=3)

        vectors = embeddings.embed_queries(["查询一", "查询二", "查询三"])

        assert client.calls == [["查询一", "查询二", "查询三"]]
        assert all(vector is not None and len(vector) == 3 for vector in vectors)

    def test_blank_entries_stay_none_without_extra_call(self, monkeypatch):
        client = _fake_client(monkeypatch, dim=3)

        vectors = embeddings.embed_queries(["查询一", "   ", ""])

        assert client.calls == [["查询一"]]
        assert vectors[0] is not None
        assert vectors[1] is None
        assert vectors[2] is None

    def test_all_blank_skips_client_entirely(self, monkeypatch):
        client = _fake_client(monkeypatch)

        assert embeddings.embed_queries(["", "  "]) == [None, None]
        assert client.calls == []

    def test_empty_input_returns_empty(self, monkeypatch):
        client = _fake_client(monkeypatch)

        assert embeddings.embed_queries([]) == []
        assert client.calls == []

    def test_unconfigured_client_returns_none_per_entry(self, monkeypatch):
        monkeypatch.setattr(embeddings, "get_embedding_client", lambda: None)

        assert embeddings.embed_queries(["查询一", "查询二"]) == [None, None]

    def test_endpoint_failure_degrades_whole_batch(self, monkeypatch, caplog):
        _fake_client(monkeypatch, fail=True)

        with caplog.at_level("WARNING"):
            assert embeddings.embed_queries(["查询一", "查询二"]) == [None, None]
        assert any(
            "query 批量向量化失败" in record.message for record in caplog.records
        )

