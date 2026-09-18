import datetime
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, Memory as MemoryRow, MemoryCandidateRow
from app.core.settings import get_settings
from app.main import app
from app.models.observability import RuntimeTrace, TraceStep
from app.repositories import memory_repository, trace_repository
from app.services.memory2 import attribution, evaluator, lifecycle


@pytest.fixture
def attr_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (attribution, evaluator, lifecycle, memory_repository, trace_repository):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _promote(candidate_id="c1", content="用户喜欢吃辣", source_ref=None):
    now = datetime.datetime.now()
    ref = source_ref or {"table": "conversation", "id": "conv:u1:s1:0"}
    row = MemoryCandidateRow(
        id=candidate_id,
        user_id="u1",
        character_id="asuna",
        content=content,
        proposed_type="user_preference",
        source="user_stated",
        source_ref=ref,
        source_table="conversation",
        source_id="conv:u1:s1:0",
        salience=0.8,
        status="pending",
        visibility="private",
        created_at=now,
    )
    with evaluator.SessionLocal() as session:
        session.add(row)
        session.commit()
    import asyncio

    decision = asyncio.run(evaluator.evaluate_candidate(row, []))
    assert decision.action == "approve"
    return decision.memory_id


def _seed_trace(steps, user_id="u1", turn_id="t1"):
    trace = RuntimeTrace(
        trace_id=uuid.uuid4().hex,
        user_id=user_id,
        turn_id=turn_id,
        steps=[TraceStep(name=name, duration_ms=1.0, status="ok", extra=extra) for name, extra in steps],
    )
    trace_repository.save(trace)


def _memory_row(memory_id):
    with memory_repository.SessionLocal() as session:
        row = session.get(MemoryRow, memory_id)
        session.expunge(row)
        return row


class TestMemoryAttribution:
    def test_full_chain_view(self, attr_db):
        memory_id = _promote()
        _seed_trace(
            [
                (
                    "memory_ingest",
                    {
                        "source": "conversation",
                        "created": 1,
                        "candidate_ids": ["c1"],
                    },
                ),
                (
                    "memory_evaluate",
                    {
                        "candidate_id": "c1",
                        "decision": "approve",
                        "reason": "rule_score:0.95",
                        "score": 0.95,
                        "llm_used": False,
                    },
                ),
            ]
        )
        view = attribution.memory_attribution(memory_id)
        assert view is not None
        assert view["memory"]["id"] == memory_id
        assert view["memory"]["status"] == "active"
        assert view["candidate"]["id"] == "c1"
        assert view["candidate"]["status"] == "approved"
        step_names = [step["step"] for step in view["steps"]]
        assert "memory_ingest" in step_names
        assert "memory_evaluate" in step_names
        assert view["trace_status"] == "ok"

    def test_recent_reinforce_visible(self, attr_db):
        memory_id = _promote()
        lifecycle.record_reinforce(memory_id)
        lifecycle.flush_reinforce_buffer()
        _seed_trace(
            [
                (
                    "memory_lifecycle",
                    {"event": "reinforce", "memory_ids": [memory_id], "updated": 1},
                )
            ]
        )
        view = attribution.memory_attribution(memory_id)
        assert _memory_row(memory_id).last_reinforced_at is not None
        lifecycle_steps = [s for s in view["steps"] if s["step"] == "memory_lifecycle"]
        assert lifecycle_steps[0]["extra"]["event"] == "reinforce"

    def test_supersede_link_traced(self, attr_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "memory_eval_weight_source", 1.0)
        monkeypatch.setattr(get_settings(), "memory_eval_weight_novelty", 0.0)
        monkeypatch.setattr(get_settings(), "memory_eval_weight_affinity", 0.0)
        monkeypatch.setattr(get_settings(), "memory_eval_weight_salience", 0.0)
        old = MemoryRow(
            id="old",
            user_id="u1",
            character_id="asuna",
            content="用户喜欢吃辣",
            type="user_preference",
            importance=0.6,
            status="active",
            salience=0.6,
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now(),
        )
        with memory_repository.SessionLocal() as session:
            session.add(old)
            session.commit()
        memory_id = _promote(
            candidate_id="c2",
            content="用户不吃辣",
            source_ref={"table": "conversation", "id": "conv:u1:s1:9"},
        )
        assert memory_id
        _seed_trace(
            [
                (
                    "memory_lifecycle",
                    {
                        "event": "supersede",
                        "memory_id": memory_id,
                        "target_id": "old",
                        "relation": "supersedes",
                    },
                )
            ]
        )
        view = attribution.memory_attribution("old")
        assert view["memory"]["status"] == "superseded"
        links = [l for l in view["links"] if l["relation"] == "supersedes"]
        assert links and links[0]["related_memory_id"] == "old"
        assert view["steps"], "supersede 事件应可见于归因步骤"

    def test_no_trace_data_marked(self, attr_db):
        memory_id = _promote()
        view = attribution.memory_attribution(memory_id)
        assert view["trace_status"] == "no_data"
        assert view["steps"] == []

    def test_missing_memory_returns_none(self, attr_db):
        assert attribution.memory_attribution("missing") is None


class TestCandidateAttribution:
    def test_rejected_candidate_reason_visible(self, attr_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "memory_eval_weight_source", 0.5)
        monkeypatch.setattr(get_settings(), "memory_eval_weight_novelty", 0.0)
        monkeypatch.setattr(get_settings(), "memory_eval_weight_affinity", 0.0)
        monkeypatch.setattr(get_settings(), "memory_eval_weight_salience", 0.0)
        monkeypatch.setattr(get_settings(), "memory_eval_threshold_high", 0.75)
        monkeypatch.setattr(get_settings(), "memory_eval_threshold_low", 0.35)

        async def _reject(*args, **kwargs):
            from app.models.memory2 import EvaluationVerdict

            return EvaluationVerdict(approve=False, reason="无长期价值")

        monkeypatch.setattr(evaluator, "_ask_llm", _reject)
        now = datetime.datetime.now()
        row = MemoryCandidateRow(
            id="cx",
            user_id="u1",
            character_id="asuna",
            content="随便聊聊",
            proposed_type="user_fact",
            source="user_stated",
            source_ref={"table": "conversation", "id": "conv:u1:s1:x"},
            source_table="conversation",
            source_id="conv:u1:s1:x",
            salience=0.3,
            status="pending",
            visibility="private",
            created_at=now,
        )
        with evaluator.SessionLocal() as session:
            session.add(row)
            session.commit()
        import asyncio

        decision = asyncio.run(evaluator.evaluate_candidate(row, []))
        assert decision.action == "reject"
        _seed_trace(
            [
                (
                    "memory_evaluate",
                    {"candidate_id": "cx", "decision": "reject", "reason": decision.reason},
                )
            ]
        )
        view = attribution.candidate_attribution("cx")
        assert view["candidate"]["status"] == "rejected"
        assert "无长期价值" in view["candidate"]["reason"]
        assert view["steps"][0]["extra"]["decision"] == "reject"
        assert view["promoted_memory"] is None

    def test_missing_candidate_returns_none(self, attr_db):
        assert attribution.candidate_attribution("missing") is None


class TestDebugEndpoints:
    def test_memory_attribution_endpoint(self, attr_db):
        memory_id = _promote()
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/debug/memory/{memory_id}/attribution")
            assert resp.status_code == 200
            assert resp.json()["memory"]["id"] == memory_id
            resp = client.get("/api/v1/debug/memory/missing/attribution")
            assert resp.status_code == 404

    def test_candidate_attribution_endpoint(self, attr_db):
        _promote()
        with TestClient(app) as client:
            resp = client.get("/api/v1/debug/candidate/c1/attribution")
            assert resp.status_code == 200
            assert resp.json()["candidate"]["id"] == "c1"
            resp = client.get("/api/v1/debug/candidate/missing/attribution")
            assert resp.status_code == 404
