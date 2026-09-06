"""Development 回退与重放（DEV-004）。

订阅 REF-005 失效事件（编排层注册）：Insight 失效 → 定位受影响 key → 重放该
key 的调制历史（活跃 Insight 时间序重编译 + 同一仲裁比较器）→ 有次优胜者则
提升（changes reason=rolled_back）、无则 retire——回退与在线共用同一套编译+
仲裁代码，这是「重放=在线」的结构保障。

verify_replay 为只读校验：内存重放各 key 的仲裁胜者并与在线 active 集比对
（原始审计行零改动）；rebuild 模式才实际清空重写（仅运维显式触发）。
"""

import logging
import time

from app.core.db import BackgroundJobRow, DevelopmentChangeRow, DevelopmentStateRow, SessionLocal
from app.models.development import ModulationProposal
from app.repositories import background_job_repository
from app.services.development import aggregate
from app.services.development import policy as development_policy
from app.services.reflection import lifecycle as reflection_lifecycle

logger = logging.getLogger(__name__)

STEP_NAME = "development_rollback"

JOB_TYPE_ROLLBACK = "development_rollback"

STATUS_INVALIDATED = "invalidated"
STATUS_ACTIVE = "active"


def on_invalidation(user_id: str, changed: list[dict]) -> None:
    """失效事件回调：逐变更 enqueue 回退 job（幂等键拦截重复事件）。"""
    for item in changed or []:
        insight_id = item.get("insight_id")
        status = item.get("status") or STATUS_INVALIDATED
        if not insight_id:
            continue
        background_job_repository.enqueue_job(
            JOB_TYPE_ROLLBACK,
            {"insight_id": insight_id, "user_id": user_id, "status": status},
            f"{JOB_TYPE_ROLLBACK}:{insight_id}:{status}",
        )


def run_rollback_jobs() -> int:
    """job handler（无参签名对齐 _JOB_HANDLERS）：处理本类型 running 载荷。

    重复处理幂等（回退收敛后 no-op）；重放异常由 MEM-009 退避重试，达上限死信
    failed+last_error——当前态保留不静默清空。
    """
    processed = 0
    with SessionLocal() as session:
        rows = (
            session.query(BackgroundJobRow)
            .filter(
                BackgroundJobRow.job_type == JOB_TYPE_ROLLBACK,
                BackgroundJobRow.status == "running",
            )
            .all()
        )
        payloads = [
            (
                (row.payload or {}).get("user_id"),
                (row.payload or {}).get("insight_id"),
                (row.payload or {}).get("status") or STATUS_INVALIDATED,
            )
            for row in rows
        ]
    for user_id, insight_id, status in payloads:
        if not insight_id or not user_id:
            continue
        rollback_for_insight(user_id, insight_id, status)
        processed += 1
    return processed


def rollback_for_insight(
    user_id: str, insight_id: str, status: str = STATUS_INVALIDATED, trace=None
) -> dict:
    """Insight 失效后的按 key 回退：重放该 key 调制历史 → 次优提升或 retire。"""
    started = time.perf_counter()
    affected = aggregate.list_states_by_source_insight(user_id, insight_id)
    if not affected:
        _trace(trace, started, insight_id=insight_id, reason="no_affected_keys")
        return {"affected_keys": [], "actions": []}
    actives = reflection_lifecycle.list_user_active_insights(user_id)
    actions: list[dict] = []
    for state in affected:
        key = state.key
        winner = _replay_key_winner(actives, key)
        aggregate.retire_modulation(
            user_id,
            key,
            insight_id,
            reason=aggregate.REASON_ROLLED_BACK,
            trace=trace,
        )
        if winner is None:
            actions.append({"key": key, "action": "retired"})
            continue
        outcome = aggregate.upsert_modulation(
            user_id,
            winner.kind,
            key,
            winner.value,
            winner.strength,
            winner.insight_id,
            source_insight_created_at=winner.insight_created_at,
            comparator=development_policy.arbitration_comparator,
            change_reason=aggregate.REASON_ROLLED_BACK,
            ignore_seen=True,
            trace=trace,
        )
        actions.append({"key": key, "action": "promoted", "outcome": outcome.outcome})
    _trace(
        trace,
        started,
        insight_id=insight_id,
        status=status,
        affected_keys=[item.key for item in affected],
        actions=actions,
    )
    return {"affected_keys": [item.key for item in affected], "actions": actions}


def verify_replay(user_id: str, rebuild: bool = False, trace=None) -> dict:
    """重放校验（默认只读）：内存重编译各 key 仲裁胜者 vs 在线 active 集。

    原始审计行零改动（rebuild=False 不写任何行）；rebuild=True 实际清空重写，
    仅限审计损坏修复且停写窗口执行。报告 diffs 为空即「重放=在线」。
    """
    started = time.perf_counter()
    deleted = rebuild_state(user_id) if rebuild else None
    replay = _replay_active_winners(user_id)
    with SessionLocal() as session:
        online_rows = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.status == STATUS_ACTIVE,
            )
            .all()
        )
        online = {row.key: row for row in online_rows}
        state_ids = [row.id for row in online_rows] + [
            row.id
            for row in session.query(DevelopmentStateRow.id)
            .filter(DevelopmentStateRow.user_id == user_id)
            .all()
        ]
        unique_state_ids = list(dict.fromkeys(state_ids))
        changes = (
            session.query(DevelopmentChangeRow)
            .filter(DevelopmentChangeRow.development_state_id.in_(unique_state_ids))
            .all()
            if unique_state_ids
            else []
        )
        changes_total = len(changes)
        change_insight_ids = {row.insight_id for row in changes}
        from app.core.db import InsightRow

        resolvable = {
            insight_id
            for insight_id in change_insight_ids
            if session.get(InsightRow, insight_id) is not None
        }
        unattributed = len(change_insight_ids - resolvable)
    diffs: list[dict] = []
    for key in sorted(set(replay) | set(online)):
        replayed = replay.get(key)
        row = online.get(key)
        replayed_id = replayed.insight_id if replayed is not None else None
        online_id = row.source_insight_id if row is not None else None
        replayed_value = replayed.value if replayed is not None else None
        online_value = row.value if row is not None else None
        if replayed_id != online_id or replayed_value != online_value:
            diffs.append(
                {
                    "key": key,
                    "online": online_id,
                    "replay": replayed_id,
                }
            )
    report = {
        "user_id": user_id,
        "consistent": not diffs,
        "keys_checked": len(set(replay) | set(online)),
        "diffs": diffs,
        "changes_total": changes_total,
        "changes_unattributed": unattributed,
    }
    if deleted is not None:
        report["rebuild"] = deleted
    _trace(
        trace,
        started,
        user_id=user_id,
        consistent=report["consistent"],
        rebuild=rebuild,
    )
    return report


def rebuild_state(user_id: str) -> int:
    """清空该用户 development 两表后按 Insight 时间序重编译重建（运维入口）。"""
    with SessionLocal() as session:
        state_ids = [
            row.id
            for row in session.query(DevelopmentStateRow.id)
            .filter(DevelopmentStateRow.user_id == user_id)
            .all()
        ]
        if state_ids:
            session.query(DevelopmentChangeRow).filter(
                DevelopmentChangeRow.development_state_id.in_(state_ids)
            ).delete(synchronize_session=False)
        deleted = (
            session.query(DevelopmentStateRow)
            .filter(DevelopmentStateRow.user_id == user_id)
            .delete(synchronize_session=False)
        )
        session.commit()
    actives = sorted(
        reflection_lifecycle.list_user_active_insights(user_id),
        key=lambda insight: (insight.created_at, insight.id),
    )
    for insight in actives:
        for proposal in development_policy.compile_insight(insight):
            aggregate.upsert_modulation(
                user_id,
                proposal.kind,
                proposal.key,
                proposal.value,
                proposal.strength,
                proposal.insight_id,
                source_insight_created_at=proposal.insight_created_at,
                comparator=development_policy.arbitration_comparator,
                change_reason=aggregate.REASON_REPLAYED,
            )
    return deleted


def register_rollback_listener() -> None:
    """Flag ON 编排层注册：失效事件订阅 + 回退 job handler。"""
    from app.services.memory2 import job_worker as memory2_job_worker
    from app.services.reflection import lifecycle as reflection_lifecycle

    memory2_job_worker.register_job_type(JOB_TYPE_ROLLBACK, run_rollback_jobs)
    reflection_lifecycle.register_invalidation_listener(on_invalidation)


def _replay_key_winner(
    actives: list, key: str
) -> ModulationProposal | None:
    winner: ModulationProposal | None = None
    for insight in actives:
        for proposal in development_policy.compile_insight(insight):
            if proposal.key != key:
                continue
            if winner is None or _proposal_beats(proposal, winner):
                winner = proposal
    return winner


def _replay_active_winners(user_id: str) -> dict[str, ModulationProposal]:
    actives = sorted(
        reflection_lifecycle.list_user_active_insights(user_id),
        key=lambda insight: (insight.created_at, insight.id),
    )
    winners: dict[str, ModulationProposal] = {}
    for insight in actives:
        for proposal in development_policy.compile_insight(insight):
            current = winners.get(proposal.key)
            if current is None or _proposal_beats(proposal, current):
                winners[proposal.key] = proposal
    return winners


def _proposal_beats(a: ModulationProposal, b: ModulationProposal) -> bool:
    if a.strength != b.strength:
        return a.strength > b.strength
    if a.insight_created_at is None or b.insight_created_at is None:
        return False
    return a.insight_created_at > b.insight_created_at



def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)
