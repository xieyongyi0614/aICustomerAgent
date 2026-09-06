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
from datetime import datetime

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

logger = logging.getLogger(__name__)

SCENARIO_COMPILE_IDEMPOTENT = "compile_idempotent"
SCENARIO_CAP_SATURATION = "cap_saturation"
SCENARIO_CONTRADICTION_ARBITRATION = "contradiction_arbitration"
SCENARIO_REBUTTAL_ROLLBACK = "rebuttal_rollback"

KIND_TO_METRIC = {
    SCENARIO_COMPILE_IDEMPOTENT: ("E-DEV-01",),
    SCENARIO_CAP_SATURATION: ("E-DEV-02",),
    SCENARIO_CONTRADICTION_ARBITRATION: ("E-DEV-03",),
    SCENARIO_REBUTTAL_ROLLBACK: ("E-DEV-03",),
}

GATE_THRESHOLDS = {
    "E-DEV-01": {"metric": "编译一致性与归因完整率", "threshold": 1.0},
    "E-DEV-02": {"metric": "调制可见性与封顶", "threshold": 1.0},
    "E-DEV-03": {"metric": "矛盾仲裁与回退有效性", "threshold": 1.0},
}

STATEMENT_PREFERENCE = "用户偏好简短的回复"


def collect_slice(user_id: str) -> DevelopmentSlice | None:
    """EvaluationContext 只读切片：Flag OFF 或无任何行 → None。"""
    if not get_settings().v2_development_enabled:
        return None
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
    """只读 DB 统计（offline_evaluator development 小节引用；Flag OFF 为空）。"""
    if not get_settings().v2_development_enabled:
        return {}
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
    from app.services.reflection import lifecycle as reflection_lifecycle

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
    from app.services.reflection import lifecycle as reflection_lifecycle

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
    cap = settings.v2_development_preference_max_token_delta
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
    from app.services.reflection import lifecycle as reflection_lifecycle

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
