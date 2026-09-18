"""Reflection 离线评估（REF-006，模式对齐 MEM-010）。

三层结构：
- SCENARIOS + run_scenarios(...)：场景定义与注入式全链 runner（session_factory 与
  LLM stub 由调用方注入——tests/eval 运行器负责环境准备与确定性 stub，离线零真实
  调用；服务层不做 monkeypatch）。
- compute_metrics(...)：纯函数聚合场景结果 → E-REF-01~04 Eval Gate 报告。
- build_db_report(...)：只读 DB 统计（offline_evaluator 的 reflection 小节引用；
  Flag OFF 返回空 dict）。

TOOL-009 §5 Step 3：追加工具效能场景 `run_tool_scenario(...)`（注入式 seeder，
零真实调用）。该场景**不并入** `run_scenarios`/`GATE_THRESHOLDS`，Eval Gate 指标
（E-REF-01~04）保持零改动——工具效能的版本级 Gate 由 TOOL-012 承载。
"""

import logging
from datetime import datetime, timedelta

from app.core.db import (
    EvidenceLinkRow,
    InsightRow,
    Memory,
    ReflectionRunRow,
    SessionLocal,
)
from app.core.settings import get_settings
from app.character.asuna import evaluation as asuna_evaluation
from app.models.reflection import TOOL_INSIGHT_TYPES
from app.services.reflection import lifecycle as reflection_lifecycle
from app.services.reflection import reflector as reflection_reflector
from app.services.reflection import triggers as reflection_triggers
from app.models.reflection import InsightDraft, ReflectionProposal

logger = logging.getLogger(__name__)

SCENARIO_FATIGUE_PRESSURE = "fatigue_pressure"
SCENARIO_COUNTER_EVIDENCE = "counter_evidence"
SCENARIO_NOISE_MONTH = "noise_month"
SCENARIO_ISOLATED_SINGLE = "isolated_single"
SCENARIO_REBUTTAL = "rebuttal"
SCENARIO_FUZZY_CLARIFICATION = "fuzzy_clarification"
SCENARIO_TOOL_EFFECTIVENESS = "tool_effectiveness"

KIND_TO_METRIC = {
    SCENARIO_FATIGUE_PRESSURE: ("E-REF-01", "E-REF-01-JUDGE", "E-REF-02"),
    SCENARIO_COUNTER_EVIDENCE: ("E-REF-02",),
    SCENARIO_NOISE_MONTH: ("E-REF-03",),
    SCENARIO_ISOLATED_SINGLE: ("E-REF-03",),
    SCENARIO_REBUTTAL: ("E-REF-04",),
    SCENARIO_FUZZY_CLARIFICATION: ("E-REF-04",),
}

GATE_THRESHOLDS = {
    "E-REF-01": {"metric": "Insight 证据引用率", "threshold": 1.0},
    "E-REF-01-JUDGE": {"metric": "Reflection Judge 通过率", "threshold": 0.9},
    "E-REF-02": {"metric": "证据门槛有效性", "threshold": 1.0},
    "E-REF-03": {"metric": "误报率（0 Insight 0 LLM）", "threshold": 1.0},
    "E-REF-04": {"metric": "反驳失效有效性", "threshold": 1.0},
}

FATIGUE_CONTENTS = [
    "用户说最近加班很累",
    "用户说最近加班很累（第二次提到）",
    "用户说最近加班很累（第三次提到）",
    "用户说最近加班很累（第四次提到）",
    "用户说最近加班很累（第五次提到）",
]

NOISE_CONTENTS = [
    "用户养了一只叫小雪的猫",
    "用户喜欢在周末爬山",
    "用户在深圳工作",
    "用户不喝咖啡",
    "用户上周去看了牙医",
]


def run_scenarios(session_factory, reflector_stub, judge_llm=None, now=None) -> list[dict]:
    """注入式场景 runner：调用方负责 SessionLocal 环境与 stub；逐场景返回执行结果。"""
    now = now or datetime.now()
    results = [
        _run_pressure_scenario(session_factory, reflector_stub, judge_llm, now),
        _run_counter_evidence_scenario(session_factory, reflector_stub, now),
        _run_noise_scenario(session_factory, now),
        _run_isolated_scenario(session_factory, now),
        _run_rebuttal_scenario(session_factory, reflector_stub, now),
        _run_fuzzy_scenario(session_factory, reflector_stub, now),
    ]
    return results


def _seed_memory(session_factory, memory_id, content, *, created_at, user_id, source="user_stated"):
    with session_factory() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                character_id="asuna",
                content=content,
                type="user_fact",
                importance=0.7,
                confidence=0.9,
                source=source,
                status="active",
                salience=0.8,
                source_ref={"table": "conversation", "id": f"conv:{user_id}:{memory_id}"},
                visibility="private",
                created_at=created_at,
                updated_at=datetime.now(),
            )
        )
        session.commit()


def _seed_cluster(session_factory, user_id, contents, now):
    for index, content in enumerate(contents):
        _seed_memory(
            session_factory,
            f"{user_id}-mem-{index}",
            content,
            created_at=now - timedelta(days=index * 2),
            user_id=user_id,
        )


def _enqueue_and_execute(session_factory, user_id, now, reflector_stub) -> dict:
    """触发（事件路）→ 执行 → 返回 {outcome, insights, llm_calls}。"""
    memory_ids = [row_id for row_id, in _active_memory_ids(session_factory, user_id)]
    reflection_triggers.observe_reinforce(user_id, memory_ids)
    queued = _queued_run_ids(session_factory)
    outcome = None
    calls_before = reflector_stub.calls
    for run_id in queued:
        reflection_reflector._claim_run(run_id, now)
        result = reflection_reflector.execute_run(run_id)
        run = _run_row(session_factory, run_id)
        outcome = run.outcome if run is not None else result
    insights = _insight_rows(session_factory, user_id)
    return {
        "outcome": outcome,
        "insights": insights,
        "llm_calls": reflector_stub.calls - calls_before,
    }


def _run_pressure_scenario(session_factory, reflector_stub, judge_llm, now) -> dict:
    scenario_id = SCENARIO_FATIGUE_PRESSURE
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    reflector_stub.proposals.append(_fatigue_proposal())
    _seed_cluster(session_factory, user_id, FATIGUE_CONTENTS, now)
    result = _enqueue_and_execute(session_factory, user_id, now, reflector_stub)
    insights = result["insights"]
    if not insights:
        failures.append("未产出 Insight")
    for insight in insights:
        links = _evidence_count(session_factory, insight["id"])
        if links < get_settings().v2_reflection_min_evidence:
            failures.append(f"insight={insight['id']} 引用数 {links} 低于门槛")
        if not (insight["confidence"] > 0 and insight["confidence"] <= 0.95):
            failures.append(f"insight={insight['id']} confidence 越界")
    judge_score = 0.0
    if insights and judge_llm is not None:
        verdicts = [
            _judge_one(insight, session_factory, judge_llm) for insight in insights
        ]
        judge_score = sum(verdicts) / len(verdicts) if verdicts else 0.0
        if judge_score < 0.9:
            failures.append(f"Judge 通过率 {judge_score:.2f} < 0.9")
    elif insights:
        failures.append("缺少 Judge 评审")
    return _result(scenario_id, failures, {"insights": len(insights), "judge": judge_score})


def _run_counter_evidence_scenario(session_factory, reflector_stub, now) -> dict:
    scenario_id = SCENARIO_COUNTER_EVIDENCE
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    reflector_stub.proposals.append(
        _under_referenced_proposal()
    )
    _seed_cluster(session_factory, user_id, FATIGUE_CONTENTS, now)
    result = _enqueue_and_execute(session_factory, user_id, now, reflector_stub)
    if result["insights"]:
        failures.append("反例/引用不足场景不应入库 Insight")
    if result["outcome"] != "rejected":
        failures.append(f"预期 rejected，实际 {result['outcome']}")
    return _result(scenario_id, failures, {"outcome": result["outcome"]})


def _run_noise_scenario(session_factory, now) -> dict:
    scenario_id = SCENARIO_NOISE_MONTH
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    _seed_cluster(session_factory, user_id, NOISE_CONTENTS, now)
    decision = reflection_triggers.trigger_for_user(user_id, now=now)
    if decision != "skipped":
        failures.append(f"预期 skipped，实际 {decision}")
    runs = _run_rows(session_factory, user_id)
    if any(run.llm_used for run in runs):
        failures.append("噪声场景出现 LLM 调用")
    if _queued_run_ids(session_factory):
        failures.append("噪声场景不应入队")
    return _result(scenario_id, failures, {"decision": decision})


def _run_isolated_scenario(session_factory, now) -> dict:
    scenario_id = SCENARIO_ISOLATED_SINGLE
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    _seed_memory(
        session_factory,
        f"{user_id}-mem-0",
        "用户喜欢在周末爬山",
        created_at=now - timedelta(days=3),
        user_id=user_id,
    )
    decision = reflection_triggers.trigger_for_user(user_id, now=now)
    if decision != "skipped":
        failures.append(f"孤立单条预期 skipped，实际 {decision}")
    if _insight_rows(session_factory, user_id):
        failures.append("孤立单条场景产出 Insight")
    return _result(scenario_id, failures, {"decision": decision})


def _run_rebuttal_scenario(session_factory, reflector_stub, now) -> dict:
    scenario_id = SCENARIO_REBUTTAL
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    reflector_stub.proposals.append(_fatigue_proposal())
    _seed_cluster(session_factory, user_id, FATIGUE_CONTENTS, now)
    result = _enqueue_and_execute(session_factory, user_id, now, reflector_stub)
    if not result["insights"]:
        return _result(scenario_id, ["前置反思未产出 Insight"], {})
    hook_calls: list = []
    reflection_lifecycle.register_invalidation_listener(lambda uid, changed: hook_calls.append(changed))
    invalidated = reflection_lifecycle.observe_negation(
        user_id, f"{user_id}-neg", "用户最近没有持续的工作压力"
    )
    if not invalidated:
        failures.append("澄清反驳未触发 invalidated")
    if not hook_calls:
        failures.append("失效事件钩子未被调用")
    actives = reflection_lifecycle.list_user_active_insights(user_id)
    if any(insight.id in invalidated for insight in actives):
        failures.append("invalidated 后仍出现在 active 列表")
    return _result(scenario_id, failures, {"invalidated": invalidated})


def _run_fuzzy_scenario(session_factory, reflector_stub, now) -> dict:
    scenario_id = SCENARIO_FUZZY_CLARIFICATION
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    reflector_stub.proposals.append(_fatigue_proposal())
    _seed_cluster(session_factory, user_id, FATIGUE_CONTENTS, now)
    result = _enqueue_and_execute(session_factory, user_id, now, reflector_stub)
    if not result["insights"]:
        return _result(scenario_id, ["前置反思未产出 Insight"], {})
    hook_calls: list = []
    reflection_lifecycle.register_invalidation_listener(lambda uid, changed: hook_calls.append(changed))
    invalidated = reflection_lifecycle.observe_negation(
        user_id, f"{user_id}-fuzzy", "用户最近状态还行"
    )
    if invalidated:
        failures.append("模糊澄清误失效 Insight")
    if hook_calls:
        failures.append("模糊澄清触发事件钩子")
    return _result(scenario_id, failures, {"invalidated": invalidated})


def run_tool_scenario(
    session_factory,
    reflector_stub,
    tool_seeder,
    now=None,
) -> dict:
    """工具效能离线场景（TOOL-009 E13）：注入式 runner，零真实调用。

    `tool_seeder(session_factory, user_id, now)` 由调用方注入（负责铺 `action_records`
    与用户消息）；服务层不做 monkeypatch、不发外部调用。判定：reinforce 计数触发 →
    按 run 裁决的窗口名取资产声明的 Insight 类型/scope 产出 stub 提案 → 执行 run →
    产物类型与窗口一致、证据链指向 `tool:` 命名空间的工具证据。
    """
    now = now or datetime.now()
    scenario_id = SCENARIO_TOOL_EFFECTIVENESS
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    if tool_seeder is None:
        return _result(scenario_id, ["缺少注入式工具证据 seeder"], {})
    tool_seeder(session_factory, user_id, now)
    reflection_triggers.reset_trigger_state()
    calls_before = reflector_stub.calls
    fired = reflection_triggers.observe_tool_evidence_from_records(user_id, now=now)
    window_kind = _queued_window_kind(session_factory)
    expected_type = (
        asuna_evaluation.insight_type_for(window_kind) if window_kind else None
    )
    if expected_type:
        reflector_stub.proposals.append(
            _capability_proposal(
                insight_type=expected_type, scope=asuna_evaluation.scope_for(window_kind)
            )
        )
    outcome = None
    for run_id in _queued_run_ids(session_factory):
        reflection_reflector._claim_run(run_id, now)
        reflection_reflector.execute_run(run_id)
        run = _run_row(session_factory, run_id)
        outcome = run.outcome if run is not None else None
    insights = _insight_rows(session_factory, user_id)
    if not insights:
        failures.append("未产出工具效能 Insight")
    for insight in insights:
        if insight["type"] not in TOOL_INSIGHT_TYPES:
            failures.append(f"insight={insight['id']} 类型越界：{insight['type']}")
        elif expected_type and insight["type"] != expected_type:
            failures.append(
                f"insight={insight['id']} 类型与窗口不符：{insight['type']} != {expected_type}"
            )
        if not _evidence_tool_ids(session_factory, insight["id"]):
            failures.append(f"insight={insight['id']} 证据链未指向工具执行事实")
    return _result(
        scenario_id,
        failures,
        {
            "fired": fired,
            "window_kind": window_kind,
            "outcome": outcome,
            "insights": len(insights),
            "llm_calls": reflector_stub.calls - calls_before,
        },
    )


def _queued_window_kind(session_factory) -> str | None:
    """queued run 裁决的窗口名（工具通道；无 queued run 返回 None）。"""
    with SessionLocal() as session:
        row = (
            session.query(ReflectionRunRow)
            .filter(ReflectionRunRow.status == "queued")
            .order_by(ReflectionRunRow.created_at.asc())
            .first()
        )
        if row is None:
            return None
        return (row.evidence_summary or {}).get("window_kind")


def _capability_proposal(
    *,
    insight_type: str = "capability_note",
    scope: str = "world",
):
    return ReflectionProposal(
        insights=[
            InsightDraft(
                statement="最近天气接口不稳定，先别急着查",
                type=insight_type,
                scope=scope,
                evidence_ids=["E1", "E2", "E3"],
                counter_evidence="失败集中在同一时段，不足以说明长期不可靠",
                self_confidence=0.8,
            )
        ]
    )


def _evidence_tool_ids(session_factory, insight_id: str) -> list[str]:
    from app.services.reflection import evidence as reflection_evidence

    with session_factory() as session:
        rows = (
            session.query(EvidenceLinkRow.memory_id)
            .filter(EvidenceLinkRow.insight_id == insight_id)
            .all()
        )
    return [
        tool_id
        for tool_id in (
            reflection_evidence.tool_id_of_evidence_id(row[0]) for row in rows
        )
        if tool_id is not None
    ]


def compute_metrics(scenario_results: list[dict]) -> dict:
    """场景结果 → E-REF-01~04 指标报告（纯函数）。"""
    by_metric: dict[str, list[dict]] = {metric_id: [] for metric_id in GATE_THRESHOLDS}
    for result in scenario_results:
        for metric_id in KIND_TO_METRIC.get(result["scenario_id"], ()):
            by_metric[metric_id].append(result)
    metrics = {}
    for metric_id, spec in GATE_THRESHOLDS.items():
        results = by_metric[metric_id]
        total = len(results)
        score = sum(1 for r in results if not r["failures"]) / total if total else 0.0
        metrics[metric_id] = {
            "metric": spec["metric"],
            "score": round(score, 4),
            "threshold": spec["threshold"],
            "n": total,
            "pass": bool(total) and score >= spec["threshold"],
        }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "gate_passed": all(m["pass"] for m in metrics.values()),
        "failed_scenarios": [
            {"scenario_id": r["scenario_id"], "failures": r["failures"]}
            for r in scenario_results
            if r["failures"]
        ],
    }


def build_db_report() -> dict:
    """只读 DB 统计（offline_evaluator reflection 小节引用）。"""
    with SessionLocal() as session:
        active = (
            session.query(InsightRow)
            .filter(InsightRow.status == "active")
            .all()
        )
        runs = session.query(ReflectionRunRow).all()
        active_ids = [row.id for row in active]
        linked = 0
        if active_ids:
            linked = (
                session.query(EvidenceLinkRow.insight_id)
                .filter(EvidenceLinkRow.insight_id.in_(active_ids))
                .distinct()
                .count()
            )
    status_counts: dict[str, int] = {}
    for run in runs:
        status_counts[run.status] = status_counts.get(run.status, 0) + 1
    return {
        "active_insights": len(active),
        "evidence_link_rate": round(linked / len(active), 4) if active else None,
        "run_status_counts": status_counts,
    }


def _result(scenario_id: str, failures: list[str], stats: dict) -> dict:
    return {
        "scenario_id": scenario_id,
        "failures": failures,
        "passed": not failures,
        **stats,
    }


def _active_memory_ids(session_factory, user_id) -> list[tuple[str]]:
    with session_factory() as session:
        rows = (
            session.query(Memory.id)
            .filter(Memory.user_id == user_id, Memory.status == "active")
            .all()
        )
        return list(rows)


def _queued_run_ids(session_factory) -> list[str]:
    with SessionLocal() as session:
        rows = (
            session.query(ReflectionRunRow.id)
            .filter(ReflectionRunRow.status == "queued")
            .all()
        )
        return [row[0] for row in rows]


def _run_rows(session_factory, user_id) -> list:
    with SessionLocal() as session:
        rows = (
            session.query(ReflectionRunRow)
            .filter(ReflectionRunRow.user_id == user_id)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return list(rows)


def _run_row(session_factory, run_id):
    with SessionLocal() as session:
        row = session.get(ReflectionRunRow, run_id)
        if row is not None:
            session.expunge(row)
        return row


def _insight_rows(session_factory, user_id) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(InsightRow)
            .filter(InsightRow.user_id == user_id)
            .all()
        )
        return [
            {
                "id": row.id,
                "statement": row.statement,
                "confidence": row.confidence,
                "type": row.type,
            }
            for row in rows
        ]


def _evidence_count(session_factory, insight_id) -> int:
    with SessionLocal() as session:
        return (
            session.query(EvidenceLinkRow)
            .filter(EvidenceLinkRow.insight_id == insight_id)
            .count()
        )


def _judge_one(insight: dict, session_factory, judge_stub) -> float:
    """judge_stub 为同步可调用（statement, evidence_contents) -> ReflectionJudgeResult；
    真链 judge_reflection 由 tests/eval 运行器按需替换。"""
    with SessionLocal() as session:
        links = (
            session.query(EvidenceLinkRow.memory_id)
            .filter(EvidenceLinkRow.insight_id == insight["id"])
            .all()
        )
        memory_ids = [row[0] for row in links]
        contents = (
            session.query(Memory.content).filter(Memory.id.in_(memory_ids)).all()
            if memory_ids
            else []
        )
    verdict = judge_stub(insight["statement"], [row[0] for row in contents])
    if verdict is None:
        return 0.0
    return 1.0 if getattr(verdict, "passed", False) else 0.0


def _fatigue_proposal():
    return ReflectionProposal(
        insights=[
            InsightDraft(
                statement="用户最近持续处于工作压力中",
                type="pattern",
                scope="user",
                evidence_ids=["E1", "E2", "E3"],
                counter_evidence="无",
                self_confidence=0.9,
            )
        ]
    )


def _under_referenced_proposal():
    return ReflectionProposal(
        insights=[
            InsightDraft(
                statement="用户最近持续处于工作压力中",
                type="pattern",
                scope="user",
                evidence_ids=["E1"],
                counter_evidence="无",
                self_confidence=0.9,
            )
        ]
    )
