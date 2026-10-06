"""REL-004 关系域离线评估：审计切片 + 场景集 + Gate 指标 + 只读 DB 报告。

场景 runner 注入式（0 LLM）：调用方负责 SessionLocal 环境与 Flag 开关；场景
数据按 user_id 隔离。E-REL-03（evolve 字节级）由 scripts/replay_relationship.py
在 Regression Gate 承担，不入场景集。
"""

from datetime import datetime

from app.core import timeutil
from app.core.db import (
    InsightRow,
    Memory,
    RelationshipMilestoneRow,
    SessionLocal,
)
from app.core.settings import get_settings
from app.models.relationship import RelationshipDelta, RelationshipEvent
from app.prompts.builder import PromptBuilder
from app.repositories import (
    memory_repository,
    relationship_event_repository,
    relationship_milestone_repository,
)
from app.services.relationship import narrative as relationship_narrative
from app.services.relationship import shared as relationship_shared
from app.services.relationship import patterns as relationship_patterns
from app.services.conversation.context import _select_shared_entries
from app.services.evaluation.context import (
    EvaluationContext,
    NarrativeFactRef,
    NarrativeMilestoneRef,
    NarrativeSlice,
)
from app.services.evaluation.rules.relationship import (
    NarrativeFactProvenanceRule,
    NarrativeMilestoneProvenanceRule,
)
from app.services.memory import ingest
from app.core.db import BackgroundJobRow, MemoryCandidateRow
from app.models.conversation import ConversationState
from app.services.development import aggregate

NARRATIVE_PREFIX = "narrative:"

GATE_THRESHOLDS = {
    "E-REL-01": {"metric": "narrative_provenance_rate", "threshold": 1.0},
    "E-REL-02": {"metric": "shared_experience_consistency", "threshold": 1.0},
    "E-REL-04": {"metric": "narrative_milestone_compliance", "threshold": 1.0},
}

KIND_TO_METRIC = {
    "provenance_complete": ("E-REL-01", "E-REL-04"),
    "conflict_resolution_narrative": ("E-REL-01",),
    "shared_experience_reconciliation": ("E-REL-02",),
    "pattern_injection_ablation": ("E-REL-02",),
    "milestone_flood": ("E-REL-04",),
}


def collect_narrative_slice(user_id: str) -> NarrativeSlice | None:
    """EvaluationContext 只读切片：无叙事行 → None（规则跳过）。"""
    with SessionLocal() as session:
        facts = (
            session.query(Memory.id, Memory.type, Memory.source_ref)
            .filter(
                Memory.user_id == user_id,
                Memory.type.in_(["relationship_fact", "milestone_event"]),
            )
            .limit(100)
            .all()
        )
        milestones = (
            session.query(RelationshipMilestoneRow)
            .filter(RelationshipMilestoneRow.user_id == user_id)
            .all()
        )
        insight_ids = {
            row.id
            for row in session.query(InsightRow.id)
            .filter(InsightRow.user_id == user_id)
            .all()
        }
    narrative_milestones = [
        row for row in milestones if (row.milestone_key or "").startswith(NARRATIVE_PREFIX)
    ]
    if not facts and not narrative_milestones:
        return None
    return NarrativeSlice(
        facts=[
            NarrativeFactRef(id=row_id, type=memory_type, source_ref=dict(ref or {}))
            for row_id, memory_type, ref in facts
        ],
        narrative_milestones=[
            NarrativeMilestoneRef(
                id=row.id, milestone_key=row.milestone_key, meta=dict(row.meta or {})
            )
            for row in narrative_milestones
        ],
        insight_ids=insight_ids,
    )


def run_scenarios(session_factory, now: datetime | None = None) -> list[dict]:
    """注入式场景 runner：调用方负责 SessionLocal 环境与确定性数据（0 LLM）。"""
    return [
        _run_provenance_complete(now),
        _run_conflict_resolution_narrative(now),
        _run_shared_experience_reconciliation(now),
        _run_pattern_injection_ablation(now),
        _run_milestone_flood(now),
    ]


def compute_metrics(scenario_results: list[dict]) -> dict:
    """场景结果 → E-REL 指标报告（纯函数）。"""
    by_metric: dict[str, list[dict]] = {metric_id: [] for metric_id in GATE_THRESHOLDS}
    for result in scenario_results:
        for metric_id in KIND_TO_METRIC.get(result["scenario_id"], ()):
            by_metric[metric_id].append(result)
    metrics = {}
    for metric_id, spec in GATE_THRESHOLDS.items():
        results = by_metric[metric_id]
        total = len(results)
        score = (
            sum(1 for r in results if not r["failures"]) / total if total else 0.0
        )
        metrics[metric_id] = {
            "metric": spec["metric"],
            "score": round(score, 4),
            "threshold": spec["threshold"],
            "n": total,
            "pass": bool(total) and score >= spec["threshold"],
        }
    return {
        "generated_at": timeutil.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "gate_passed": all(m["pass"] for m in metrics.values()),
        "failed_scenarios": [
            {"scenario_id": r["scenario_id"], "failures": r["failures"]}
            for r in scenario_results
            if r["failures"]
        ],
    }


def build_db_report() -> dict:
    """只读 DB 统计（offline_evaluator relationship 小节引用）。"""
    with SessionLocal() as session:
        milestones = session.query(RelationshipMilestoneRow).all()
        facts = (
            session.query(Memory.source_ref)
            .filter(Memory.type.in_(["relationship_fact", "milestone_event"]))
            .all()
        )
        insight_ids = {row.id for row in session.query(InsightRow.id).all()}
    provenanced = sum(
        1
        for (ref,) in facts
        if (ref or {}).get("table") in ("relationship_events", "relationship_milestones")
        and (ref or {}).get("id")
    )
    narrative_milestones = [
        row for row in milestones if (row.milestone_key or "").startswith(NARRATIVE_PREFIX)
    ]
    provenanced_milestones = sum(
        1
        for row in narrative_milestones
        if (row.meta or {}).get("source") == "insight"
        and (row.meta or {}).get("insight_id") in insight_ids
    )
    return {
        "milestones_total": len(milestones),
        "narrative_milestones": len(narrative_milestones),
        "milestone_provenance_rate": (
            round(provenanced_milestones / len(narrative_milestones), 4)
            if narrative_milestones
            else None
        ),
        "narrative_facts_total": len(facts),
        "provenance_rate": round(provenanced / len(facts), 4) if facts else None,
    }


def _claim_pending_jobs() -> None:
    """模拟 job_worker 认领：pending → running（handler 只处理 running 载荷）。"""

    with SessionLocal() as session:
        rows = (
            session.query(BackgroundJobRow)
            .filter(
                BackgroundJobRow.job_type
                == relationship_narrative.JOB_TYPE_NARRATIVE,
                BackgroundJobRow.status == "pending",
            )
            .all()
        )
        for row in rows:
            row.status = "running"
        session.commit()


def _result(scenario_id: str, failures: list[str], stats: dict) -> dict:
    return {"scenario_id": scenario_id, "failures": failures, "stats": stats}


def _seed_insight(insight_id: str, user_id: str, statement: str, now: datetime) -> None:
    with SessionLocal() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                statement=statement,
                type="pattern",
                confidence=0.9,
                scope="relationship",
                status="active",
                run_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _seed_event(
    event_id: str,
    user_id: str,
    cause: str,
    created_at: datetime,
    event_type: str = "intimate_moment",
    source: str = "conversation",
) -> None:
    relationship_event_repository.create_event(
        RelationshipEvent(
            id=event_id,
            user_id=user_id,
            session_id="s-eval",
            type=event_type,
            magnitude="strong",
            impact=RelationshipDelta(intimacy=0.05),
            confidence=0.9,
            source=source,
            cause=cause,
            created_at=created_at,
        )
    )


def _run_provenance_complete(now: datetime) -> dict:
    user = "rel-eval-prov"
    _seed_insight("ins-eval-prov", user, "我们熬夜一起赶工了一个通宵", now)
    relationship_narrative.on_insight_created(
        user,
        [{"insight_id": "ins-eval-prov", "scope": "relationship", "confidence": 0.9}],
    )
    _claim_pending_jobs()
    processed = relationship_narrative.run_narrative_jobs()
    failures: list[str] = []
    if processed != 1:
        failures.append(f"processed={processed} != 1")
    milestones = relationship_milestone_repository.list_milestones(user)
    if len(milestones) != 1:
        failures.append(f"milestones={len(milestones)} != 1")
    else:
        record = milestones[0]
        if record.meta.get("insight_id") != "ins-eval-prov":
            failures.append("milestone meta 缺少 insight 溯源")
        ingest.ingest_from_relationship_milestone(record)
        with SessionLocal() as session:
            candidate = (
                session.query(MemoryCandidateRow)
                .filter(
                    MemoryCandidateRow.source_table == "relationship_milestones",
                    MemoryCandidateRow.source_id == record.id,
                )
                .first()
            )
        if candidate is None:
            failures.append("里程碑转写候选缺失")
    slice_ = collect_narrative_slice(user)
    ctx = EvaluationContext(
        subject="offline_batch",
        subject_id="rel-eval",
        session_id="s",
        user_id=user,
        narrative=slice_,
    )
    for rule in (NarrativeFactProvenanceRule(), NarrativeMilestoneProvenanceRule()):
        if rule.evaluate(ctx) is not None:
            failures.append(f"rule={rule.code.value} 违例")
    return _result("provenance_complete", failures, {"milestones": len(milestones)})


def _run_conflict_resolution_narrative(now: datetime) -> dict:
    user = "rel-eval-conflict"
    _seed_event("ev-conflict", user, "我们吵了一架", now, event_type="conflict")
    _seed_event(
        "ev-settle", user, "冲突解决", now, event_type="none", source="system"
    )
    now_db = timeutil.now()
    with memory_repository.SessionLocal() as session:
        session.add(
            memory_repository.Memory(
                id="mem-conflict-1",
                user_id=user,
                character_id="asuna",
                content="我们吵了一架",
                type="relationship_fact",
                importance=0.75,
                confidence=0.9,
                source="user_derived",
                status="active",
                source_ref={
                    "table": "relationship_events",
                    "id": "ev-conflict",
                },
                created_at=now_db,
                updated_at=now_db,
            )
        )
        session.commit()
    slice_ = collect_narrative_slice(user)
    failures: list[str] = []
    if slice_ is None:
        failures.append("narrative slice 缺席")
    else:
        types = {fact.type for fact in slice_.facts}
        if "relationship_fact" not in types:
            failures.append("冲突叙事未转写")
        ctx = EvaluationContext(
            subject="offline_batch",
            subject_id="rel-eval",
            session_id="s",
            user_id=user,
            narrative=slice_,
        )
        if NarrativeFactProvenanceRule().evaluate(ctx) is not None:
            failures.append("存在孤儿叙事事实")
    return _result("conflict_resolution_narrative", failures, {})


def _run_shared_experience_reconciliation(now: datetime) -> dict:
    user = "rel-eval-shared"
    _seed_event("ev-1", user, "一起看了日出", now)
    now_db = timeutil.now()
    with memory_repository.SessionLocal() as session:
        session.add(
            memory_repository.Memory(
                id="mem-shared-1",
                user_id=user,
                character_id="asuna",
                content="一起完成了项目",
                type="experience",
                importance=0.9,
                confidence=0.9,
                source="user_derived",
                status="active",
                created_at=now_db,
                updated_at=now_db,
            )
        )
        session.commit()
    entries = relationship_shared.collect_shared_experiences(user)
    failures: list[str] = []
    if len(entries) != 2:
        failures.append(f"对账失败：投影 {len(entries)} != 源 2")
    ordered = [entry.occurred_at for entry in entries]
    if ordered != sorted(ordered):
        failures.append("投影未按时间序")
    selected, _ = _select_shared_entries(entries)
    section = PromptBuilder.build_shared_experience_section(
        _state_with(entries=selected)
    )
    if section is None or len(section) > get_settings().relationship_shared_budget_chars:
        failures.append("Context 段预算超限或缺席")
    return _result("shared_experience_reconciliation", failures, {"entries": len(entries)})


def _run_pattern_injection_ablation(now: datetime) -> dict:
    user_with = "rel-eval-pat-a"
    user_without = "rel-eval-pat-b"
    _seed_insight("ins-eval-pat", user_with, "他更愿意在深夜向我倾诉", now)

    aggregate.upsert_modulation(
        user_id=user_with,
        kind="pattern",
        key="goal.user_care.weight",
        value={"tier_delta": 0.4},
        strength=0.8,
        source_insight_id="ins-eval-pat",
        now=now,
    )
    with_patterns, _ = relationship_patterns_read(user_with)
    without_patterns, _ = relationship_patterns_read(user_without)
    failures: list[str] = []
    if not with_patterns:
        failures.append("有关系模式的用户未注入")
    if without_patterns:
        failures.append("无数据用户出现注入（凭空条目）")
    section = PromptBuilder.build_relationship_pattern_section(
        _state_with(patterns=with_patterns)
    )
    if section is None or len(section) > get_settings().relationship_pattern_budget_chars:
        failures.append("关系模式段预算超限或缺席")
    return _result("pattern_injection_ablation", failures, {})


def _run_milestone_flood(now: datetime) -> dict:
    user = "rel-eval-flood"
    _seed_insight("ins-flood-1", user, "我们熬夜一起赶工了一个通宵", now)
    _seed_insight("ins-flood-2", user, "我们一起熬过了项目上线", now)
    _seed_insight("ins-flood-3", user, "用户喜欢深夜工作", now)
    for insight_id in ("ins-flood-1", "ins-flood-2", "ins-flood-3"):
        relationship_narrative.on_insight_created(
            user,
            [{"insight_id": insight_id, "scope": "relationship", "confidence": 0.9}],
        )
    _claim_pending_jobs()
    relationship_narrative.run_narrative_jobs()
    milestones = relationship_milestone_repository.list_milestones(user)
    failures: list[str] = []
    if len(milestones) != 1:
        failures.append(f"频控失效：落了 {len(milestones)} 条（预期 1）")
    if milestones and milestones[0].milestone_key != "narrative:all_nighter":
        failures.append("白名单匹配不符合确定性排序预期")
    relationship_narrative.process_insight("ins-flood-1")
    again = relationship_milestone_repository.list_milestones(user)
    if len(again) != 1:
        failures.append("同 Insight 重复触发")
    return _result("milestone_flood", failures, {"milestones": len(milestones)})


def relationship_patterns_read(user_id: str):
    return relationship_patterns.read_relationship_patterns(user_id)


def _state_with(entries=None, patterns=None):
    return ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="",
        shared_experiences=entries or [],
        relationship_patterns=patterns or [],
    )
