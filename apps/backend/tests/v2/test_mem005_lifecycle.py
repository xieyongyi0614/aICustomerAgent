import datetime
import math

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, Memory as MemoryRow, MemoryLinkRow
from app.core.settings import get_settings
from app.repositories import memory_repository
from app.services.memory2 import lifecycle


@pytest.fixture
def life_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(lifecycle, "SessionLocal", testing_session)
    monkeypatch.setattr(memory_repository, "SessionLocal", testing_session)
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
    status="active",
    salience=0.8,
    embedding=None,
    user_id="u1",
    last_reinforced_at=None,
    forgotten_at=None,
    superseded_by=None,
    merge_chain=None,
    created_at=None,
):
    now = datetime.datetime.now()
    with lifecycle.SessionLocal() as session:
        session.add(
            MemoryRow(
                id=id,
                user_id=user_id,
                character_id="asuna",
                content=content,
                type=type,
                importance=0.6,
                status=status,
                salience=salience,
                embedding=embedding,
                superseded_by=superseded_by,
                merge_chain=merge_chain,
                created_at=created_at or now,
                updated_at=now,
                last_reinforced_at=last_reinforced_at,
                forgotten_at=forgotten_at,
            )
        )
        session.commit()


def _row(id):
    with lifecycle.SessionLocal() as session:
        row = session.get(MemoryRow, id)
        if row is None:
            return None
        session.refresh(row)
        session.expunge(row)
        return row


def _links(memory_id=None, related_memory_id=None):
    with lifecycle.SessionLocal() as session:
        query = session.query(MemoryLinkRow)
        if memory_id is not None:
            query = query.filter(MemoryLinkRow.memory_id == memory_id)
        if related_memory_id is not None:
            query = query.filter(MemoryLinkRow.related_memory_id == related_memory_id)
        rows = query.all()
        for row in rows:
            session.expunge(row)
        return rows


class TestTransitionGuard:
    @pytest.mark.parametrize(
        "status,event,expected",
        [
            ("active", "reinforce", "active"),
            ("decayed", "reinforce", "active"),
            ("active", "supersede", "superseded"),
            ("active", "merge", "superseded"),
            ("active", "invalidate", "invalidated"),
            ("active", "decay_floor", "decayed"),
            ("active", "decay_forget", "forgotten"),
            ("decayed", "decay_forget", "forgotten"),
            ("active", "forget", "forgotten"),
            ("decayed", "forget", "forgotten"),
            ("superseded", "forget", "forgotten"),
            ("invalidated", "forget", "forgotten"),
            ("forgotten", "forget", "forgotten"),
        ],
    )
    def test_legal_transitions(self, status, event, expected):
        assert lifecycle.transition(status, event) == expected

    @pytest.mark.parametrize(
        "status,event",
        [
            ("forgotten", "reinforce"),
            ("forgotten", "supersede"),
            ("forgotten", "decay_floor"),
            ("superseded", "reinforce"),
            ("superseded", "decay_floor"),
            ("invalidated", "reinforce"),
            ("decayed", "supersede"),
            ("decayed", "merge"),
            ("decayed", "invalidate"),
        ],
    )
    def test_illegal_transitions_rejected(self, status, event):
        with pytest.raises(lifecycle.IllegalTransitionError):
            lifecycle.transition(status, event)


class TestDecay:
    def test_decay_formula(self, life_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_decay_lambda_json",
                            '{"user_preference": 0.03}')
        now = datetime.datetime.now()
        _memory("m1", "内容", type="user_preference", salience=0.8,
                last_reinforced_at=now - datetime.timedelta(days=10))
        lifecycle.run_decay_cycle(now=now)
        import math

        assert _row("m1").salience == pytest.approx(0.8 * math.exp(-0.03 * 10))
        assert _row("m1").status == "active"

    def test_same_day_rerun_idempotent(self, life_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_decay_lambda_json",
                            '{"user_preference": 0.5}')
        now = datetime.datetime.now()
        _memory("m1", "内容", salience=0.8,
                last_reinforced_at=now - datetime.timedelta(days=5))
        lifecycle.run_decay_cycle(now=now)
        first = _row("m1").salience
        lifecycle.run_decay_cycle(now=now)
        assert _row("m1").salience == pytest.approx(first)

    def test_salience_floor_transitions_to_decayed(self, life_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_decay_lambda_json",
                            '{"user_preference": 1.0}')
        monkeypatch.setattr(get_settings(), "v2_memory_salience_floor", 0.1)
        now = datetime.datetime.now()
        _memory("m1", "内容", salience=0.3,
                last_reinforced_at=now - datetime.timedelta(days=5))
        lifecycle.run_decay_cycle(now=now)
        assert _row("m1").salience == pytest.approx(0.3 * math.exp(-5.0))
        assert _row("m1").status == "decayed"

    def test_decayed_forget_after_retention(self, life_db):
        now = datetime.datetime.now()
        _memory("m1", "旧记忆", status="decayed", salience=0.1,
                last_reinforced_at=now - datetime.timedelta(days=40))
        _memory("m2", "新记忆", status="decayed", salience=0.1,
                last_reinforced_at=now - datetime.timedelta(days=5))
        stats = lifecycle.run_decay_cycle(now=now)
        assert stats["auto_forgotten"] == 1
        assert _row("m1").status == "forgotten"
        assert _row("m1").forgotten_at is not None
        assert _row("m1").embedding is None
        assert _row("m2").status == "decayed"

    def test_30day_low_salience_decayed_not_deleted(self, life_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_decay_lambda_json",
                            '{"user_preference": 1.0}')
        monkeypatch.setattr(get_settings(), "v2_memory_salience_floor", 0.1)
        now = datetime.datetime.now()
        _memory("m1", "低显著度", salience=0.15,
                last_reinforced_at=now - datetime.timedelta(days=30))
        lifecycle.run_decay_cycle(now=now)
        row = _row("m1")
        assert row.status == "decayed"
        assert row.id == "m1"

    def test_row_exception_isolated(self, life_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "v2_memory_decay_lambda_json",
                            '{"user_preference": 0.01}')
        now = datetime.datetime.now()
        _memory("m1", "正常", last_reinforced_at=now - datetime.timedelta(days=3))

        original = lifecycle.decay_lambda_for

        def boom(memory_type):
            if memory_type == "user_preference":
                raise RuntimeError("bad config")
            return original(memory_type)

        monkeypatch.setattr(lifecycle, "decay_lambda_for", boom)
        lifecycle.run_decay_cycle(now=now)
        assert _row("m1").status == "active"


class TestReinforce:
    def test_buffer_flush_bumps_active(self, life_db):
        now = datetime.datetime.now()
        _memory("m1", "内容", salience=0.5, last_reinforced_at=now)
        lifecycle.record_reinforce("m1")
        lifecycle.record_reinforce("m1")
        assert len(lifecycle.flush_reinforce_buffer()) == 1
        row = _row("m1")
        assert row.salience == pytest.approx(0.6)
        assert row.status == "active"
        assert row.last_reinforced_at is not None
        assert lifecycle.flush_reinforce_buffer() == []

    def test_reinforce_revives_decayed(self, life_db):
        _memory("m1", "内容", status="decayed", salience=0.1)
        lifecycle.record_reinforce("m1")
        lifecycle.flush_reinforce_buffer()
        row = _row("m1")
        assert row.status == "active"
        assert row.salience == pytest.approx(0.2)

    def test_reinforce_skips_forgotten(self, life_db):
        now = datetime.datetime.now()
        _memory("m1", "内容", status="forgotten", forgotten_at=now,
                last_reinforced_at=now)
        lifecycle.record_reinforce("m1")
        assert lifecycle.flush_reinforce_buffer() == []
        assert _row("m1").status == "forgotten"
        assert lifecycle._reinforce_pending == []

    def test_buffer_kept_on_db_failure(self, life_db, monkeypatch):
        _memory("m1", "内容", salience=0.5)
        lifecycle.record_reinforce("m1")

        class _Broken:
            def __call__(self):
                raise RuntimeError("db down")

        original = lifecycle.SessionLocal
        monkeypatch.setattr(lifecycle, "SessionLocal", _Broken)
        assert lifecycle.flush_reinforce_buffer() == []
        monkeypatch.setattr(lifecycle, "SessionLocal", original)
        assert lifecycle._reinforce_pending == ["m1"]
        assert len(lifecycle.flush_reinforce_buffer()) == 1
        assert _row("m1").salience == pytest.approx(0.6)


class TestOnPromoted:
    def test_rewrite_supersedes_old_with_traceable_link(self, life_db):
        _memory("old", "用户喜欢吃辣", type="user_preference")
        _memory("new", "用户不吃辣", type="user_preference")
        lifecycle.on_promoted("new")
        old = _row("old")
        assert old.status == "superseded"
        assert old.superseded_by == "new"
        links = _links(memory_id="new")
        assert len(links) == 1
        assert links[0].relation == "supersedes"
        assert links[0].related_memory_id == "old"
        assert _row("new").merge_chain == ["old"]
        assert _row("new").status == "active"

    def test_refinement_merges(self, life_db):
        _memory("old", "用户喜欢吃辣")
        _memory("new", "用户喜欢吃辣尤其是川菜")
        lifecycle.on_promoted("new")
        assert _row("old").status == "superseded"
        links = _links(memory_id="new")
        assert links[0].relation == "merges"
        assert _row("new").merge_chain == ["old"]

    def test_negate_signal_conservative_coexistence(self, life_db):
        _memory("old", "用户喜欢吃辣")
        _memory("new", "用户不吃辣")
        lifecycle.on_promoted("new", relation="negate")
        assert _row("old").status == "active"
        assert _row("new").status == "active"
        links = _links(memory_id="new")
        assert links[0].relation == "contradicts"
        assert links[0].related_memory_id == "old"

    def test_no_conflict_no_links(self, life_db):
        _memory("old", "用户在深圳工作", type="user_fact")
        _memory("new", "用户喜欢吃辣")
        lifecycle.on_promoted("new")
        assert _links() == []
        assert _row("old").status == "active"

    def test_idempotent_rerun_no_duplicate_links(self, life_db):
        _memory("old", "用户喜欢吃辣")
        _memory("new", "用户不吃辣")
        lifecycle.on_promoted("new")
        lifecycle.on_promoted("new")
        assert len(_links()) == 1
        assert _row("new").merge_chain == ["old"]


class TestExplicitForget:
    def test_forget_active_memory(self, life_db):
        _memory("m1", "敏感内容", embedding="[0.1,0.2]")
        assert lifecycle.explicit_forget("m1") is True
        row = _row("m1")
        assert row.status == "forgotten"
        assert row.forgotten_at is not None
        assert row.embedding is None
        assert memory_repository.list_active("u1", "asuna") == []
        assert memory_repository.list_pending_embedding() == []

    def test_forget_idempotent(self, life_db):
        _memory("m1", "内容")
        assert lifecycle.explicit_forget("m1") is True
        first_forgotten_at = _row("m1").forgotten_at
        assert lifecycle.explicit_forget("m1") is True
        assert _row("m1").forgotten_at == first_forgotten_at

    def test_forget_missing_returns_false(self, life_db):
        assert lifecycle.explicit_forget("missing") is False

    def test_forget_by_match_high_confidence_only(self, life_db):
        _memory("m1", "用户生日在五月")
        _memory("m2", "用户喜欢爬山")
        forgotten = lifecycle.explicit_forget_by_match("u1", "用户生日在五月")
        assert forgotten == ["m1"]
        assert _row("m1").status == "forgotten"
        assert _row("m2").status == "active"

    def test_forget_by_match_empty_no_delete(self, life_db):
        _memory("m1", "内容")
        assert lifecycle.explicit_forget_by_match("u1", "") == []
        assert _row("m1").status == "active"


class TestPurge:
    def test_purge_after_retention_with_links(self, life_db):
        now = datetime.datetime.now()
        stale = now - datetime.timedelta(
            days=get_settings().v2_memory_forget_retention_days + 1
        )
        _memory("gone", "过期遗忘", status="forgotten", forgotten_at=stale)
        _memory("keep", "新近遗忘", status="forgotten", forgotten_at=now)
        _memory("other", "正常记忆")
        with lifecycle.SessionLocal() as session:
            session.add(
                MemoryLinkRow(
                    id="l1", memory_id="other", related_memory_id="gone",
                    relation="contradicts", created_at=now,
                )
            )
            session.commit()
        purged = lifecycle.purge_expired_forgotten(now)
        assert purged == 1
        assert _row("gone") is None
        assert _row("keep").status == "forgotten"
        assert _links(related_memory_id="gone") == []
        assert _row("other").status == "active"

    def test_purge_idempotent(self, life_db):
        now = datetime.datetime.now()
        stale = now - datetime.timedelta(days=40)
        _memory("gone", "过期", status="forgotten", forgotten_at=stale)
        assert lifecycle.purge_expired_forgotten(now) == 1
        assert lifecycle.purge_expired_forgotten(now) == 0


class TestEvaluatorIntegration:
    def test_promotion_triggers_conflict_chain(self, life_db, monkeypatch):
        from app.core.db import MemoryCandidateRow
        from app.services.memory2 import evaluator

        monkeypatch.setattr(evaluator, "SessionLocal", memory_repository.SessionLocal)
        monkeypatch.setattr(lifecycle, "SessionLocal", memory_repository.SessionLocal)
        monkeypatch.setattr(get_settings(), "v2_memory_enabled", True)
        monkeypatch.setattr(get_settings(), "v2_memory_vector_enabled", False)
        monkeypatch.setattr(get_settings(), "v2_memory_eval_threshold_high", 0.75)
        monkeypatch.setattr(get_settings(), "v2_memory_eval_threshold_low", 0.35)
        monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_source", 1.0)
        monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_novelty", 0.0)
        monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_affinity", 0.0)
        monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_salience", 0.0)
        _memory("old", "用户喜欢吃辣")

        row = MemoryCandidateRow(
            id="c1",
            user_id="u1",
            character_id="asuna",
            content="用户不吃辣",
            proposed_type="user_preference",
            source="user_stated",
            source_ref={"importance": 0.8, "confidence": 0.9, "relation": "replace"},
            source_table="conversation",
            source_id="src-c1",
            salience=0.8,
            status="pending",
            visibility="private",
            created_at=datetime.datetime.now(),
        )
        with evaluator.SessionLocal() as session:
            session.add(row)
            session.commit()
        import asyncio

        decision = asyncio.run(evaluator.evaluate_candidate(row, []))
        assert decision.action == "approve"
        assert _row("old").status == "superseded"
        assert _row("old").superseded_by == decision.memory_id
        links = _links(memory_id=decision.memory_id)
        assert links[0].relation == "supersedes"
