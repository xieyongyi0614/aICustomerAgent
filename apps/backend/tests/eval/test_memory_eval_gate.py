"""MEM-010 Eval Gate：Memory 2.0 场景集离线执行与门槛判定。

双态执行入口：
- Flag ON 影子态 = 本文件（确定性 stub：LLM 由场景级拒绝表驱动、向量由字符桶
  伪语义函数驱动），逐场景走真实 memory2 链路（ingest→evaluate→lifecycle→
  retriever→commands），聚合 E-MEM-01~06 报告并断言 Gate 通过。
- Flag OFF golden 态 = tests/golden（prompt_snapshots 字节级对比），由
  regression-checklist 引用执行。
报告归档：tests/eval/reports/mem-{date}.json。
"""

import asyncio
import datetime
import json
import math
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, Memory as MemoryRow, MemoryCandidateRow, MemoryLinkRow
from app.core.settings import get_settings
from app.repositories import memory_repository
from app.services.memory2 import (
    attribution,
    commands,
    embeddings,
    evaluator,
    ingest,
    lifecycle,
    offline_metrics,
    retriever,
)
from app.services.memory2.offline_metrics import build_report

SCENARIO_DIR = Path(__file__).parent / "memory_scenarios"
REPORT_DIR = Path(__file__).parent / "reports"


def _fake_vector(text: str) -> list[float]:
    """确定性伪语义：字符桶词袋。改述查询与原句共享关键字 → 余弦显著高于无关句。"""
    vector = [0.0] * 64
    for char in (text or ""):
        vector[ord(char) % 64] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class _StubLLM:
    """确定性兜底 stub：命中场景拒绝表 → reject，否则 approve。"""

    def __init__(self):
        self.calls = 0
        self.reject_contents: set[str] = set()

    async def __call__(self, content, proposed_type, related_contents, llm=None):
        from app.models.memory import EvaluationVerdict

        self.calls += 1
        if content in self.reject_contents:
            return EvaluationVerdict(approve=False, reason="疑似错误信息")
        return EvaluationVerdict(approve=True, type=None, reason="离线确定性兜底")


@pytest.fixture
def gate_env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (
        attribution,
        commands,
        evaluator,
        ingest,
        lifecycle,
        memory_repository,
        retriever,
    ):
        monkeypatch.setattr(module, "SessionLocal", testing_session)

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_eval_threshold_high", 0.75)
    monkeypatch.setattr(settings, "memory_eval_threshold_low", 0.35)
    monkeypatch.setattr(settings, "memory_eval_weight_source", 0.35)
    monkeypatch.setattr(settings, "memory_eval_weight_novelty", 0.30)
    monkeypatch.setattr(settings, "memory_eval_weight_affinity", 0.20)
    monkeypatch.setattr(settings, "memory_eval_weight_salience", 0.15)
    monkeypatch.setattr(settings, "memory_conflict_threshold", 0.6)
    monkeypatch.setattr(settings, "memory_retrieval_budget", 800)
    monkeypatch.setattr(settings, "memory_reinforce_boost", 0.1)

    stub = _StubLLM()
    monkeypatch.setattr(evaluator, "_ask_llm", stub)
    monkeypatch.setattr(embeddings, "embed_query", _fake_vector)

    lifecycle.reset_reinforce_buffer()
    embeddings.reset_queue()
    yield {"session": testing_session, "stub": stub}
    lifecycle.reset_reinforce_buffer()
    embeddings.reset_queue()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _active_memories():
    with memory_repository.SessionLocal() as session:
        rows = session.query(MemoryRow).filter_by(status="active").all()
        for row in rows:
            session.expunge(row)
        return rows


def _row(memory_id):
    if not memory_id:
        return None
    with memory_repository.SessionLocal() as session:
        row = session.get(MemoryRow, memory_id)
        if row is None:
            return None
        session.refresh(row)
        session.expunge(row)
        return row


class ScenarioRunner:
    def __init__(self, stub: _StubLLM):
        self.stub = stub
        self.refs: dict[str, str] = {}
        self.context_violations: list[str] = []
        self.probe_count = 0

    def run(self, scenario: dict) -> dict:
        failures: list[str] = []
        self.refs = {}
        self.probe_count = 0
        self.stub.reject_contents = set(scenario.get("llm_reject_contents", []))
        self._reset_db()
        evaluator.reset_evaluator_state()
        for step in scenario.get("steps", []):
            handler = getattr(self, f"_do_{step['action']}", None)
            if handler is None:
                failures.append(f"未知步骤 action={step['action']}")
                continue
            failures.extend(handler(step))
        return {
            "scenario_id": scenario["id"],
            "kind": scenario.get("kind", ""),
            "passed": not failures,
            "failures": failures,
            "probe_count": self.probe_count,
        }

    def _reset_db(self) -> None:
        with memory_repository.SessionLocal() as session:
            session.query(MemoryLinkRow).delete(synchronize_session=False)
            session.query(MemoryRow).delete(synchronize_session=False)
            session.query(MemoryCandidateRow).delete(synchronize_session=False)
            session.commit()

    def _expect(self, step) -> dict:
        return step.get("expect", {})

    def _check(self, failures: list[str], condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    def _do_seed(self, step) -> list[str]:
        failures: list[str] = []
        row = self._create_candidate(step)
        before = self.stub.calls
        decision = asyncio.run(evaluator.evaluate_candidate(row, self._active_contents()))
        expect = self._expect(step)
        memory_id = decision.memory_id
        if decision.action == "approve" and memory_id:
            self.refs[step["ref"]] = memory_id
            memory_repository.update_embeddings_batch(
                [(memory_id, _fake_vector(step["content"]))]
            )
        if "approved" in expect:
            self._check(
                failures,
                (decision.action == "approve") == expect["approved"],
                f"{step['ref']} approved 期望 {expect['approved']}，实际 {decision.action}",
            )
        if "salience" in expect:
            self._check(
                failures,
                _row(memory_id) is not None
                and _row(memory_id).salience == pytest.approx(expect["salience"]),
                f"{step['ref']} salience 期望 {expect['salience']}",
            )
        if "confidence_max" in expect:
            confidence = _row(memory_id).confidence if _row(memory_id) else 1.0
            self._check(
                failures,
                confidence <= expect["confidence_max"],
                f"{step['ref']} confidence {confidence} 超上限 {expect['confidence_max']}",
            )
        if "reason" in expect:
            self._check(
                failures,
                _candidate(row.id).reason == expect["reason"],
                f"{step['ref']} reason 期望 {expect['reason']}，实际 {_candidate(row.id).reason}",
            )
        if "llm_used" in expect:
            self._check(
                failures,
                self.stub.calls - before == expect["llm_used"],
                f"{step['ref']} LLM 调用数期望 {expect['llm_used']}，实际 {self.stub.calls - before}",
            )
        return failures

    def _do_seed_many(self, step) -> list[str]:
        for index in range(step["count"]):
            child = dict(step)
            child["ref"] = f"{step.get('ref', 'many')}-{index}"
            child["content"] = step["template"].format(i=index + 1)
            child["source_id"] = f"{child['ref']}"
            self._do_seed(child)
        return []

    def _do_seed_hypothetical(self, step) -> list[str]:
        child = dict(step)
        child["visibility"] = "hypothetical"
        return self._do_seed(child)

    def _do_remember(self, step) -> list[str]:
        failures: list[str] = []
        before = self.stub.calls
        outcome = asyncio.run(commands.handle("u1", step["message"]))
        expect = self._expect(step)
        self._check(
            failures,
            outcome == expect.get("outcome"),
            f"remember outcome 期望 {expect.get('outcome')}，实际 {outcome}",
        )
        if "llm_used" in expect:
            self._check(
                failures,
                self.stub.calls - before == expect["llm_used"],
                f"remember LLM 调用数期望 0，实际 {self.stub.calls - before}",
            )
        if "salience" in expect:
            object_text = step["message"].split("记住", 1)[1].strip()
            matched = [m for m in _active_memories() if object_text in m.content]
            self._check(
                failures,
                bool(matched) and matched[0].salience == pytest.approx(expect["salience"]),
                f"remember salience 期望 {expect['salience']}",
            )
            if matched:
                self.refs[step["ref"]] = matched[0].id
        return failures

    def _do_forget(self, step) -> list[str]:
        failures: list[str] = []
        outcome = asyncio.run(commands.handle("u1", step["message"]))
        expect = self._expect(step)
        self._check(
            failures,
            outcome == expect.get("outcome"),
            f"forget outcome 期望 {expect.get('outcome')}，实际 {outcome}",
        )
        for ref in expect.get("deleted_refs", []):
            row = _row(self.refs.get(ref, ""))
            self._check(
                failures,
                row is not None and row.status == "forgotten",
                f"{ref} 应被遗忘，实际 {row.status if row else 'missing'}",
            )
        for ref in expect.get("intact_refs", []):
            row = _row(self.refs.get(ref, ""))
            self._check(
                failures,
                row is not None and row.status == "active",
                f"{ref} 应保持 active，实际 {row.status if row else 'missing'}",
            )
        return failures

    def _do_probe(self, step) -> list[str]:
        failures: list[str] = []
        self.probe_count += 1
        result = retriever.retrieve("u1", step["query"], top_k=step.get("top_k"))
        result_ids = [item.memory.id for item in result.items]
        result_refs = [self._ref_of(mid) for mid in result_ids]
        total_chars = sum(len(item.memory.content) for item in result.items)
        if total_chars > get_settings().memory_retrieval_budget:
            self.context_violations.append(
                f"{step.get('query')}: 检索段 {total_chars} 超预算"
            )
        for mid in result_ids:
            row = _row(mid)
            if row is not None and row.visibility == "hypothetical":
                self.context_violations.append(f"{step.get('query')}: hypothetical 注入")
        if "expect_top" in step:
            self._check(
                failures,
                bool(result_refs) and result_refs[0] == step["expect_top"],
                f"probe '{step['query']}' top1 期望 {step['expect_top']}，实际 {result_refs}",
            )
        for ref in step.get("expect_ids", []):
            self._check(failures, ref in result_refs, f"probe 应含 {ref}，实际 {result_refs}")
        for ref in step.get("expect_not_ids", []):
            self._check(
                failures, ref not in result_refs, f"probe 不应含 {ref}，实际 {result_refs}"
            )
        if "max_results" in step:
            self._check(
                failures,
                len(result_ids) <= step["max_results"],
                f"probe 结果数 {len(result_ids)} 超上限 {step['max_results']}",
            )
        if step.get("expect_no_hypothetical"):
            self._check(
                failures,
                all(
                    (_row(mid).visibility if _row(mid) else None) != "hypothetical"
                    for mid in result_ids
                ),
                "probe 结果含 hypothetical",
            )
        return failures

    def _do_supersede_check(self, step) -> list[str]:
        failures: list[str] = []
        new_id = self.refs.get(step["new_ref"])
        for ref in step.get("superseded_refs", []):
            row = _row(self.refs.get(ref, ""))
            self._check(
                failures,
                row is not None
                and row.status == "superseded"
                and row.superseded_by == new_id,
                f"{ref} 应被 {step['new_ref']} superseded，实际 {row.status if row else 'missing'}",
            )
        if "relation" in step:
            links = self._links(new_id)
            self._check(
                failures,
                any(link.relation == step["relation"] for link in links),
                f"缺少 {step['relation']} 链",
            )
        return failures

    def _do_contradicts_check(self, step) -> list[str]:
        failures: list[str] = []
        a_id = self.refs.get(step["a_ref"])
        links = self._links(a_id)
        self._check(
            failures,
            any(link.relation == "contradicts" for link in links),
            f"{step['a_ref']} 缺少 contradicts 链",
        )
        for ref in (step["a_ref"], step["b_ref"]):
            row = _row(self.refs.get(ref, ""))
            self._check(
                failures,
                row is not None and row.status == "active",
                f"{ref} 应保守并存 active，实际 {row.status if row else 'missing'}",
            )
        return failures

    def _do_resolve_contradicts(self, step) -> list[str]:
        dead_id = self.refs.get(step["dead_ref"])
        if dead_id:
            lifecycle.explicit_forget(dead_id)
        return []

    def _do_count_check(self, step) -> list[str]:
        failures: list[str] = []
        count = len(_active_memories())
        self._check(
            failures,
            count == step["expect_active_memories"],
            f"active 记忆数期望 {step['expect_active_memories']}，实际 {count}",
        )
        return failures

    def _do_forget_check(self, step) -> list[str]:
        failures: list[str] = []
        memory_id = self.refs.get(step["ref"], "")
        row = _row(memory_id)
        self._check(
            failures,
            row is not None and row.status == "forgotten",
            f"{step['ref']} 应为 forgotten",
        )
        self._check(
            failures,
            memory_id not in [m.id for m in memory_repository.list_active("u1", "asuna")],
            "结构通道仍命中",
        )
        self._check(
            failures,
            memory_id not in [m.id for m in memory_repository.list_pending_embedding()],
            "补扫通道仍命中",
        )
        result = retriever.retrieve("u1", step["probe_query"], top_k=5)
        self._check(
            failures,
            memory_id not in [item.memory.id for item in result.items],
            "Context 通道仍命中",
        )
        return failures

    def _create_candidate(self, step):
        scenario_ref = step.get("source_id") or f"{step['ref']}"
        visibility = step.get("visibility", "private")
        return ingest._create_candidate(
            user_id="u1",
            character_id="asuna",
            source_table="conversation",
            source_id=f"{scenario_ref}:{abs(hash(step['content'])) % 100000}",
            content=step["content"],
            proposed_type=step.get("type", "user_fact"),
            source_kind=step.get("source", "user_stated"),
            salience_init=step.get("salience", 0.8),
            visibility=visibility,
            source_ref_extra={"relation": step.get("relation"), "confidence": 0.9},
        )

    def _active_contents(self) -> list[str]:
        return [m.content for m in _active_memories()]

    def _links(self, memory_id):
        with memory_repository.SessionLocal() as session:
            rows = (
                session.query(MemoryLinkRow)
                .filter(MemoryLinkRow.memory_id == memory_id)
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def _ref_of(self, memory_id: str) -> str | None:
        for ref, mid in self.refs.items():
            if mid == memory_id:
                return ref
        return None


def _candidate(candidate_id):
    with memory_repository.SessionLocal() as session:
        row = session.get(MemoryCandidateRow, candidate_id)
        if row is None:
            return None
        session.refresh(row)
        session.expunge(row)
        return row


def _load_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for scenario in payload["scenarios"]:
            scenario["kind"] = payload["kind"]
            scenarios.append(scenario)
    return scenarios


def test_memory_eval_gate(gate_env):
    stub = gate_env["stub"]
    scenarios = _load_scenarios()
    assert scenarios, "场景集为空"
    runner = ScenarioRunner(stub)
    results = []
    for scenario in scenarios:
        results.append(runner.run(scenario))

    report = build_report(results, runner.context_violations)
    REPORT_DIR.mkdir(exist_ok=True)
    report_path = REPORT_DIR / f"mem-{datetime.date.today():%Y%m%d}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert report["coverage"]["scenario_count"] >= 20
    failed = [r for r in results if not r["passed"]]
    for item in failed:
        print(f"EVAL-FAIL {item['scenario_id']}({item['kind']}): {item['failures']}")
    assert report["gate_passed"], json.dumps(report["metrics"], ensure_ascii=False)
