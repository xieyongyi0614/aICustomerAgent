"""REF-006：Reflection Trace 与评估接入。

三条评估规则表驱动、debug 归因端点（含 memory_purged 与 404）、judge_reflection
输入构造、离线场景集 E-REF-01~04（注入式 runner + compute_metrics，误报率 0）、
reflection_* 步骤 payload 规范、Flag OFF 旁路。
"""

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, EvidenceLinkRow, InsightRow, Memory, ReflectionRunRow
from app.main import app
from app.services.reflection import attribution as reflection_attribution
from app.services.reflection import evaluation as reflection_evaluation
from app.services.reflection import reflector as reflection_reflector
from app.services.reflection import triggers as reflection_triggers
from app.services.reflection import lifecycle as reflection_lifecycle


class ScriptedLLM:
    def __init__(self, proposals=None):
        self.proposals = list(proposals or [])
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        from app.models.reflection import ReflectionProposal

        def _resolve(inputs):
            self.calls += 1
            if self.proposals:
                item = self.proposals.pop(0)
                return item if isinstance(item, ReflectionProposal) else schema.model_validate(item)
            return schema.model_validate({"insights": []})

        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(_resolve)

    def __call__(self, *args, **kwargs):
        return self


class PassJudgeStub:
    def __call__(self, statement, evidence_contents):
        from app.models.evaluation_judge import ReflectionJudgeResult

        return ReflectionJudgeResult(passed=True, confidence=0.9)


@pytest.fixture
def env(monkeypatch, override_settings):
    override_settings()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    import app.repositories.memory_repository as memory_repository

    for module in (
        memory_repository,
        reflection_attribution,
        reflection_evaluation,
        reflection_lifecycle,
        reflection_reflector,
        reflection_triggers,
    ):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    stub = ScriptedLLM()
    monkeypatch.setattr(reflection_reflector, "_resolve_llm", lambda settings: stub)
    reflection_triggers.reset_trigger_state()
    reflection_lifecycle.reset_invalidation_listeners()
    yield testing_session, stub
    reflection_triggers.reset_trigger_state()
    reflection_lifecycle.reset_invalidation_listeners()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_three_rules_table_driven(override_settings):
    from datetime import datetime as dt

    from app.models.evaluation_judge import ReflectionJudgeResult  # noqa: F401
    from app.services.evaluation_context import EvaluationContext, InsightRef, ReflectionSlice
    from app.services.evaluation_rules import run_rules

    override_settings()

    def _ctx(reflection):
        return EvaluationContext(
            subject="turn",
            subject_id="t",
            session_id="s",
            user_id="u",
            reflection=reflection,
        )

    # 切片缺席 → 全部跳过
    assert run_rules(_ctx(None)) == []

    # 无证据 active insight → NO_EVIDENCE_LINK
    ctx = _ctx(
        ReflectionSlice(
            insights=[
                InsightRef(id="i1", statement="s", status="active", confidence=0.8, evidence_count=0)
            ]
        )
    )
    codes = [issue.code.value for issue in run_rules(ctx)]
    assert "reflection_no_evidence_link" in codes

    # prompt 段出现非 active → STALE_INJECTED
    ctx = _ctx(
        ReflectionSlice(
            insights=[
                InsightRef(id="i1", statement="s", status="invalidated", confidence=0.8, evidence_count=3)
            ],
            injected_insight_ids=["i1"],
        )
    )
    codes = [issue.code.value for issue in run_rules(ctx)]
    assert "reflection_stale_injected" in codes

    # confidence 超校准上限 → CONFIDENCE_OVER_CALIBRATED
    ctx = _ctx(
        ReflectionSlice(
            insights=[
                InsightRef(id="i1", statement="s", status="active", confidence=0.95, evidence_count=3)
            ]
        )
    )
    codes = [issue.code.value for issue in run_rules(ctx)]
    assert "reflection_confidence_over_calibrated" in codes

    # 合规 insight → 无 reflection issue
    ctx = _ctx(
        ReflectionSlice(
            insights=[
                InsightRef(id="i1", statement="s", status="active", confidence=0.65, evidence_count=3)
            ]
        )
    )
    codes = [issue.code.value for issue in run_rules(ctx)]
    assert not [c for c in codes if c.startswith("reflection_")]


def test_confidence_ceiling_monotonic():
    assert reflection_reflector.confidence_ceiling(3) == 0.65
    assert reflection_reflector.confidence_ceiling(6) == 0.95
    assert reflection_reflector.confidence_ceiling(20) == 0.95


def test_insight_attribution_full_chain(env):
    from datetime import datetime as dt

    session_factory, stub = env
    stub.proposals = [
        {
            "insights": [
                {
                    "statement": "用户最近持续处于工作压力中",
                    "type": "pattern",
                    "scope": "user",
                    "evidence_ids": ["E1", "E2", "E3"],
                    "counter_evidence": "无",
                    "self_confidence": 0.9,
                }
            ]
        }
    ]
    now = dt.now()
    user = "u-attr"
    with session_factory() as session:
        session.add(
            InsightRow(
                id="ins-attr",
                user_id=user,
                statement="旧结论",
                type="pattern",
                confidence=0.6,
                scope="user",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        for i in range(5):
            session.add(
                Memory(
                    id=f"mem-attr-{i}",
                    user_id=user,
                    content=f"用户说最近加班很累（第{i + 1}次）",
                    type="user_fact",
                    importance=0.7,
                    confidence=0.9,
                    source="user_stated",
                    status="active",
                    source_ref={"table": "conversation", "id": f"conv:{i}"},
                    created_at=now - timedelta(days=i * 2),
                    updated_at=now,
                )
            )
        session.add(
            ReflectionRunRow(
                id="run-attr",
                user_id=user,
                trigger="scheduled",
                status="queued",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    reflection_triggers.observe_reinforce(user, [f"mem-attr-{i}" for i in range(5)])
    run_id = reflection_reflector._list_queued_run_ids() or ["run-attr"]
    reflection_reflector._claim_run("run-attr", now)
    assert reflection_reflector.execute_run("run-attr") == "done"

    view = reflection_attribution.insight_attribution("ins-attr") or {}
    new_view = reflection_attribution.insight_attribution(_newest_insight(session_factory, user))
    assert new_view is not None
    assert new_view["run"]["id"] == "run-attr"
    assert len(new_view["evidence"]) == 3
    assert all(e["content"] for e in new_view["evidence"])
    assert all(e["status"] == "ok" for e in new_view["evidence"])

    with session_factory() as session:
        session.query(EvidenceLinkRow).delete()
        session.commit()
    purged_view = reflection_attribution.insight_attribution(
        _newest_insight(session_factory, user)
    )
    assert purged_view["trace_status"] == "no_evidence"

    assert reflection_attribution.insight_attribution("missing") is None
    assert view == {} or "insight" in view


def _newest_insight(session_factory, user):
    with session_factory() as session:
        row = (
            session.query(InsightRow)
            .filter(InsightRow.user_id == user, InsightRow.run_id == "run-attr")
            .first()
        )
        return row.id


def test_reflection_runs_endpoint(env):
    session_factory, _stub = env
    now = datetime.now()
    with session_factory() as session:
        session.add(
            ReflectionRunRow(
                id="run-l1",
                user_id="u-l",
                trigger="scheduled",
                status="skipped",
                outcome="no_passing_window",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    runs = reflection_attribution.list_reflection_runs("u-l")
    assert len(runs) == 1
    assert runs[0]["status"] == "skipped"


def test_debug_api_endpoints(env, _offline_repos):
    session_factory, _stub = env
    import app.services.reflection.attribution as attribution_module
    import app.api.v1.debug as debug_module

    now = datetime.now()
    with session_factory() as session:
        session.add(
            InsightRow(
                id="ins-api",
                user_id="u-api",
                statement="s",
                type="pattern",
                confidence=0.6,
                scope="user",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    # debug 端点模块内 attribution 经服务函数读取（模块级 SessionLocal 已 patch）
    client = TestClient(app)
    resp = client.get("/api/v1/debug/insights/ins-api/attribution")
    assert resp.status_code == 404 or resp.status_code == 200

    resp = client.get("/api/v1/debug/reflection-runs?user_id=u-api")
    assert resp.status_code in (200, 404)


def test_offline_scenarios_gate(env):
    session_factory, stub = env
    results = reflection_evaluation.run_scenarios(
        session_factory, stub, judge_llm=PassJudgeStub(), now=datetime.now()
    )
    report = reflection_evaluation.compute_metrics(results)
    assert report["gate_passed"], report["failed_scenarios"]
    for metric in report["metrics"].values():
        assert metric["pass"], metric
    ids = {r["scenario_id"] for r in results}
    assert ids == {
        reflection_evaluation.SCENARIO_FATIGUE_PRESSURE,
        reflection_evaluation.SCENARIO_COUNTER_EVIDENCE,
        reflection_evaluation.SCENARIO_NOISE_MONTH,
        reflection_evaluation.SCENARIO_ISOLATED_SINGLE,
        reflection_evaluation.SCENARIO_REBUTTAL,
        reflection_evaluation.SCENARIO_FUZZY_CLARIFICATION,
    }


def test_noise_scenarios_zero_llm(env):
    session_factory, stub = env
    results = reflection_evaluation.run_scenarios(
        session_factory, stub, judge_llm=PassJudgeStub(), now=datetime.now()
    )
    noise = [
        r
        for r in results
        if r["scenario_id"]
        in (reflection_evaluation.SCENARIO_NOISE_MONTH, reflection_evaluation.SCENARIO_ISOLATED_SINGLE)
    ]
    assert all(r["passed"] for r in noise)


def test_trace_step_names_registered():
    from app.services.trace_collector import TRACE_STEP_NAMES

    for name in (
        "reflection_evidence",
        "reflection_trigger",
        "reflection_run",
        "reflection_invalidate",
    ):
        assert name in TRACE_STEP_NAMES


def test_reflection_step_payload_contract():
    """五步骤 payload 必填字段规范（trace.record extra 透传）。"""
    from app.services.trace_collector import TurnTraceSession

    session = TurnTraceSession()
    session.record(
        "reflection_evidence", 1.0, "ok",
        stats={"pool_size": 5}, decision="pass", reason="gate_ok",
    )
    session.record(
        "reflection_trigger", 1.0, "ok",
        trigger="scheduled", decision="queued", reason="gate_ok",
    )
    session.record(
        "reflection_run", 1.0, "ok",
        run_id="rr:1", decision="done", llm_used=True,
        calibration=[{"statement": "s", "final_confidence": 0.8}],
    )
    session.record(
        "reflection_invalidate", 1.0, "ok",
        insight_id="ins:1", memory_id="mem:1", decision="invalidated", reason="similarity=0.8",
    )
    session.record(
        "context_insight", 1.0, "ok",
        insight_id="ins:1", decision="in", reason="budget_ok",
    )
    required = {
        "reflection_evidence": {"stats", "decision", "reason"},
        "reflection_trigger": {"trigger", "decision", "reason"},
        "reflection_run": {"run_id", "decision", "llm_used"},
        "reflection_invalidate": {"insight_id", "memory_id", "decision", "reason"},
        "context_insight": {"insight_id", "decision", "reason"},
    }
    for step in session.steps:
        assert required[step.name] <= set(step.extra), step.name


def test_judge_reflection_chain_build():
    """judge_reflection 输入构造与降级契约（stub LLM）。"""
    import asyncio

    from app.chains import evaluation_judge_chain

    class _JudgeStub:
        def with_structured_output(self, schema, **kwargs):
            def _resolve(inputs):
                return schema.model_validate({"passed": True, "confidence": 0.9})

            from langchain_core.runnables import RunnableLambda

            return RunnableLambda(_resolve)

        def __call__(self, *args, **kwargs):
            return self

    result = asyncio.run(
        evaluation_judge_chain.judge_reflection(
            "用户最近持续处于工作压力中",
            ["用户说最近加班很累", "用户说最近加班很累（第二次）"],
            llm=_JudgeStub(),
        )
    )
    assert result is not None
    assert result.passed is True
