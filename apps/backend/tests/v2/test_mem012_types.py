"""V2 类型体系收口测试：7 规范类型 + 2 遗留类型的归一化、存储与检索亲和。"""

import datetime
from typing import get_args

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, Memory as MemoryRow
from app.core.settings import get_settings
from app.models.memory import MemoryType, UserMemory
from app.repositories import memory_repository
from app.services.memory import evaluator, lifecycle, retriever, types


@pytest.fixture
def types_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (memory_repository, evaluator, lifecycle, retriever):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    monkeypatch.setattr(get_settings(), "memory_eval_threshold_high", 0.75)
    monkeypatch.setattr(get_settings(), "memory_eval_threshold_low", 0.35)
    monkeypatch.setattr(get_settings(), "memory_eval_weight_source", 1.0)
    monkeypatch.setattr(get_settings(), "memory_eval_weight_novelty", 0.0)
    monkeypatch.setattr(get_settings(), "memory_eval_weight_affinity", 0.0)
    monkeypatch.setattr(get_settings(), "memory_eval_weight_salience", 0.0)
    evaluator.reset_evaluator_state()
    yield testing_session
    evaluator.reset_evaluator_state()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _candidate(id, content, proposed_type, source="user_stated"):
    from app.core.db import MemoryCandidateRow

    row = MemoryCandidateRow(
        id=id,
        user_id="u1",
        character_id="asuna",
        content=content,
        proposed_type=proposed_type,
        source=source,
        source_ref={"importance": 0.8, "confidence": 0.9},
        source_table="conversation",
        source_id=f"src-{id}",
        salience=0.8,
        status="pending",
        visibility="private",
        created_at=datetime.datetime.now(),
    )
    with memory_repository.SessionLocal() as session:
        session.add(row)
        session.commit()
    return row


class TestNormalizeType:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("user_preference", "user_preference"),
            ("user_fact", "user_fact"),
            ("experience", "experience"),
            ("relationship_fact", "relationship_fact"),
            ("commitment", "commitment"),
            ("milestone_event", "milestone_event"),
            ("behavior_pattern", "behavior_pattern"),
            ("important_event", "experience"),
            ("relationship_event", "relationship_fact"),
            ("goal", None),
            ("hobby", None),
            (None, None),
        ],
    )
    def test_normalize(self, raw, expected):
        assert types.normalize_type(raw) == expected

    def test_storage_type_accepts_legacy_and_canonical(self):
        for value in types.STORAGE_MEMORY_TYPES:
            assert types.storage_type(value) == value
        assert types.storage_type("goal") is None

    def test_model_literal_covers_storage_set(self):
        assert set(types.STORAGE_MEMORY_TYPES) == set(get_args(MemoryType))


class TestPromotionNormalization:
    def test_legacy_important_event_normalized_to_experience(self, types_db):
        row = _candidate("c1", "用户通过了面试", "important_event")
        decision = asyncio_run(
            evaluator.evaluate_candidate(row, [])
        )
        assert decision.action == "approve"
        with memory_repository.SessionLocal() as session:
            assert session.get(MemoryRow, decision.memory_id).type == "experience"

    def test_legacy_relationship_event_normalized_to_relationship_fact(self, types_db):
        row = _candidate("c1", "用户帮我修过电脑", "relationship_event")
        decision = asyncio_run(evaluator.evaluate_candidate(row, []))
        assert decision.action == "approve"
        with memory_repository.SessionLocal() as session:
            stored = session.get(MemoryRow, decision.memory_id).type
        assert stored == "relationship_fact"

    def test_new_canonical_type_stored(self, types_db):
        row = _candidate("c1", "周末一起吃饭", "commitment")
        decision = asyncio_run(evaluator.evaluate_candidate(row, []))
        assert decision.action == "approve"
        with memory_repository.SessionLocal() as session:
            stored = session.get(MemoryRow, decision.memory_id).type
        assert stored == "commitment"

    def test_orm_check_rejects_out_of_vocabulary(self, types_db):
        with pytest.raises(Exception):
            with memory_repository.SessionLocal() as session:
                session.add(
                    MemoryRow(
                        id="m-bad",
                        user_id="u1",
                        character_id="asuna",
                        content="内容",
                        type="goal",
                        importance=0.5,
                        status="active",
                        created_at=datetime.datetime.now(),
                        updated_at=datetime.datetime.now(),
                    )
                )
                session.commit()

    def test_user_memory_loads_all_storage_types(self, types_db):
        for memory_type in types.STORAGE_MEMORY_TYPES:
            memory = UserMemory(
                id=f"m-{memory_type}",
                user_id="u1",
                character_id="asuna",
                type=memory_type,
                content="内容",
                importance=0.5,
                created_at=datetime.datetime.now(),
                updated_at=datetime.datetime.now(),
            )
            assert memory.type == memory_type


class TestRetrieverAffinityAliases:
    def test_legacy_query_keywords_alias_to_canonical(self):
        assert retriever._detect_query_types("面试经历") == {"experience"}
        assert retriever._detect_query_types("我们一起去过") == {"relationship_fact"}

    def test_legacy_stored_type_matches_canonical_query(self):
        memory = UserMemory(
            id="m1",
            user_id="u1",
            character_id="asuna",
            type="important_event",
            content="内容",
            importance=0.5,
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now(),
        )
        assert retriever._affinity_score(memory, {"experience"}) == 1.0


class TestEvaluatorAffinityUnification:
    def test_canonical_and_legacy_proposed_types_score_alike(self):
        """映射统一后规范名与遗留名同分（原规范名 experience 被误罚 0.0 的不一致消除）。"""
        assert evaluator._type_affinity("用户明天有一场面试", "experience") == 1.0
        assert evaluator._type_affinity("用户明天有一场面试", "important_event") == 1.0

    def test_cross_group_still_rejected(self):
        assert evaluator._type_affinity("我喜欢吃西瓜", "important_event") == 0.0
        assert evaluator._type_affinity("我喜欢吃西瓜", "user_preference") == 1.0

    def test_no_hit_neutral(self):
        assert evaluator._type_affinity("今天天气不错", "user_preference") == 0.5


class TestDecayLambdaAliases:
    def test_legacy_type_uses_canonical_lambda(self, monkeypatch):
        monkeypatch.setattr(
            get_settings(),
            "memory_decay_lambda_json",
            '{"experience": 0.03, "relationship_fact": 0.03}',
        )
        assert lifecycle.decay_lambda_for("important_event") == pytest.approx(0.03)
        assert lifecycle.decay_lambda_for("relationship_event") == pytest.approx(0.03)
        assert lifecycle.decay_lambda_for("commitment") == pytest.approx(0.03)


def asyncio_run(coroutine):
    import asyncio

    return asyncio.run(coroutine)
