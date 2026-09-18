"""REF-004：反思执行器。

confidence 折算表驱动（count_factor 曲线/ai_inferred cap/单调性）、三闸复检逐闸、
认领条件 UPDATE 幂等、「5 次说累」端到端（100% 带 ≥3 引用 + llm_call_records 恰 1）、
FailureInjection（幻觉引用拒绝 / LLM 两次失败 failed / 同 run 重复执行幂等 /
Flag OFF 不执行）。
"""

import json
from datetime import datetime, timedelta

import pytest

from app.core.db import EvidenceLinkRow, InsightRow, Memory, ReflectionRunRow
from app.models.reflection import InsightDraft, ReflectionProposal
from app.services.reflection import reflector
from app.services.reflection import evidence as reflection_evidence

USER = "u-rfl"
CHARACTER = "asuna"


class StubTrace:
    def __init__(self):
        self.steps = []

    def record(self, name, duration_ms, status="ok", **extra):
        self.steps.append({"name": name, "status": status, **extra})


class ScriptedLLM:
    """确定性结构化 stub：按调用次序返回 proposal 或抛错（含调用计数）。"""

    def __init__(self, proposals=None, errors=None):
        self.proposals = list(proposals or [])
        self.errors = list(errors or [])
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        def _resolve(inputs):
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            if self.proposals:
                item = self.proposals.pop(0)
                return item if isinstance(item, ReflectionProposal) else schema.model_validate(item)
            return ReflectionProposal(insights=[])

        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(_resolve)

    def __call__(self, *args, **kwargs):
        return self


def _seed_cluster_memory(session_factory, memory_id, *, created_at, content, source="user_stated"):
    now = datetime.now()
    with session_factory() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=USER,
                character_id=CHARACTER,
                content=content,
                type="user_fact",
                importance=0.7,
                confidence=0.9,
                source=source,
                status="active",
                salience=0.8,
                embedding=json.dumps([1.0 if i == 3 else 0.1 for i in range(8)]),
                source_ref={"table": "conversation", "id": f"conv:u:s:{memory_id}"},
                visibility="private",
                created_at=created_at,
                updated_at=now,
            )
        )
        session.commit()


def _seed_fatigue(session_factory, *, count=5):
    now = datetime.now()
    for i in range(count):
        _seed_cluster_memory(
            session_factory,
            f"mem-rfl-{i}",
            created_at=now - timedelta(days=i * 2),
            content="用户说最近加班很累" if i == 0 else f"用户说最近加班很累（第{i + 1}次）",
        )
    return now


def _seed_run(session_factory, run_id, *, status="queued", user=USER):
    now = datetime.now()
    with session_factory() as session:
        session.add(
            ReflectionRunRow(
                id=run_id,
                user_id=user,
                character_id=CHARACTER,
                trigger="scheduled",
                status=status,
                llm_used=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return run_id


def _run_row(session_factory, run_id):
    with session_factory() as session:
        row = session.get(ReflectionRunRow, run_id)
        if row is None:
            return None
        session.expunge(row)
        return row


def _insights(session_factory):
    with session_factory() as session:
        rows = session.query(InsightRow).all()
        for row in rows:
            session.expunge(row)
        return rows


def _proposal(**overrides) -> ReflectionProposal:
    draft = InsightDraft(
        statement=overrides.pop("statement", "用户最近持续处于工作压力中"),
        type=overrides.pop("type", "pattern"),
        scope=overrides.pop("scope", "user"),
        evidence_ids=overrides.pop("evidence_ids", ["E1", "E2", "E3"]),
        counter_evidence=overrides.pop("counter_evidence", "无"),
        self_confidence=overrides.pop("self_confidence", 0.9),
        **overrides,
    )
    return ReflectionProposal(insights=[draft])


@pytest.fixture
def reflection_on(override_settings):
    override_settings()


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch):
    llm = ScriptedLLM()
    monkeypatch.setattr(reflector, "_resolve_llm", lambda settings: llm)
    yield llm


def test_count_factor_curve():
    curve = reflector.get_settings().reflection_confidence_count_curve_json
    assert reflector._count_factor(3, curve) == 0.65
    assert reflector._count_factor(4, curve) == 0.75
    assert reflector._count_factor(5, curve) == 0.85
    assert reflector._count_factor(6, curve) == 0.95
    assert reflector._count_factor(20, curve) == 0.95
    assert reflector._count_factor(2, curve) == 0.65


def test_calibrate_confidence_monotonic_and_capped():
    settings = reflector.get_settings()
    strong = reflector.calibrate_confidence(0.9, 6, ["user_stated"], settings)
    mid = reflector.calibrate_confidence(0.9, 3, ["user_stated"], settings)
    weak = reflector.calibrate_confidence(0.5, 3, ["user_stated"], settings)
    assert strong > mid > weak
    assert strong <= 0.95
    capped = reflector.calibrate_confidence(0.9, 6, ["user_stated", "ai_inferred"], settings)
    assert capped == settings.reflection_ai_inferred_cap


def test_review_rejects_hallucinated_evidence_ids():
    settings = reflector.get_settings()
    proposal = _proposal(evidence_ids=["E1", "E2", "E99"])
    accepted, rejected = reflector._calibrate_and_review(
        proposal, _window(), _provided(5), settings
    )
    assert not accepted
    assert rejected[0]["reasons"] == ["evidence_out_of_scope", "evidence_below_min"]


def test_review_rejects_out_of_scope_raw_id():
    settings = reflector.get_settings()
    proposal = _proposal(evidence_ids=["E1", "E2", "mem-fake"])
    accepted, rejected = reflector._calibrate_and_review(
        proposal, _window(), _provided(5), settings
    )
    assert not accepted
    assert "evidence_out_of_scope" in rejected[0]["reasons"]


def test_review_rejects_missing_counter_evidence():
    settings = reflector.get_settings()
    proposal = _proposal(counter_evidence="  ")
    accepted, rejected = reflector._calibrate_and_review(
        proposal, _window(), _provided(5), settings
    )
    assert not accepted
    assert "missing_counter_evidence" in rejected[0]["reasons"]


def test_review_rejects_below_min_confidence(db_session_factory, reflection_on, override_settings):
    override_settings( reflection_min_confidence=0.99)
    settings = reflector.get_settings()
    proposal = _proposal()
    accepted, rejected = reflector._calibrate_and_review(
        proposal, _window(coherence=0.6), _provided(5), settings
    )
    assert not accepted
    assert "below_min_confidence" in rejected[0]["reasons"]


def test_review_accepts_valid_draft():
    settings = reflector.get_settings()
    accepted, rejected = reflector._calibrate_and_review(
        _proposal(), _window(), _provided(5), settings
    )
    assert not rejected
    draft, resolved, final = accepted[0]
    assert resolved == [f"mem-ev-{i}" for i in range(3)]
    assert final > 0.6


def test_evidence_gone_completes_without_llm(db_session_factory, reflection_on, _patch_llm):
    _seed_run(db_session_factory, "run-gone")
    result = reflector.execute_run("run-gone")
    assert result == "evidence_gone"
    row = _run_row(db_session_factory, "run-gone")
    assert row.status == "done"
    assert row.outcome == "evidence_gone"
    assert row.llm_used is False
    assert _patch_llm.calls == 0
    assert _insights(db_session_factory) == []


def test_end_to_end_creates_insight_with_evidence_links(
    db_session_factory, reflection_on, _patch_llm
):
    now = _seed_fatigue(db_session_factory)
    run_id = _seed_run(db_session_factory, "run-e2e")
    assert reflector._claim_run(run_id, datetime.now()) is True
    _patch_llm.proposals = [_proposal()]
    result = reflector.execute_run(run_id)
    assert result == "done"
    insights = _insights(db_session_factory)
    assert len(insights) == 1
    insight = insights[0]
    assert insight.run_id == run_id
    assert insight.statement == "用户最近持续处于工作压力中"
    with db_session_factory() as session:
        links = (
            session.query(EvidenceLinkRow)
            .filter(EvidenceLinkRow.insight_id == insight.id)
            .all()
        )
    assert len(links) == 3
    assert {link.memory_id for link in links} == {
        "mem-rfl-0",
        "mem-rfl-1",
        "mem-rfl-2",
    }
    assert all(0.0 < link.weight <= 1.0 for link in links)
    row = _run_row(db_session_factory, run_id)
    assert row.status == "done"
    assert row.outcome == "insights_created"
    assert row.insight_ids == [insight.id]
    assert row.llm_used is True
    assert _patch_llm.calls == 1


def test_same_run_reexecution_is_idempotent(db_session_factory, reflection_on, _patch_llm):
    _seed_fatigue(db_session_factory)
    run_id = _seed_run(db_session_factory, "run-idem")
    assert reflector._claim_run(run_id, datetime.now()) is True
    _patch_llm.proposals = [_proposal()]
    assert reflector.execute_run(run_id) == "done"
    _patch_llm.proposals = [_proposal(statement="重复结论")]
    assert reflector.execute_run(run_id) == "done"
    assert len(_insights(db_session_factory)) == 1
    row = _run_row(db_session_factory, run_id)
    assert row.outcome == "already_created"
    assert _patch_llm.calls == 1


def test_llm_double_failure_marks_run_failed(db_session_factory, reflection_on, _patch_llm):
    _seed_fatigue(db_session_factory)
    run_id = _seed_run(db_session_factory, "run-fail")
    assert reflector._claim_run(run_id, datetime.now()) is True
    _patch_llm.errors = [RuntimeError("500"), RuntimeError("500")]
    result = reflector.execute_run(run_id)
    assert result == "failed"
    row = _run_row(db_session_factory, run_id)
    assert row.status == "failed"
    assert row.error == "llm_failed"
    assert row.llm_used is True
    assert _patch_llm.calls == 2
    assert _insights(db_session_factory) == []


def test_all_drafts_rejected_completes_without_insights(
    db_session_factory, reflection_on, _patch_llm
):
    _seed_fatigue(db_session_factory)
    run_id = _seed_run(db_session_factory, "run-rej")
    assert reflector._claim_run(run_id, datetime.now()) is True
    _patch_llm.proposals = [
        ReflectionProposal(
            insights=[
                InsightDraft(
                    statement="无中生有的结论",
                    type="belief",
                    scope="user",
                    evidence_ids=["E99"],
                    counter_evidence="",
                )
            ]
        )
    ]
    result = reflector.execute_run(run_id)
    assert result == "rejected"
    row = _run_row(db_session_factory, run_id)
    assert row.status == "done"
    assert row.outcome == "rejected"
    assert _insights(db_session_factory) == []


def test_claim_is_conditional_update(db_session_factory, reflection_on):
    _seed_run(db_session_factory, "run-claim", status="queued")
    now = datetime.now()
    assert reflector._claim_run("run-claim", now) is True
    assert reflector._claim_run("run-claim", now) is False
    assert _run_row(db_session_factory, "run-claim").status == "running"


def test_timeout_recovery_requeues_running(db_session_factory, reflection_on):
    _seed_run(db_session_factory, "run-zombie", status="running")
    stale = datetime.now() - timedelta(
        minutes=reflector.get_settings().reflection_run_timeout_minutes + 1
    )
    with db_session_factory() as session:
        row = session.get(ReflectionRunRow, "run-zombie")
        row.updated_at = stale
        session.commit()
    assert reflector._recover_timed_out_runs(datetime.now()) == 1
    assert _run_row(db_session_factory, "run-zombie").status == "queued"
    assert reflector._recover_timed_out_runs(datetime.now()) == 0


def test_new_reflection_supersedes_conflicting_old_insight(
    db_session_factory, reflection_on, _patch_llm
):
    _seed_fatigue(db_session_factory)
    now = datetime.now()
    with db_session_factory() as session:
        session.add(
            InsightRow(
                id="ins-old",
                user_id=USER,
                character_id=CHARACTER,
                statement="用户最近持续处于工作压力中（旧表述）",
                type="pattern",
                confidence=0.7,
                scope="user",
                status="active",
                run_id="run-old",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    run_id = _seed_run(db_session_factory, "run-sup")
    assert reflector._claim_run(run_id, datetime.now()) is True
    _patch_llm.proposals = [_proposal()]
    assert reflector.execute_run(run_id) == "done"
    insights = {row.id: row for row in _insights(db_session_factory)}
    assert len(insights) == 2
    assert "ins-old" in insights
    new_id = [key for key in insights if key != "ins-old"][0]
    assert insights["ins-old"].status == "superseded"
    assert insights["ins-old"].superseded_by == new_id
    assert insights[new_id].status == "active"


def test_run_queued_reflections_processes_all(db_session_factory, reflection_on, _patch_llm):
    _seed_fatigue(db_session_factory)
    _seed_run(db_session_factory, "run-batch-1")
    _seed_run(db_session_factory, "run-batch-2")
    _patch_llm.proposals = [_proposal(), _proposal()]
    processed = reflector.run_queued_reflections()
    assert processed == 2
    assert len([row for row in _insights(db_session_factory)]) == 2


def test_trace_records_calibration(db_session_factory, reflection_on, _patch_llm):
    _seed_fatigue(db_session_factory)
    run_id = _seed_run(db_session_factory, "run-trace")
    assert reflector._claim_run(run_id, datetime.now()) is True
    _patch_llm.proposals = [_proposal()]
    trace = StubTrace()
    reflector.execute_run(run_id, trace=trace)
    step = trace.steps[-1]
    assert step["name"] == "reflection_run"
    assert step["outcome"] == "insights_created"
    assert step["calibration"][0]["final_confidence"] > 0.6


def _window(coherence=0.9):
    from app.models.reflection import EvidenceWindow, WindowStats

    return EvidenceWindow(
        topic_digest="用户说最近加班很累",
        members=[],
        stats=WindowStats(
            member_count=5,
            span_hours=96.0,
            distinct_source_refs=5,
            source_type_mix={"user_stated": 5},
            coherence=coherence,
        ),
    )


def _provided(count=5):
    from app.models.reflection import EvidenceMember

    now = datetime.now()
    return [
        EvidenceMember(
            memory_id=f"mem-ev-{i}",
            content=f"用户说最近加班很累（第{i + 1}次）",
            created_at=now - timedelta(days=i),
            source="user_stated",
            source_ref=f"conv:u:s:{i}",
            salience=0.8,
            weight=0.5 - i * 0.05,
        )
        for i in range(count)
    ]
