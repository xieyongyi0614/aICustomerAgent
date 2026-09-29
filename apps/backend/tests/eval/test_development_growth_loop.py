"""DEV-006 Eval Gate：成长闭环验证（E-DEV-04）。

三周期「连续加班」剧情全链影子执行（P1 ingest/evaluate → P2 reflect → P3
compile/调制演进 → 反驳回退），逐周期归因链审计；Flag 中断矩阵（三开关逐一
关闭 → 闭环在对应环节停止且无越级影响）；报告归档 tests/eval/reports/。
确定性 stub：reflector LLM 脚本化、evaluator 兜底恒准、向量用固定伪语义簇。
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import (
    Base,
    DevelopmentStateRow,
    InsightRow,
    Memory as MemoryRow,
    MemoryCandidateRow,
)
from app.core.settings import get_settings
from app.models.reflection import InsightDraft, ReflectionProposal
from app.repositories import background_job_repository, memory_repository
from app.services.development import aggregate, audit, evaluation, policy
from app.services.memory import (
    attribution as memory_attribution,
    commands as memory_commands,
    evaluator as memory_evaluator,
    ingest as memory_ingest,
    job_worker as memory_job_worker,
    lifecycle as memory_lifecycle,
    retriever as memory_retriever,
)
from app.services.reflection import (
    attribution as reflection_attribution,
    evidence as reflection_evidence,
    evaluation as reflection_evaluation,
    lifecycle as reflection_lifecycle,
    reflector as reflection_reflector,
    triggers as reflection_triggers,
)

pytestmark = pytest.mark.xdist_group("development")

REPORT_DIR = Path(__file__).parent / "reports"

_CLUSTER_VECTOR = [1.0 if i == 3 else 0.1 for i in range(8)]


class ScriptedLLM:
    """反思 LLM 脚本化 stub：按队列返回 proposal（含调用计数）。"""

    def __init__(self, proposals=None):
        self.proposals = list(proposals or [])
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        def _resolve(inputs):
            self.calls += 1
            if self.proposals:
                item = self.proposals.pop(0)
                return item if isinstance(item, ReflectionProposal) else schema.model_validate(item)
            return ReflectionProposal(insights=[])

        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(_resolve)

    def __call__(self, *args, **kwargs):
        return self


class _EvaluatorStubLLM:
    """候选评估兜底 stub：灰区恒准（approve）。"""

    async def __call__(self, content, proposed_type, related_contents, llm=None):
        from app.models.memory import EvaluationVerdict

        return EvaluationVerdict(approve=True, type=None, reason="离线确定性兜底")


def _proposal(statement: str) -> ReflectionProposal:
    return ReflectionProposal(
        insights=[
            InsightDraft(
                statement=statement,
                type="pattern",
                scope="user",
                evidence_ids=["E1", "E2", "E3"],
                counter_evidence="无",
                self_confidence=0.9,
            )
        ]
    )


@pytest.fixture
def growth_env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (
        memory_attribution,
        memory_commands,
        memory_evaluator,
        memory_ingest,
        memory_job_worker,
        memory_lifecycle,
        memory_retriever,
        memory_repository,
        background_job_repository,
        reflection_attribution,
        reflection_evidence,
        reflection_evaluation,
        reflection_lifecycle,
        reflection_reflector,
        reflection_triggers,
        aggregate,
        policy,
        audit,
        evaluation,
    ):
        monkeypatch.setattr(module, "SessionLocal", testing_session)

    settings = get_settings()

    stub = ScriptedLLM(
        [
            _proposal(evaluation.INSIGHT_STATEMENT_CYCLE1),
            _proposal(evaluation.INSIGHT_STATEMENT_CYCLE2),
        ]
    )
    monkeypatch.setattr(reflection_reflector, "_resolve_llm", lambda settings: stub)
    monkeypatch.setattr(memory_evaluator, "_ask_llm", _EvaluatorStubLLM())

    memory_lifecycle.reset_reinforce_buffer()
    yield {"session": testing_session, "stub": stub}
    memory_lifecycle.reset_reinforce_buffer()
    reflection_lifecycle.reset_invalidation_listeners()
    reflection_lifecycle.reset_insight_created_listeners()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_growth_loop_full_cycle_passes_gate(growth_env, monkeypatch):
    now = datetime.now()
    result = evaluation.run_growth_loop(growth_env["session"], now=now)
    assert result["failures"] == [], result["failures"]
    assert result["stats"]["cycles"] == 3
    assert result["stats"]["rolled_back"] is True
    assert len(result["stats"]["insight_ids"]) == 2

    all_results = evaluation.run_scenarios(growth_env["session"], now=now) + [result]
    report = evaluation.compute_metrics(all_results)
    assert report["gate_passed"] is True, report["failed_scenarios"]
    assert report["metrics"]["E-DEV-04"]["pass"] is True

    REPORT_DIR.mkdir(exist_ok=True)
    report_path = REPORT_DIR / f"dev-growth-{datetime.now():%Y%m%d}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    assert report_path.exists()


def test_growth_loop_amplitude_evolves_with_new_evidence(growth_env):
    now = datetime.now()
    result = evaluation.run_growth_loop(growth_env["session"], now=now)
    assert result["failures"] == []
    insight_ids = result["stats"]["insight_ids"]
    confidence1, confidence2 = evaluation._insight_confidences(
        growth_env["session"], insight_ids
    )
    assert confidence2 > confidence1
    with growth_env["session"]() as session:
        states = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.key == "goal.user_care.weight",
                DevelopmentStateRow.source_insight_id == insight_ids[1],
            )
            .all()
        )
        assert states
        delta2 = float(states[0].value["tier_delta"])
    assert delta2 == pytest.approx(round(confidence2 * 0.5, 2), abs=0.001)


def test_growth_loop_cycle2_experience_ingested_via_p1(growth_env):
    now = datetime.now()
    evaluation.run_growth_loop(growth_env["session"], now=now)
    with growth_env["session"]() as session:
        contents = [
            row.content
            for row in session.query(MemoryRow)
            .filter(MemoryRow.user_id == "eval-growth_loop")
            .all()
        ]
    for content in evaluation.NEW_EXPERIENCE_CONTENTS:
        assert content in contents
    with growth_env["session"]() as session:
        cycle2_memories = (
            session.query(MemoryRow)
            .filter(
                MemoryRow.user_id == "eval-growth_loop",
                MemoryRow.created_at >= now - timedelta(minutes=1),
            )
            .all()
        )
        assert cycle2_memories
        assert all(row.embedding is not None for row in cycle2_memories)
