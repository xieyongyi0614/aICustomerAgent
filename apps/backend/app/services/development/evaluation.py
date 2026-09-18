"""Development 离线评估（DEV-005，模式对齐 REF-006 / MEM-010）。

四层结构：
- collect_slice(...)：EvaluationContext 的只读切片（Flag OFF/无数据 → None）。
- SCENARIOS + run_scenarios(...)：E-DEV-01~03 场景定义与注入式全链 runner
  （session_factory 与确定性 stub 由调用方注入，离线零真实 LLM）。
- compute_metrics(...)：纯函数聚合场景结果 → E-DEV-01~03 Eval Gate 报告。
- build_db_report(...)：只读 DB 统计（offline_evaluator 的 development 小节；
  Flag OFF 返回空 dict）。
"""

import logging
from datetime import datetime, timedelta

from app.core.db import (
    DevelopmentChangeRow,
    DevelopmentStateRow,
    InsightRow,
    SessionLocal,
)
from app.core.settings import get_settings
from app.services.development import aggregate
from app.services.development import audit as development_audit
from app.services.development import policy as development_policy
from app.services.evaluation_context import (
    DevelopmentChangeRef,
    DevelopmentSlice,
    DevelopmentStateRef,
)
from app.core.db import Memory, ReflectionRunRow, EvidenceLinkRow
from app.models.memory import MemoryCandidate, MemoryExtraction
from app.services.memory2 import evaluator as memory_evaluator, ingest as memory_ingest
from app.services.reflection import (
    lifecycle as reflection_lifecycle,
    reflector as reflection_reflector,
)

logger = logging.getLogger(__name__)

SCENARIO_COMPILE_IDEMPOTENT = "compile_idempotent"
SCENARIO_CAP_SATURATION = "cap_saturation"
SCENARIO_CONTRADICTION_ARBITRATION = "contradiction_arbitration"
SCENARIO_REBUTTAL_ROLLBACK = "rebuttal_rollback"
SCENARIO_GROWTH_LOOP = "growth_loop"

KIND_TO_METRIC = {
    SCENARIO_COMPILE_IDEMPOTENT: ("E-DEV-01",),
    SCENARIO_CAP_SATURATION: ("E-DEV-02",),
    SCENARIO_CONTRADICTION_ARBITRATION: ("E-DEV-03",),
    SCENARIO_REBUTTAL_ROLLBACK: ("E-DEV-03",),
    SCENARIO_GROWTH_LOOP: ("E-DEV-04",),
}

GATE_THRESHOLDS = {
    "E-DEV-01": {"metric": "编译一致性与归因完整率", "threshold": 1.0},
    "E-DEV-02": {"metric": "调制可见性与封顶", "threshold": 1.0},
    "E-DEV-03": {"metric": "矛盾仲裁与回退有效性", "threshold": 1.0},
    "E-DEV-04": {"metric": "成长闭环归因完整率（三周期）", "threshold": 1.0},
}

STATEMENT_PREFERENCE = "用户偏好简短的回复"


def collect_slice(user_id: str) -> DevelopmentSlice | None:
    """EvaluationContext 只读切片：无任何行 → None。"""
    with SessionLocal() as session:
        states = (
            session.query(DevelopmentStateRow)
            .filter(DevelopmentStateRow.user_id == user_id)
            .order_by(DevelopmentStateRow.created_at.asc())
            .all()
        )
        if not states:
            return None
        state_ids = [row.id for row in states]
        changes = (
            session.query(DevelopmentChangeRow)
            .filter(DevelopmentChangeRow.development_state_id.in_(state_ids))
            .order_by(DevelopmentChangeRow.created_at.asc())
            .limit(50)
            .all()
        )
        insight_rows = (
            session.query(InsightRow.id, InsightRow.status)
            .filter(InsightRow.user_id == user_id)
            .all()
        )
    return DevelopmentSlice(
        active_states=[
            DevelopmentStateRef(
                id=row.id,
                key=row.key,
                kind=row.kind,
                status=row.status,
                strength=row.strength,
                value=dict(row.value or {}),
                source_insight_id=row.source_insight_id,
            )
            for row in states
            if row.status == "active"
        ],
        changes=[
            DevelopmentChangeRef(
                id=row.id,
                state_id=row.development_state_id,
                insight_id=row.insight_id,
                reason=row.reason,
                before=dict(row.before) if row.before else None,
                after=dict(row.after) if row.after else None,
            )
            for row in changes
        ],
        insight_statuses={row.id: row.status for row in insight_rows},
    )


def run_scenarios(session_factory, now=None) -> list[dict]:
    """注入式场景 runner：调用方负责 SessionLocal 环境与确定性数据（0 LLM）。"""
    now = now or datetime.now()
    return [
        _run_compile_idempotent(session_factory, now),
        _run_cap_saturation(session_factory, now),
        _run_contradiction_arbitration(session_factory, now),
        _run_rebuttal_rollback(session_factory, now),
    ]


def compute_metrics(scenario_results: list[dict]) -> dict:
    """场景结果 → E-DEV-01~03 指标报告（纯函数）。"""
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
    """只读 DB 统计（offline_evaluator development 小节引用）。"""
    with SessionLocal() as session:
        states = session.query(DevelopmentStateRow).all()
        changes = session.query(DevelopmentChangeRow).all()
        insight_ids = {row.id for row in session.query(InsightRow.id).all()}
    attributable = sum(1 for row in changes if row.insight_id in insight_ids)
    by_status: dict[str, int] = {}
    by_key: dict[str, int] = {}
    for row in states:
        if row.status == "active":
            by_status[row.status] = by_status.get(row.status, 0) + 1
            by_key[row.key] = by_key.get(row.key, 0) + 1
    concurrent = sum(1 for count in by_key.values() if count > 1)
    return {
        "states_total": len(states),
        "active_states": by_status.get("active", 0),
        "changes_total": len(changes),
        "attribution_rate": round(attributable / len(changes), 4) if changes else None,
        "concurrent_active_keys": concurrent,
    }


def _result(scenario_id: str, failures: list[str], stats: dict) -> dict:
    return {"scenario_id": scenario_id, "failures": failures, "stats": stats}


def _seed_insight(
    session_factory,
    user_id,
    insight_id,
    *,
    statement,
    insight_type,
    confidence,
    created_at,
    status="active",
):
    with session_factory() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                character_id="asuna",
                statement=statement,
                type=insight_type,
                confidence=confidence,
                scope="user",
                status=status,
                invalidated_reason="seed" if status == "invalidated" else None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()


def _compile_apply(user_id: str, insight_id: str) -> list[str]:
    """编译 + 仲裁落库；返回逐 key outcome（无提案为空表）。"""

    insight = reflection_lifecycle.get_insight(insight_id)
    outcomes = []
    for proposal in development_policy.compile_insight(insight):
        outcome = aggregate.upsert_modulation(
            user_id,
            proposal.kind,
            proposal.key,
            proposal.value,
            proposal.strength,
            proposal.insight_id,
            source_insight_created_at=proposal.insight_created_at,
            comparator=development_policy.arbitration_comparator,
        )
        outcomes.append(f"{proposal.key}:{outcome.outcome}")
    return outcomes


def _run_compile_idempotent(session_factory, now) -> dict:
    scenario_id = SCENARIO_COMPILE_IDEMPOTENT
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    _seed_insight(
        session_factory,
        user_id,
        "ins-idem",
        statement=STATEMENT_PREFERENCE,
        insight_type="preference",
        confidence=0.8,
        created_at=now,
    )

    insight = reflection_lifecycle.get_insight("ins-idem")
    compiled_first = development_policy.compile_insight(insight)
    first = _compile_apply(user_id, "ins-idem")
    before = _snapshot_states(session_factory, user_id)
    compiled_second = development_policy.compile_insight(insight)
    second = _compile_apply(user_id, "ins-idem")
    after = _snapshot_states(session_factory, user_id)
    if compiled_first != compiled_second:
        failures.append("同 Insight 重复编译输出不一致")
    if before != after:
        failures.append("重复编译写入了新 state 行（非 noop）")
    unattributed = _unattributed_changes(session_factory, user_id)
    if unattributed:
        failures.append(f"{unattributed} 条 changes 不可溯 insight_id")
    return _result(scenario_id, failures, {"proposals": len(first)})


def _run_cap_saturation(session_factory, now) -> dict:
    scenario_id = SCENARIO_CAP_SATURATION
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    settings = get_settings()
    cap = settings.development_preference_max_token_delta
    for index in range(10):
        _seed_insight(
            session_factory,
            user_id,
            f"ins-cap-{index}",
            statement=f"用户偏好简短的回复（第{index + 1}次确认）",
            insight_type="preference",
            confidence=0.95,
            created_at=now.replace(microsecond=index),
        )
        _compile_apply(user_id, f"ins-cap-{index}")
    actives = aggregate.list_active_modulations(user_id)
    length = [item for item in actives if item.key == "response_style.length"]
    if not length:
        failures.append("长度调制未生效")
    else:
        delta = abs(length[0].value.get("max_tokens_delta", 0))
        if delta > cap:
            failures.append(f"幅度 {delta} 超出封顶 {cap}")
    concurrent = _concurrent_active(session_factory, user_id)
    if concurrent:
        failures.append(f"{concurrent} 个 key 存在并存 active")
    return _result(scenario_id, failures, {"active_keys": len(actives), "cap": cap})


def _run_contradiction_arbitration(session_factory, now) -> dict:
    scenario_id = SCENARIO_CONTRADICTION_ARBITRATION
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []
    _seed_insight(
        session_factory,
        user_id,
        "ins-con-a",
        statement="用户喜欢详细的解释",
        insight_type="preference",
        confidence=0.6,
        created_at=now,
    )
    _seed_insight(
        session_factory,
        user_id,
        "ins-con-b",
        statement="用户讨厌冗长的解释",
        insight_type="preference",
        confidence=0.9,
        created_at=now,
    )
    _compile_apply(user_id, "ins-con-a")
    _compile_apply(user_id, "ins-con-b")
    actives = aggregate.list_active_modulations(user_id)
    length = [item for item in actives if item.key == "response_style.length"]
    if len(length) != 1:
        failures.append(f"矛盾 Insight 并存生效（{len(length)} 条 active）")
    elif length[0].source_insight_id != "ins-con-b":
        failures.append("仲裁未选高 confidence 者")
    losers = _states_by_status(session_factory, user_id, ("superseded",))
    if not losers:
        failures.append("败者未留痕")
    return _result(scenario_id, failures, {"active": len(actives)})


def _run_rebuttal_rollback(session_factory, now) -> dict:
    scenario_id = SCENARIO_REBUTTAL_ROLLBACK
    user_id = f"eval-{scenario_id}"
    failures: list[str] = []

    _seed_insight(
        session_factory,
        user_id,
        "ins-rebut",
        statement=STATEMENT_PREFERENCE,
        insight_type="preference",
        confidence=0.8,
        created_at=now,
    )
    _compile_apply(user_id, "ins-rebut")
    if not aggregate.list_active_modulations(user_id):
        failures.append("调制未生效")
    if not reflection_lifecycle.invalidate_insight("ins-rebut", "其实我喜欢长回复"):
        failures.append("反驳未失效 Insight")
    report = development_audit.rollback_for_insight(user_id, "ins-rebut")
    if not report["affected_keys"]:
        failures.append("回退未定位受影响 key")
    if aggregate.list_active_modulations(user_id):
        failures.append("回退后仍有 active 调制（无次优场景应为基线）")
    verify = development_audit.verify_replay(user_id)
    if not verify["consistent"]:
        failures.append(f"重放与在线不一致: {verify['diffs']}")
    return _result(
        scenario_id,
        failures,
        {"affected_keys": report["affected_keys"], "verify": verify["consistent"]},
    )


def _snapshot_states(session_factory, user_id) -> list[tuple]:
    with session_factory() as session:
        rows = (
            session.query(DevelopmentStateRow)
            .filter(DevelopmentStateRow.user_id == user_id)
            .all()
        )
        return sorted((row.key, row.status, str(row.value)) for row in rows)


def _unattributed_changes(session_factory, user_id) -> int:
    with session_factory() as session:
        state_ids = [
            row.id
            for row in session.query(DevelopmentStateRow.id)
            .filter(DevelopmentStateRow.user_id == user_id)
            .all()
        ]
        if not state_ids:
            return 0
        changes = (
            session.query(DevelopmentChangeRow)
            .filter(DevelopmentChangeRow.development_state_id.in_(state_ids))
            .all()
        )
        insight_ids = {
            row.id
            for row in session.query(InsightRow.id)
            .filter(InsightRow.user_id == user_id)
            .all()
        }
        return sum(1 for row in changes if row.insight_id not in insight_ids)


def _concurrent_active(session_factory, user_id) -> int:
    with session_factory() as session:
        rows = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.status == "active",
            )
            .all()
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.key] = counts.get(row.key, 0) + 1
    return sum(1 for count in counts.values() if count > 1)


def _states_by_status(session_factory, user_id, statuses) -> list:
    with session_factory() as session:
        rows = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.status.in_(list(statuses)),
            )
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


PRESSURE_CONTENTS = [
    "用户说最近经常加班到深夜",
    "用户说项目上线前都在加班",
    "用户说加班后感到很疲惫",
    "用户说周末也要去公司加班",
    "用户说已经连续加班一个月",
]

INSIGHT_STATEMENT_CYCLE1 = "用户最近经常加班，处于持续高压"
INSIGHT_STATEMENT_CYCLE2 = "用户最近经常加班，处于持续高压，需主动关心"
REBUTTAL_CONTENT = "并非如此，用户最近经常加班，处于持续高压"

NEW_EXPERIENCE_CONTENTS = [
    "亚丝娜深夜主动提醒用户休息，用户回应感觉被关心",
    "亚丝娜跟进询问加班项目进展，用户表示很暖心",
]


def run_growth_loop(session_factory, now=None, user_id=None) -> dict:
    """三周期「连续加班」成长闭环 runner（注入式；Flag 组合由调用方 settings 决定）。

    周期 1：压力证据 → 反思 → 调制生效；周期 2：调制后行为 → 新对话经 P1 摄取
    → 反思强化（confidence 提升）→ 调制演进；周期 3：用户反驳 → 失效 → 回退基线。
    每周期执行归因链审计（memory→evidence→insight→changes→state）。
    """
    now = now or datetime.now()
    user_id = user_id or f"eval-{SCENARIO_GROWTH_LOOP}"
    settings = get_settings()
    failures: list[str] = []
    stats: dict = {"insight_ids": [], "state_keys": [], "cycles": 0}

    _seed_cluster(session_factory, user_id, PRESSURE_CONTENTS, now)
    stats["cycles"] = 1

    insight1 = _grow_reflect_once(
        session_factory, user_id, now, INSIGHT_STATEMENT_CYCLE1
    )
    if insight1 is None:
        failures.append("周期 1 未产出 Insight")
        return _result(SCENARIO_GROWTH_LOOP, failures, stats)
    stats["insight_ids"].append(insight1)
    stats["cycles"] = 2

    if not _grow_compile(session_factory, user_id, insight1):
        failures.append("周期 1 调制未生效")
        return _result(SCENARIO_GROWTH_LOOP, failures, stats)
    overlay1 = aggregate.read_overlay(user_id)
    if overlay1 is None or "goal.user_care.weight" not in overlay1.sources:
        failures.append("周期 1 overlay 缺少 goal 调制")
    stats["state_keys"] = [
        item.key for item in aggregate.list_active_modulations(user_id)
    ]

    failures.extend(_audit_chain(session_factory, user_id, insight1))

    _grow_new_experience(session_factory, user_id, now)
    insight2 = _grow_reflect_once(
        session_factory, user_id, now, INSIGHT_STATEMENT_CYCLE2
    )
    if insight2 is None:
        failures.append("周期 2 未产出强化 Insight")
        return _result(SCENARIO_GROWTH_LOOP, failures, stats)
    stats["insight_ids"].append(insight2)
    stats["cycles"] = 3

    confidence1, confidence2 = _insight_confidences(
        session_factory, [insight1, insight2]
    )
    if not confidence2 > confidence1:
        failures.append(f"强化 Insight confidence 未提升: {confidence1} -> {confidence2}")
    superseded_by = _insight_superseded_by(session_factory, insight1)
    if superseded_by != insight2:
        failures.append(f"旧 Insight 未被替代: superseded_by={superseded_by}")

    _grow_compile(session_factory, user_id, insight2)
    actives = {item.key: item for item in aggregate.list_active_modulations(user_id)}
    weight = actives.get("goal.user_care.weight")
    if weight is None or weight.source_insight_id != insight2:
        failures.append("调制演进未指向周期 2 Insight")
    delta2 = float(weight.value.get("tier_delta", 0.0)) if weight else 0.0
    if delta2 <= 0:
        failures.append("周期 2 调制幅度未演化")
    failures.extend(_audit_chain(session_factory, user_id, insight2))


    invalidated = reflection_lifecycle.observe_negation(
        user_id, "mem-rebuttal", REBUTTAL_CONTENT
    )
    if invalidated != [insight2]:
        failures.append(f"反驳未失效周期 2 Insight: {invalidated}")
    development_audit.rollback_for_insight(user_id, insight2)
    if aggregate.list_active_modulations(user_id):
        failures.append("回退后仍有 active 调制（应为基线）")
    if aggregate.read_overlay(user_id) is not None:
        failures.append("回退后 overlay 应为空")
    stats["rolled_back"] = True
    return _result(SCENARIO_GROWTH_LOOP, failures, stats)


CLUSTER_VECTOR = [1.0 if i == 3 else 0.1 for i in range(8)]


def _seed_cluster(session_factory, user_id, contents, now):
    """确定性伪语义簇：全部成员共享同一向量（单簇聚类）+ 时间跨度满足证据门槛。"""
    import json as _json


    with session_factory() as session:
        for index, content in enumerate(contents):
            created = now - timedelta(days=(len(contents) - 1 - index) * 2)
            session.add(
                Memory(
                    id=f"{user_id}-mem-{index}",
                    user_id=user_id,
                    character_id="asuna",
                    content=content,
                    type="user_fact",
                    importance=0.7,
                    confidence=0.9,
                    source="user_stated",
                    status="active",
                    salience=0.8,
                    embedding=_json.dumps(CLUSTER_VECTOR),
                    source_ref={"table": "conversation", "id": f"conv:{user_id}:{index}"},
                    visibility="private",
                    created_at=created,
                    updated_at=now,
                )
            )
        session.commit()


def _fake_vector(text: str) -> list[float]:
    import math

    vector = [0.0] * 64
    for char in text or "":
        vector[ord(char) % 64] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _grow_reflect_once(session_factory, user_id, now, statement) -> str | None:
    run_id = f"run-{user_id}-{int(now.timestamp())}-{len(statement)}"
    with session_factory() as session:
        session.add(
            ReflectionRunRow(
                id=run_id,
                user_id=user_id,
                character_id="asuna",
                trigger="scheduled",
                status="queued",
                llm_used=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    reflection_reflector.run_queued_reflections()
    with session_factory() as session:
        rows = (
            session.query(InsightRow)
            .filter(InsightRow.user_id == user_id, InsightRow.statement == statement)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows[0].id if rows else None


def _grow_compile(session_factory, user_id, insight_id) -> bool:
    development_policy.compile_insight_by_id(insight_id)
    actives = aggregate.list_active_modulations(user_id)
    return any(item.source_insight_id == insight_id for item in actives)


def _grow_new_experience(session_factory, user_id, now):
    """周期 2：调制后行为 → 新对话 → P1 摄取 → 评估转正 → 补确定性伪向量。"""
    import asyncio
    import json as _json


    extraction = MemoryExtraction(
        candidates=[
            MemoryCandidate(
                action="save",
                type="user_fact",
                content=content,
                importance=0.8,
                confidence=0.9,
                source="user_stated",
            )
            for content in NEW_EXPERIENCE_CONTENTS
        ]
    )
    memory_ingest.ingest_from_conversation(
        user_id,
        extraction,
        source_id_base=f"conv:{user_id}:cycle2",
        created_at=now,
    )
    asyncio.run(memory_evaluator.evaluate_pending(user_id))
    promoted = _active_memory_contents(session_factory, user_id)
    missing = [content for content in NEW_EXPERIENCE_CONTENTS if content not in promoted]
    if missing:
        return
    with session_factory() as session:
        rows = session.query(Memory).filter(Memory.user_id == user_id).all()
        for row in rows:
            if row.embedding is None:
                row.embedding = _json.dumps(CLUSTER_VECTOR)
        session.commit()


def _active_memory_contents(session_factory, user_id) -> list[str]:
    with session_factory() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.user_id == user_id, Memory.status == "active")
            .all()
        )
        return [row.content for row in rows]


def _audit_chain(session_factory, user_id, insight_id) -> list[str]:
    """归因链审计：memory→evidence_links→insight→development_changes→state。"""

    failures: list[str] = []
    with session_factory() as session:
        links = (
            session.query(EvidenceLinkRow)
            .filter(EvidenceLinkRow.insight_id == insight_id)
            .all()
        )
        if not links:
            return [f"insight={insight_id} 无 evidence_links"]
        memory_ids = {link.memory_id for link in links}
        existing = {
            row.id
            for row in session.query(Memory.id)
            .filter(Memory.user_id == user_id)
            .all()
        }
        dangling = memory_ids - existing
        if dangling:
            failures.append(f"evidence 引用悬空: {sorted(dangling)}")
        changes = (
            session.query(DevelopmentChangeRow)
            .filter(DevelopmentChangeRow.insight_id == insight_id)
            .all()
        )
        if not changes:
            failures.append(f"insight={insight_id} 无 development_changes 归因行")
        states = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.source_insight_id == insight_id,
            )
            .all()
        )
        if not states:
            failures.append(f"insight={insight_id} 无 development_state 行")
    return failures


def _insight_confidences(session_factory, insight_ids) -> tuple:
    with session_factory() as session:
        rows = session.query(InsightRow).filter(InsightRow.id.in_(list(insight_ids))).all()
        by_id = {row.id: row.confidence for row in rows}
    return tuple(by_id[item] for item in insight_ids)


def _insight_superseded_by(session_factory, insight_id) -> str | None:
    with session_factory() as session:
        row = session.get(InsightRow, insight_id)
        return row.superseded_by if row is not None else None
