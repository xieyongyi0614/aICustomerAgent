from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.models.evaluation import EvaluationSubjectKind
from app.repositories import (
    conversation_repository,
    decision_repository,
    evaluation_repository,
    llm_call_repository,
    prompt_snapshot_repository,
    proactive_repository,
    trace_repository,
)
from app.services.observability.metrics_aggregator import (
    build_metric_report,
    summarize_llm_records,
)
from app.services.memory2 import attribution as memory2_attribution
from app.services.reflection import attribution as reflection_attribution
from app.services.trace_collector import get_trace_collector

debug_router = APIRouter()


@debug_router.get("/debug/memory/{memory_id}/attribution")
def get_memory_attribution(memory_id: str):
    view = memory2_attribution.memory_attribution(memory_id)
    if view is None:
        raise HTTPException(status_code=404, detail="memory 不存在")
    return view


@debug_router.get("/debug/candidate/{candidate_id}/attribution")
def get_candidate_attribution(candidate_id: str):
    view = memory2_attribution.candidate_attribution(candidate_id)
    if view is None:
        raise HTTPException(status_code=404, detail="candidate 不存在")
    return view


@debug_router.get("/debug/insights/{insight_id}/attribution")
def get_insight_attribution(insight_id: str):
    view = reflection_attribution.insight_attribution(insight_id)
    if view is None:
        raise HTTPException(status_code=404, detail="insight 不存在")
    return view


@debug_router.get("/debug/development/states/{state_id}")
def get_development_state_attribution(state_id: str):
    from app.services.development import attribution as development_attribution

    view = development_attribution.development_state_attribution(state_id)
    if view is None:
        raise HTTPException(status_code=404, detail="development state 不存在")
    return view


@debug_router.get("/debug/development/users/{user_id}")
def list_user_development(user_id: str, limit: int = 50):
    from app.services.development import attribution as development_attribution

    return development_attribution.list_user_development(user_id, limit=limit)


@debug_router.get("/debug/reflection-runs")
def list_reflection_runs(user_id: str | None = None, limit: int = 50):
    return reflection_attribution.list_reflection_runs(user_id, limit=limit)


@debug_router.get("/debug/turns/{turn_id}/trace")
def get_turn_trace(turn_id: str):
    session = get_trace_collector().get(turn_id)
    if session is not None:
        return session.snapshot()
    persisted = trace_repository.get_by_turn(turn_id)
    if persisted is not None:
        return persisted.api_dict()
    raise HTTPException(status_code=404, detail="turn trace 不存在或已被清理")


@debug_router.get("/debug/traces/{trace_id}")
def get_trace_by_request_id(trace_id: str):
    persisted = trace_repository.get_by_trace_id(trace_id)
    if persisted is None:
        raise HTTPException(status_code=404, detail="runtime trace 不存在或已过期")
    return persisted.api_dict()


@debug_router.get("/debug/traces")
def list_traces(conversation_id: str, limit: int = 20):
    traces = trace_repository.list_by_conversation(conversation_id, limit=max(1, min(limit, 100)))
    return [trace.api_dict() for trace in traces]


@debug_router.get("/debug/llm-calls")
def list_llm_calls(
    request_id: str | None = None,
    turn_id: str | None = None,
    window_hours: float | None = None,
    call_site: str | None = None,
    model: str | None = None,
    limit: int = 100,
):
    since = (
        datetime.now() - timedelta(hours=window_hours) if window_hours is not None else None
    )
    records = llm_call_repository.search(
        request_id=request_id,
        turn_id=turn_id,
        since=since,
        call_site=call_site,
        model=model,
        limit=limit,
    )
    return [record.model_dump(mode="json") for record in records]


@debug_router.get("/debug/llm-calls/summary")
def summary_llm_calls(window_hours: float = 24):
    since = datetime.now() - timedelta(hours=window_hours)
    records = llm_call_repository.list_since(since)
    return summarize_llm_records(records, window_hours).model_dump(mode="json")


@debug_router.get("/debug/turns/{turn_id}/prompts")
def list_turn_prompts(turn_id: str):
    snapshots = prompt_snapshot_repository.get_by_turn(turn_id)
    if not snapshots:
        raise HTTPException(status_code=404, detail="prompt 快照不存在或已过期")
    return [snapshot.model_dump(mode="json") for snapshot in snapshots]


@debug_router.get("/debug/prompts/compare")
def compare_prompt_snapshots(a: str, b: str):
    from app.services.observability.prompt_capture import diff_prompt_snapshots

    snapshot_a = prompt_snapshot_repository.get_by_id(a)
    snapshot_b = prompt_snapshot_repository.get_by_id(b)
    if snapshot_a is None or snapshot_b is None:
        raise HTTPException(status_code=404, detail="prompt 快照不存在或已过期")
    return diff_prompt_snapshots(snapshot_a, snapshot_b)


@debug_router.get("/debug/prompts/{snapshot_id}")
def get_prompt_snapshot(snapshot_id: str):
    snapshot = prompt_snapshot_repository.get_by_id(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="prompt 快照不存在或已过期")
    return snapshot.model_dump(mode="json")


@debug_router.get("/debug/metrics")
def get_metrics(window_hours: float = 24, user_id: str | None = None):
    since = datetime.now() - timedelta(hours=max(window_hours, 0.001))
    traces = [
        trace
        for trace in trace_repository.list_since(since)
        if user_id is None or trace.user_id == user_id
    ]
    reports = [
        report
        for report in evaluation_repository.list_since(since)
        if user_id is None or report.user_id == user_id
    ]
    llm_records = llm_call_repository.list_since(since)
    message_pairs = conversation_repository.list_messages_since(since)
    proactive_actions = proactive_repository.list_since(since)
    report = build_metric_report(
        window_hours,
        traces,
        llm_records,
        reports,
        message_pairs,
        proactive_actions,
    )
    return report.model_dump(mode="json")


@debug_router.get("/debug/decisions")
def list_decisions(
    user_id: str | None = None,
    kind: str | None = None,
    action_id: str | None = None,
    window_hours: float | None = None,
    limit: int = 50,
):
    since = (
        datetime.now() - timedelta(hours=window_hours) if window_hours is not None else None
    )
    records = decision_repository.search(
        user_id=user_id,
        kind=kind,
        action_id=action_id,
        since=since,
        limit=limit,
    )
    return [record.model_dump(mode="json") for record in records]


def _turn_trace_payload(turn_id: str):
    persisted = trace_repository.get_by_turn(turn_id)
    if persisted is not None:
        return persisted.api_dict()
    session = get_trace_collector().get(turn_id)
    return session.snapshot() if session is not None else None


def _turn_correlation_payload(turn_id: str) -> tuple[dict, bool]:
    trace_payload = _turn_trace_payload(turn_id)
    evaluation = evaluation_repository.get_by_subject(
        EvaluationSubjectKind.TURN.value, turn_id
    )
    prompts = prompt_snapshot_repository.get_by_turn(turn_id)
    llm_calls = llm_call_repository.get_by_turn(turn_id)
    request_id = trace_payload.get("request_id") if trace_payload else None
    decisions = (
        decision_repository.search(request_id=request_id) if request_id else []
    )
    found = (
        trace_payload is not None
        or evaluation is not None
        or bool(prompts)
        or bool(llm_calls)
        or bool(decisions)
    )
    payload = {
        "turn_id": turn_id,
        "request_id": request_id,
        "trace": trace_payload,
        "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
        "prompts": [snapshot.model_dump(mode="json") for snapshot in prompts],
        "llm_calls": [record.model_dump(mode="json") for record in llm_calls],
        "decisions": [record.model_dump(mode="json") for record in decisions],
    }
    return payload, found


def _proactive_correlation_payload(action_id: str) -> tuple[dict, bool]:
    action = proactive_repository.get_by_id(action_id)
    message_id = action.message_id if action is not None else None
    trace_payload = _turn_trace_payload(message_id) if message_id is not None else None
    evaluation = evaluation_repository.get_by_subject(
        EvaluationSubjectKind.PROACTIVE_ACTION.value, action_id
    )
    llm_calls = (
        llm_call_repository.get_by_turn(message_id) if message_id is not None else []
    )
    decisions = decision_repository.search(action_id=action_id)
    found = (
        trace_payload is not None
        or evaluation is not None
        or bool(llm_calls)
        or bool(decisions)
    )
    payload = {
        "action_id": action_id,
        "turn_id": message_id,
        "trace": trace_payload,
        "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
        "prompts": [],
        "llm_calls": [record.model_dump(mode="json") for record in llm_calls],
        "decisions": [record.model_dump(mode="json") for record in decisions],
    }
    return payload, found


@debug_router.get("/debug/evaluations")
def search_evaluations(
    verdict: str | None = None,
    dimension: str | None = None,
    issue_code: str | None = None,
    window_hours: float = 168,
    limit: int = 20,
    include: str | None = None,
):
    since = datetime.now() - timedelta(hours=max(window_hours, 0.001))
    reports = evaluation_repository.list_since(since, verdict=verdict)

    def _match(report) -> bool:
        if dimension is not None and dimension not in report.scores:
            return False
        if issue_code is not None and not any(
            issue.code.value == issue_code for issue in report.issues
        ):
            return False
        return True

    matched = [report for report in reports if _match(report)][
        : max(1, min(limit, 100))
    ]
    rows = []
    for report in matched:
        item = {
            "subject": report.subject.value,
            "subject_id": report.subject_id,
            "session_id": report.session_id,
            "user_id": report.user_id,
            "overall_score": report.overall_score,
            "verdict": report.verdict,
            "scores": {
                (dimension.value if hasattr(dimension, "value") else str(dimension)): score.model_dump()
                for dimension, score in report.scores.items()
            },
            "issue_codes": [issue.code.value for issue in report.issues],
            "meta": report.meta.model_dump(mode="json"),
            "created_at": report.created_at.isoformat(),
        }
        if include == "correlation":
            if report.subject == EvaluationSubjectKind.TURN:
                payload, _ = _turn_correlation_payload(report.subject_id)
            else:
                payload, _ = _proactive_correlation_payload(report.subject_id)
            item["correlation"] = payload
        rows.append(item)
    return rows


@debug_router.get("/debug/turns/{turn_id}/correlation")
def get_turn_correlation(turn_id: str):
    payload, found = _turn_correlation_payload(turn_id)
    if not found:
        raise HTTPException(status_code=404, detail="correlation 不存在或已过期")
    return payload


@debug_router.get("/debug/proactive/{action_id}/correlation")
def get_proactive_correlation(action_id: str):
    payload, found = _proactive_correlation_payload(action_id)
    if not found:
        raise HTTPException(status_code=404, detail="correlation 不存在或已过期")
    return payload


@debug_router.get("/debug/turns/{turn_id}/evaluation")
def get_turn_evaluation(turn_id: str):
    report = evaluation_repository.get_by_subject(
        EvaluationSubjectKind.TURN.value, turn_id
    )
    if report is None:
        raise HTTPException(status_code=404, detail="评估报告不存在或已过期")
    return report.model_dump(mode="json")


@debug_router.get("/debug/proactive/{action_id}/evaluation")
def get_proactive_evaluation(action_id: str):
    report = evaluation_repository.get_by_subject(
        EvaluationSubjectKind.PROACTIVE_ACTION.value, action_id
    )
    if report is None:
        raise HTTPException(status_code=404, detail="评估报告不存在或已过期")
    return report.model_dump(mode="json")


@debug_router.get("/debug/relationship/state")
def get_relationship_state(user_id: str):
    from datetime import datetime
    from app.repositories import (
        relationship_milestone_repository,
        relationship_repository,
    )
    from app.services.relationship_evolution import distance_index

    state = relationship_repository.get_relationship(user_id)
    unlocks = relationship_milestone_repository.list_unlocks(user_id)
    now = datetime.now()
    distance = distance_index(state, now)
    return {
        "user_id": user_id,
        "state": state.model_dump(mode="json"),
        "unlocks": list(unlocks),
        "derived": {
            "distance_index": round(distance, 4),
        },
    }


@debug_router.get("/debug/relationship/timeline")
def get_relationship_timeline(user_id: str, limit: int = 50):
    from app.repositories import (
        memory_repository,
        relationship_conflict_repository,
        relationship_event_repository,
        relationship_milestone_repository,
        relationship_snapshot_repository,
    )

    limit_clamped = max(1, min(limit, 200))
    events = relationship_event_repository.list_events(user_id, limit=limit_clamped)
    milestones = relationship_milestone_repository.list_milestones(user_id)[:limit_clamped]
    conflicts = relationship_conflict_repository.list_conflicts(user_id, limit=limit_clamped)
    snapshots = relationship_snapshot_repository.list_snapshots(user_id, limit=limit_clamped)

    narrative_rows = memory_repository.list_active_by_types(
        user_id,
        "asuna",
        ["relationship_fact", "milestone_event"],
        limit=500,
    )
    source_refs = memory_repository.get_source_refs([m.id for m in narrative_rows])
    narrative_by_source: dict[tuple[str, str], list[str]] = {}
    for row in narrative_rows:
        ref = source_refs.get(row.id) or {}
        table = ref.get("table")
        target_id = ref.get("id")
        if table and target_id:
            narrative_by_source.setdefault((table, target_id), []).append(row.id)

    merged: list[dict] = []
    for e in events:
        merged.append(
            {
                "kind": "event",
                "at": e.created_at.isoformat(),
                "type": e.type,
                "magnitude": e.magnitude,
                "source": e.source,
                "cause": e.cause,
                "impact": e.impact.model_dump(mode="json"),
                "id": e.id,
                "narrative_memory_ids": narrative_by_source.get(
                    ("relationship_events", e.id), []
                ),
            }
        )
    for m in milestones:
        merged.append(
            {
                "kind": "milestone",
                "at": m.created_at.isoformat(),
                "key": m.milestone_key,
                "period_key": m.period_key,
                "title": m.title,
                "unlocks": list(m.unlocks),
                "bonus": m.applied_bonus.model_dump(mode="json"),
                "id": m.id,
                "narrative_memory_ids": narrative_by_source.get(
                    ("relationship_milestones", m.id), []
                ),
            }
        )
    for c in conflicts:
        merged.append(
            {
                "kind": "conflict",
                "at": c.started_at.isoformat(),
                "status": c.status,
                "resolution": c.resolution,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                "id": c.id,
            }
        )
    for s in snapshots:
        merged.append(
            {
                "kind": "snapshot",
                "at": s.created_at.isoformat(),
                "version": s.version,
                "stage": s.stage,
                "conflict_status": s.conflict_status,
                "trigger": s.trigger,
                "dimensions": s.dimensions,
                "id": s.id,
            }
        )
    merged.sort(key=lambda r: r["at"], reverse=True)
    return {"user_id": user_id, "items": merged[:limit_clamped]}


@debug_router.post("/debug/relationship/rollback")
def rollback_relationship(user_id: str, target_version: int):
    from datetime import datetime

    from app.repositories import (
        relationship_event_repository,
        relationship_repository,
        relationship_snapshot_repository,
    )
    from app.services import relationship_evolution

    earliest = relationship_snapshot_repository.get_earliest_version(user_id)
    if earliest is None:
        raise HTTPException(status_code=404, detail="无可用关键帧，无法回滚")
    if target_version < earliest:
        raise HTTPException(
            status_code=400,
            detail=f"target_version 早于最早关键帧 {earliest}",
        )
    current = relationship_repository.get_relationship(user_id)
    now = datetime.now()
    try:
        relationship_snapshot_repository.create_snapshot(
            user_id,
            current.version,
            current,
            trigger="manual_pre_rollback",
            now=now,
        )
    except Exception:
        pass
    anchor = relationship_snapshot_repository.get_latest_before(user_id, target_version)
    if anchor is None:
        raise HTTPException(status_code=404, detail="无法定位 ≤ target_version 的关键帧")
    from app.models.relationship import RelationshipState

    base_state = RelationshipState(
        intimacy=anchor.dimensions.get("intimacy", current.intimacy),
        trust=anchor.dimensions.get("trust", current.trust),
        familiarity=anchor.dimensions.get("familiarity", current.familiarity),
        respect=anchor.dimensions.get("respect", current.respect),
        comfort=anchor.dimensions.get("comfort", current.comfort),
        tension=anchor.dimensions.get("tension", current.tension),
        stage=anchor.stage,
        conflict_status=anchor.conflict_status,
        neglect_active=current.neglect_active,
        last_interaction_at=current.last_interaction_at,
        version=anchor.version,
        updated_at=now,
    )
    all_events = relationship_event_repository.list_events(user_id, limit=2000)
    anchor_time = anchor.created_at
    replayable = [e for e in all_events if e.created_at > anchor_time]
    rebuilt = relationship_evolution.replay(base_state, replayable)
    final = rebuilt.model_copy(
        update={"version": max(current.version, rebuilt.version) + 1, "updated_at": now}
    )
    persisted = relationship_repository.upsert_relationship(user_id, final)
    relationship_snapshot_repository.create_snapshot(
        user_id,
        final.version,
        final,
        trigger="manual",
        now=now,
    )
    return {
        "user_id": user_id,
        "target_version": target_version,
        "anchor_version": anchor.version,
        "replayed_events": len(replayable),
        "final_state": persisted.model_dump(mode="json"),
    }
