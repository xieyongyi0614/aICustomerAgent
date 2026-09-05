import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, Memory as MemoryRow, MemoryCandidateRow
from app.core.settings import get_settings
from app.models.memory2 import EvaluationVerdict
from app.services.memory2 import evaluator


@pytest.fixture
def eval_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(evaluator, "SessionLocal", testing_session)
    monkeypatch.setattr(evaluator, "_LLM_RETRY_BACKOFF_SECONDS", 0)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_evaluator_state():
    evaluator.reset_evaluator_state()
    yield
    evaluator.reset_evaluator_state()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "v2_memory_enabled", True)


def _weights(monkeypatch, source=0.35, novelty=0.30, affinity=0.20, salience=0.15):
    monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_source", source)
    monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_novelty", novelty)
    monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_affinity", affinity)
    monkeypatch.setattr(get_settings(), "v2_memory_eval_weight_salience", salience)


def _thresholds(monkeypatch, high=0.75, low=0.35):
    monkeypatch.setattr(get_settings(), "v2_memory_eval_threshold_high", high)
    monkeypatch.setattr(get_settings(), "v2_memory_eval_threshold_low", low)


def _candidate(
    id,
    content,
    proposed_type="user_preference",
    source="user_stated",
    salience=0.7,
    status="pending",
    visibility="private",
    source_ref=None,
    user_id="u1",
    created_at=None,
):
    row = MemoryCandidateRow(
        id=id,
        user_id=user_id,
        character_id="asuna",
        content=content,
        proposed_type=proposed_type,
        source=source,
        source_ref=(
            source_ref
            if source_ref is not None
            else {"importance": salience, "confidence": 0.9}
        ),
        source_table="conversation",
        source_id=f"src-{id}",
        salience=salience,
        status=status,
        visibility=visibility,
        created_at=created_at or datetime.datetime.now(),
    )
    with evaluator.SessionLocal() as session:
        session.add(row)
        session.commit()
    return row


def _memories():
    with evaluator.SessionLocal() as session:
        return session.query(MemoryRow).all()


def _candidate_by_id(candidate_id):
    with evaluator.SessionLocal() as session:
        row = session.get(MemoryCandidateRow, candidate_id)
        if row is None:
            return None
        session.refresh(row)
        session.expunge(row)
        return row


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


def _llm_verdict(approve=True, type=None, reason="长期有用"):
    async def _fake(content, proposed_type, related_contents, llm=None):
        return EvaluationVerdict(approve=approve, type=type, reason=reason)

    return _fake


def _llm_boom():
    async def _fake(content, proposed_type, related_contents, llm=None):
        raise RuntimeError("llm down")

    return _fake


def _llm_guard():
    async def _fake(content, proposed_type, related_contents, llm=None):
        raise AssertionError("LLM 不应被调用")

    return _fake


def _active_memory(content, id="m0", user_id="u1"):
    with evaluator.SessionLocal() as session:
        session.add(
            MemoryRow(
                id=id,
                user_id=user_id,
                character_id="asuna",
                content=content,
                type="user_preference",
                importance=0.6,
                status="active",
                created_at=datetime.datetime.now(),
                updated_at=datetime.datetime.now(),
            )
        )
        session.commit()


class TestScoreComponents:
    def test_full_score_with_default_weights(self, eval_db, monkeypatch):
        _weights(monkeypatch)
        row = _candidate("c1", "我最喜欢吃西瓜", salience=0.8)
        components = evaluator._score_components(row, row.content.strip(), [])
        assert components["source"] == pytest.approx(0.35)
        assert components["novelty"] == pytest.approx(0.30)
        assert components["affinity"] == pytest.approx(0.20)
        assert components["salience"] == pytest.approx(0.15 * 0.8)

    def test_source_weight_table(self, eval_db, monkeypatch):
        _weights(monkeypatch)
        for source, expected in (
            ("user_stated", 1.0),
            ("user_derived", 0.7),
            ("ai_inferred", 0.4),
            ("mystery", 0.4),
        ):
            row = _candidate(f"c-{source}", "内容", source=source)
            components = evaluator._score_components(row, row.content, [])
            assert components["source"] == pytest.approx(0.35 * expected)

    def test_novelty_against_active(self, eval_db):
        assert evaluator._novelty("我喜欢吃西瓜", []) == 1.0
        assert evaluator._novelty("我喜欢吃西瓜", ["我喜欢吃西瓜"]) == 0.0
        partial = evaluator._novelty("我喜欢吃西瓜和葡萄", ["我喜欢吃西瓜"])
        assert 0.0 < partial < 1.0

    def test_type_affinity(self, eval_db):
        assert evaluator._type_affinity("我喜欢吃西瓜", "user_preference") == 1.0
        assert evaluator._type_affinity("我喜欢吃西瓜", "user_fact") == 0.0
        assert evaluator._type_affinity("今天天气不错", "user_preference") == 0.5


class TestThresholdSegments:
    async def test_score_at_high_approves(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=1.0, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        row = _candidate("c1", "我在深圳工作", proposed_type="user_fact")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert decision.memory_id is not None
        assert decision.reason.startswith("rule_score")
        assert len(_memories()) == 1
        assert _candidate_by_id("c1").status == "approved"

    async def test_score_below_low_rejects(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=0.34, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        row = _candidate("c1", "随便聊聊", proposed_type="user_fact")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "reject"
        assert decision.reason.startswith("low_score")
        assert _memories() == []
        assert _candidate_by_id("c1").status == "rejected"

    async def test_score_exactly_low_is_gray(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=0.35, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch, high=0.75, low=0.35)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_verdict(approve=False))
        row = _candidate("c1", "内容", proposed_type="user_fact")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "reject"
        assert decision.reason.startswith("llm:")
        assert decision.llm_used is True

    async def test_score_exactly_high_approves(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=0.75, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch, high=0.75, low=0.35)
        row = _candidate("c1", "内容", proposed_type="user_fact")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"


class TestExplicitRemember:
    async def test_direct_approve_without_llm(self, eval_db, enabled, monkeypatch):
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_guard())
        row = _candidate(
            "c1",
            "用户生日在五月",
            proposed_type="user_fact",
            source="explicit_remember",
            salience=0.5,
            source_ref={"confidence": 0.5, "importance": 0.5},
        )
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert decision.reason == "explicit_remember"
        memories = _memories()
        assert len(memories) == 1
        memory = memories[0]
        assert memory.salience == 1.0
        assert memory.type == "user_fact"
        assert memory.source == "user_stated"
        assert memory.confidence == 0.5
        assert memory.source_ref == {"confidence": 0.5, "importance": 0.5}
        assert memory.visibility == "private"
        assert _candidate_by_id("c1").status == "approved"

    async def test_invalid_proposed_type_falls_back(self, eval_db, enabled):
        row = _candidate(
            "c1",
            "记住这个习惯",
            proposed_type="hobby",
            source="explicit_remember",
        )
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert _memories()[0].type == "user_fact"

    async def test_v2_canonical_type_passthrough(self, eval_db, enabled):
        row = _candidate(
            "c1",
            "记住我们的约定",
            proposed_type="commitment",
            source="explicit_remember",
        )
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert _memories()[0].type == "commitment"


class TestHypothetical:
    async def test_rejected_without_llm(self, eval_db, enabled, monkeypatch):
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_boom())
        row = _candidate("c1", "假装我是国王", visibility="hypothetical")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "reject"
        assert decision.reason == "hypothetical"
        assert decision.llm_used is False
        assert _memories() == []
        assert _candidate_by_id("c1").status == "rejected"


class TestExactDuplicate:
    async def test_rejected_against_active_memory(self, eval_db, enabled):
        _active_memory("我喜欢吃西瓜")
        row = _candidate("c1", "我喜欢吃西瓜")
        decision = await evaluator.evaluate_candidate(row, ["我喜欢吃西瓜"])
        assert decision.action == "reject"
        assert decision.reason == "duplicate_exact"
        assert len(_memories()) == 1


class TestGrayZone:
    async def test_llm_approve_keeps_proposed_type(
        self, eval_db, enabled, monkeypatch
    ):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(
            evaluator, "_ask_llm", _llm_verdict(type="user_fact", reason="长期有用")
        )
        row = _candidate("c1", "我最喜欢草莓蛋糕")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert decision.llm_used is True
        assert decision.reason == "llm:长期有用"
        memories = _memories()
        assert len(memories) == 1
        assert memories[0].type == "user_preference"

    async def test_llm_type_only_used_when_proposed_invalid(
        self, eval_db, enabled, monkeypatch
    ):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_verdict(type="user_fact"))
        row = _candidate("c1", "内容", proposed_type="hobby")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert _memories()[0].type == "user_fact"

    async def test_llm_reject_marks_rejected(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(
            evaluator, "_ask_llm", _llm_verdict(approve=False, reason="瞬时信息")
        )
        row = _candidate("c1", "帮我留意一下")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "reject"
        assert decision.reason == "llm:瞬时信息"
        assert _memories() == []
        assert _candidate_by_id("c1").status == "rejected"

    async def test_llm_failure_defers_and_keeps_pending(
        self, eval_db, enabled, monkeypatch
    ):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_boom())
        row = _candidate("c1", "内容", proposed_type="user_fact")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "defer"
        assert decision.reason == "llm_unavailable"
        assert decision.llm_used is True
        assert _candidate_by_id("c1").status == "pending"
        assert _memories() == []

    async def test_five_failures_reject_with_no_dirty_memory(
        self, eval_db, enabled, monkeypatch
    ):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_boom())
        row = _candidate("c1", "内容", proposed_type="user_fact")
        actions = []
        for _ in range(5):
            decision = await evaluator.evaluate_candidate(row, [])
            actions.append(decision.action)
        assert actions == ["defer", "defer", "defer", "defer", "reject"]
        assert evaluator._llm_failure_counts == {}
        assert _candidate_by_id("c1").status == "rejected"
        assert _candidate_by_id("c1").reason == "llm_failed"
        assert _memories() == []

    async def test_ai_inferred_confidence_capped(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=0.9, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_verdict())
        row = _candidate(
            "c1",
            "用户可能喜欢爬山",
            source="ai_inferred",
            source_ref={"confidence": 0.9, "importance": 0.8},
        )
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert _memories()[0].confidence == pytest.approx(0.4)

    async def test_promotion_failure_keeps_no_half_state(
        self, eval_db, enabled, monkeypatch
    ):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_verdict())
        row = _candidate("c1", "内容", proposed_type="user_fact")

        def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(evaluator, "_promote", _boom)
        with pytest.raises(RuntimeError):
            await evaluator.evaluate_candidate(row, [])
        assert _memories() == []
        assert _candidate_by_id("c1").status == "pending"


class TestFallbackRateGuard:
    async def test_over_cap_defers_without_llm(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_verdict())
        evaluator._fallback_window.extend([True] * 40)
        row = _candidate("c1", "灰区内容", proposed_type="user_fact")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "defer"
        assert decision.reason == "llm_fallback_rate_cap"
        assert decision.llm_used is False
        assert _memories() == []
        assert list(evaluator._fallback_window) == [True] * 40 + [False]

    async def test_under_cap_calls_llm(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=0.5, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        monkeypatch.setattr(evaluator, "_ask_llm", _llm_verdict())
        evaluator._fallback_window.extend([False] * 45 + [True] * 5)
        row = _candidate("c1", "灰区内容", proposed_type="user_fact")
        decision = await evaluator.evaluate_candidate(row, [])
        assert decision.action == "approve"
        assert len(_memories()) == 1


class TestPromoteIdempotency:
    async def test_second_promotion_rejected(self, eval_db, enabled):
        row = _candidate("c1", "内容", proposed_type="user_fact")
        evaluator._promote(row, final_type="user_fact", salience=0.7, reason="test")
        with pytest.raises(evaluator.CandidateNotPendingError):
            evaluator._promote(row, final_type="user_fact", salience=0.7, reason="test")
        assert len(_memories()) == 1

    async def test_stale_candidate_skipped(self, eval_db, enabled):
        row = _candidate("c1", "内容", proposed_type="user_fact")
        evaluator._promote(row, final_type="user_fact", salience=0.7, reason="test")
        decision = await evaluator.evaluate_candidate(row, [])
        assert len(_memories()) == 1
        assert decision.action == "defer"
        assert decision.reason == "not_pending"


class TestEvaluatePending:
    async def test_flag_off_noop(self, eval_db):
        _candidate("c1", "我喜欢吃西瓜")
        decisions = await evaluator.evaluate_pending("u1")
        assert decisions == []
        assert _candidate_by_id("c1").status == "pending"
        assert _memories() == []

    async def test_no_pending_returns_empty(self, eval_db, enabled):
        assert await evaluator.evaluate_pending("u1") == []

    async def test_mixed_outcomes_batch(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=1.0, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        _candidate("c-keep", "我在深圳工作", proposed_type="user_fact")
        _candidate("c-drop", "用户可能喜欢爬山", proposed_type="user_fact", source="ai_inferred")
        monkeypatch.setattr(
            evaluator, "_ask_llm", _llm_verdict(approve=False, reason="无价值")
        )
        decisions = await evaluator.evaluate_pending("u1")
        assert len(decisions) == 2
        assert _candidate_by_id("c-keep").status == "approved"
        assert _candidate_by_id("c-drop").status == "rejected"
        assert {m.user_id for m in _memories()} == {"u1"}

    async def test_same_batch_duplicate_content_single_promotion(
        self, eval_db, enabled, monkeypatch
    ):
        _weights(monkeypatch, source=1.0, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        _candidate("c1", "我在深圳工作", proposed_type="user_fact")
        _candidate("c2", "我在深圳工作", proposed_type="user_fact")
        decisions = await evaluator.evaluate_pending("u1")
        assert len(decisions) == 2
        assert decisions[0].action == "approve"
        assert decisions[1].action == "reject"
        assert decisions[1].reason == "duplicate_exact"
        assert len(_memories()) == 1

    async def test_replay_is_idempotent(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=1.0, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        _candidate("c1", "我在深圳工作", proposed_type="user_fact")
        first = await evaluator.evaluate_pending("u1")
        second = await evaluator.evaluate_pending("u1")
        assert len(first) == 1
        assert second == []
        assert len(_memories()) == 1

    async def test_oldest_first_ordering(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=1.0, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        now = datetime.datetime.now()
        _candidate(
            "c-late", "早的事件", proposed_type="user_fact", created_at=now
        )
        _candidate(
            "c-early",
            "早的事件",
            proposed_type="user_fact",
            created_at=now - datetime.timedelta(hours=1),
        )
        decisions = await evaluator.evaluate_pending("u1")
        assert decisions[0].action == "approve"
        assert decisions[1].reason == "duplicate_exact"
        assert _candidate_by_id("c-early").status == "approved"
        assert _candidate_by_id("c-late").status == "rejected"

    async def test_empty_content_rejected(self, eval_db, enabled):
        _candidate("c1", "   ")
        decisions = await evaluator.evaluate_pending("u1")
        assert decisions[0].action == "reject"
        assert decisions[0].reason == "empty_content"
        assert _candidate_by_id("c1").status == "rejected"

    async def test_trace_records_decisions(self, eval_db, enabled, monkeypatch):
        _weights(monkeypatch, source=1.0, novelty=0, affinity=0, salience=0)
        _thresholds(monkeypatch)
        _candidate("c1", "我在深圳工作", proposed_type="user_fact")
        trace = _TraceSpy()
        await evaluator.evaluate_pending("u1", trace=trace)
        steps = [s for s in trace.records if s.name == "memory_evaluate"]
        assert len(steps) == 1
        assert steps[0].extra["decision"] == "approve"
        assert steps[0].extra["candidate_id"] == "c1"
        assert "components" in steps[0].extra


class TestTypeMapping:
    def test_final_type_rules(self):
        assert evaluator._final_type("user_preference", "user_fact") == "user_preference"
        assert evaluator._final_type("hobby", "user_fact") == "user_fact"
        assert evaluator._final_type("hobby", "also_bad") == "user_fact"
        assert evaluator._final_type(None, None) == "user_fact"

    def test_memory_source_mapping(self):
        assert evaluator._memory_source_of("explicit_remember") == "user_stated"
        assert evaluator._memory_source_of("user_derived") == "user_derived"
        assert evaluator._memory_source_of("unknown") == "user_derived"
