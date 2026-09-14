import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import (
    ToolConfirmationRevokeOut,
    ToolConfirmationsOut,
    ToolConfirmationOut,
    ToolDetailOut,
    ToolExecutionRowOut,
    ToolExecutionsOut,
    ToolGrantOut,
    ToolHealthOut,
    ToolPermissionRevokeOut,
    ToolPermissionsOut,
    ToolRuntimeStatusOut,
    ToolSummaryOut,
    ToolSurfaceOut,
    ToolsOut,
)
from app.character.asuna.tool import RUN_KIND_FOREGROUND_CHAT
from app.core.settings import get_settings
from app.models.evaluation import EvaluationSubjectKind
from app.models.relationship import RelationshipState
from app.repositories import (
    action_repository,
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
from app.services.tool.confirmation import get_confirmation_service
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, get_tool_registry
from app.services.tool.surface import ToolSurfaceResolver
from app.services.trace_collector import get_trace_collector
from app.repositories import (
    relationship_milestone_repository,
    relationship_repository,
    memory_repository,
    relationship_conflict_repository,
    relationship_event_repository,
    relationship_snapshot_repository,
)
from app.services import relationship_evolution
from app.services.development import attribution as development_attribution
from app.services.observability.prompt_capture import diff_prompt_snapshots
from app.services.relationship_evolution import distance_index

logger = logging.getLogger(__name__)

debug_router = APIRouter()

TOOL_SURFACE_DEFAULT_RUN_KIND = RUN_KIND_FOREGROUND_CHAT

TOOL_EXECUTIONS_MIN_LIMIT = 1
TOOL_EXECUTIONS_MAX_LIMIT = 200


def _tools_enabled() -> bool:
    return bool(get_settings().v24_tool_system_enabled)


def _require_tool_registry() -> ToolRegistry:
    """写类端点门控：总闸 off → 403；注册表不可用按未启用处理。"""
    if not _tools_enabled():
        raise HTTPException(
            status_code=403, detail="工具系统未启用（v24_tool_system_enabled=false）"
        )
    registry = get_tool_registry()
    if registry is None:
        raise HTTPException(
            status_code=403, detail="工具系统未启用（v24_tool_system_enabled=false）"
        )
    return registry


def _permission_layer_enabled() -> bool:
    return bool(getattr(get_settings(), "v24_tool_permission_enabled", False))


def _require_permission_layer() -> None:
    """权限闸写类端点门控：总闸 off → 403；权限闸 off → 403，与 WS-018 惯例一致。"""
    _require_tool_registry()
    if not _permission_layer_enabled():
        raise HTTPException(
            status_code=403, detail="工具权限闸未启用（v24_tool_permission_enabled=false）"
        )


def _permission_read_gate() -> bool:
    """权限闸读类端点门控：总闸 off → 200 `{"enabled": false}`；权限闸 off → 403。"""
    if not _tools_enabled():
        return False
    if not _permission_layer_enabled():
        raise HTTPException(
            status_code=403, detail="工具权限闸未启用（v24_tool_permission_enabled=false）"
        )
    return True


def _tool_health_out(registry: ToolRegistry, tool_id: str) -> ToolHealthOut | None:
    health = registry.health(tool_id).get(tool_id)
    if health is None:
        return None
    return ToolHealthOut(**health.model_dump())


def _project_executions(
    user_id: str, limit: int, tool_id: str | None = None
) -> list[ToolExecutionRowOut]:
    """执行台账投影：从 `action_records.steps`（V9 既有列）取工具执行步骤。"""
    rows: list[ToolExecutionRowOut] = []
    records = action_repository.list_records(
        user_id, limit=max(TOOL_EXECUTIONS_MIN_LIMIT, min(limit, TOOL_EXECUTIONS_MAX_LIMIT))
    )
    for record in records:
        for step in record.steps or []:
            step_tool_id = step.get("tool_id")
            if not step_tool_id:
                continue
            if tool_id is not None and step_tool_id != tool_id:
                continue
            result = step.get("result") or {}
            effects = result.get("effects")
            rows.append(
                ToolExecutionRowOut(
                    record_id=record.id,
                    tool_id=step_tool_id,
                    status=str(step.get("status", "")),
                    permission=step.get("permission") or {},
                    duration_ms=step.get("duration_ms"),
                    effects=[item for item in (effects or []) if isinstance(item, dict)],
                )
            )
    return rows


@debug_router.get("/debug/tools", response_model=ToolsOut)
def list_tools():
    """工具清单（声明 + 状态 + 健康度）；总闸 off → `{"enabled": false}`。"""
    if not _tools_enabled():
        return ToolsOut(enabled=False)
    registry = get_tool_registry()
    if registry is None:
        return ToolsOut(enabled=False)
    return ToolsOut(
        enabled=True,
        tools=[
            ToolSummaryOut(
                tool_id=definition.id,
                name=definition.name,
                namespace=definition.namespace,
                status=registry.effective_status(definition.id),
                side_effects=list(definition.side_effects),
                health=_tool_health_out(registry, definition.id),
            )
            for definition in registry.list()
        ],
        runtime_disabled=sorted(registry.runtime_disabled_ids()),
    )


@debug_router.get("/debug/tools/surface", response_model=ToolSurfaceOut)
def get_tool_surface(run_kind: str | None = None, user_id: str | None = None):
    """工具面投影结果（含裁剪原因）；双闸：总闸 + `v24_tool_surface_enabled`。"""
    settings = get_settings()
    if not _tools_enabled():
        return ToolSurfaceOut(enabled=False)
    if not settings.v24_tool_surface_enabled:
        raise HTTPException(
            status_code=403,
            detail="工具面投影未启用（v24_tool_surface_enabled=false）",
        )
    registry = get_tool_registry()
    if registry is None:
        return ToolSurfaceOut(enabled=False)
    resolved_kind = run_kind or TOOL_SURFACE_DEFAULT_RUN_KIND
    surface = ToolSurfaceResolver(registry, settings).resolve(
        resolved_kind,
        ToolContext(
            user_id=user_id or "",
            now=datetime.now(),
            settings=settings,
            run_kind=resolved_kind,
        ),
    )
    return ToolSurfaceOut(
        enabled=True,
        run_kind=surface.run_kind,
        run_kind_defaulted=not run_kind,
        tool_ids=list(surface.tool_ids),
        excluded=[dict(item) for item in surface.excluded],
        surface_hash=surface.surface_hash,
    )


@debug_router.get("/debug/tools/executions", response_model=ToolExecutionsOut)
def list_tool_executions(user_id: str, limit: int = 50):
    """执行台账（从 `action_records.steps` 投影）；无记录返回空列表。"""
    if not _tools_enabled():
        return ToolExecutionsOut(enabled=False)
    return ToolExecutionsOut(
        enabled=True,
        user_id=user_id,
        executions=_project_executions(user_id, limit),
    )


@debug_router.get("/debug/tools/permissions", response_model=ToolPermissionsOut)
def list_tool_permissions(user_id: str):
    """有效授权清单（持久层 + 进程层 + 通道级隐含）；总闸 off → `{"enabled": false}`。"""
    if not _permission_read_gate():
        return ToolPermissionsOut(enabled=False)
    service = get_confirmation_service(get_settings())
    grants = service.grant_records(user_id, datetime.now())
    return ToolPermissionsOut(
        enabled=True,
        user_id=user_id,
        grants=[ToolGrantOut(**grant) for grant in grants],
    )


@debug_router.get("/debug/tools/confirmations", response_model=ToolConfirmationsOut)
def list_tool_confirmations(user_id: str):
    """未决确认请求（按 created_at 倒序）；总闸 off → `{"enabled": false}`。"""
    if not _permission_read_gate():
        return ToolConfirmationsOut(enabled=False)
    service = get_confirmation_service(get_settings())
    return ToolConfirmationsOut(
        enabled=True,
        user_id=user_id,
        confirmations=[
            ToolConfirmationOut(
                request_id=request.request_id,
                tool_id=request.tool_id,
                status=request.status,
                dedupe_key=request.dedupe_key,
                scope_required=list(request.scope_required),
                prompt=request.prompt,
                confirm_kind=request.confirm_kind,
                created_at=request.created_at,
                expires_at=request.expires_at,
            )
            for request in service.pending(user_id)
        ],
    )


@debug_router.post(
    "/debug/tools/confirmations/{request_id}/revoke",
    response_model=ToolConfirmationRevokeOut,
)
def revoke_tool_confirmation(request_id: str):
    """撤销未决确认请求（运维，等价否定，不执行）；未找到 → 404。"""
    _require_permission_layer()
    service = get_confirmation_service(get_settings())
    request = service.get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="确认请求不存在")
    revoked = service.revoke_request(request_id)
    return ToolConfirmationRevokeOut(
        enabled=True,
        request_id=request_id,
        revoked=revoked,
        status="denied" if revoked else request.status,
    )


@debug_router.post("/debug/tools/permissions/revoke", response_model=ToolPermissionRevokeOut)
def revoke_tool_permissions(user_id: str, tool_id: str = "*"):
    """撤销授权（运维，工具级 / 范围级 / 会话级）；无匹配授权 → 404。"""
    _require_permission_layer()
    service = get_confirmation_service(get_settings())
    revoked = service.revoke(user_id, tool_id)
    if revoked <= 0:
        raise HTTPException(status_code=404, detail="无匹配授权")
    return ToolPermissionRevokeOut(
        enabled=True, user_id=user_id, tool_id=tool_id, revoked=revoked
    )


@debug_router.post("/debug/tools/{tool_id}/disable", response_model=ToolRuntimeStatusOut)
def disable_tool(tool_id: str):
    """运行期禁用（风控，进程内存态叠加，不写回声明）。"""
    registry = _require_tool_registry()
    if registry.get(tool_id) is None:
        raise HTTPException(status_code=404, detail="工具未注册")
    registry.set_runtime_disabled(tool_id)
    return ToolRuntimeStatusOut(
        enabled=True,
        tool_id=tool_id,
        effective_status=registry.effective_status(tool_id),
        runtime_disabled=True,
    )


@debug_router.post("/debug/tools/{tool_id}/enable", response_model=ToolRuntimeStatusOut)
def enable_tool(tool_id: str):
    """解除运行期禁用（恢复）。"""
    registry = _require_tool_registry()
    if registry.get(tool_id) is None:
        raise HTTPException(status_code=404, detail="工具未注册")
    registry.clear_runtime_disabled(tool_id)
    return ToolRuntimeStatusOut(
        enabled=True,
        tool_id=tool_id,
        effective_status=registry.effective_status(tool_id),
        runtime_disabled=False,
    )


@debug_router.get("/debug/tools/{tool_id}", response_model=ToolDetailOut)
def get_tool(tool_id: str, user_id: str | None = None, limit: int = 20):
    """单工具详情（schema / permission / 健康度 / 最近执行）；未注册 → 404。"""
    if not _tools_enabled():
        return ToolDetailOut(enabled=False)
    registry = get_tool_registry()
    definition = None if registry is None else registry.get(tool_id)
    if registry is None or definition is None:
        raise HTTPException(status_code=404, detail="工具未注册")
    return ToolDetailOut(
        enabled=True,
        tool_id=tool_id,
        definition=definition.model_dump(mode="json"),
        permission=definition.permission.model_dump(mode="json"),
        health=_tool_health_out(registry, tool_id),
        recent_executions=(
            [
                row.model_dump(mode="json")
                for row in _project_executions(user_id, limit, tool_id=tool_id)
            ]
            if user_id
            else []
        ),
    )


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
    view = development_attribution.development_state_attribution(state_id)
    if view is None:
        raise HTTPException(status_code=404, detail="development state 不存在")
    return view


@debug_router.get("/debug/development/users/{user_id}")
def list_user_development(user_id: str, limit: int = 50):
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
        logger.exception("回滚前快照创建失败：%s", user_id)
    anchor = relationship_snapshot_repository.get_latest_before(user_id, target_version)
    if anchor is None:
        raise HTTPException(status_code=404, detail="无法定位 ≤ target_version 的关键帧")
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
