import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import (
    PlanContextOut,
    PlanDetailOut,
    PlanPendingOut,
    PlanPendingRowOut,
    PlanRevisionRowOut,
    PlanRevisionsOut,
    PlansOut,
    PlanStepRowOut,
    PlanStepsOut,
    PlanSummaryOut,
    ToolConfirmationRevokeOut,
    ToolConfirmationsOut,
    ToolConfirmationOut,
    ToolDetailOut,
    ToolExecutionRowOut,
    ToolExecutionsOut,
    ToolExternalOut,
    ToolGrantOut,
    ToolHealthOut,
    ToolManifestOut,
    ToolManifestsOut,
    ToolManifestSkipOut,
    ToolPermissionRevokeOut,
    ToolPermissionsOut,
    ToolRuntimeStatusOut,
    ToolSummaryOut,
    ToolSurfaceOut,
    ToolUserDefinedOut,
    ToolUserDefinedRevokeOut,
    ToolWorldIntentOut,
    ToolsOut,
)
from app.application.autonomy_engine import tool_surface_degrade_count
from app.character.asuna.tool import RUN_KIND_AUTONOMOUS_TICK, RUN_KIND_FOREGROUND_CHAT
from app.core.settings import get_settings
from app.models.evaluation import EvaluationSubjectKind
from app.models.goal import PLAN_STATUS_VALUES
from app.models.observability import DecisionKind
from app.models.relationship import RelationshipState
from app.repositories import (
    action_repository,
    conversation_repository,
    decision_repository,
    evaluation_repository,
    goal_repository,
    llm_call_repository,
    prompt_snapshot_repository,
    proactive_repository,
    trace_repository,
)
from app.services.action.registry import (
    capability_registry_flags,
    peek_capability_registry,
)
from app.services.observability.metrics_aggregator import (
    build_metric_report,
    summarize_llm_records,
)
from app.services.memory2 import attribution as memory2_attribution
from app.services.planning import context as plan_context
from app.services.planning import observer as plan_observer
from app.services.planning import scheduler as plan_scheduler
from app.services.reflection import attribution as reflection_attribution
from app.services.tool.confirmation import get_confirmation_service
from app.services.tool.context import ToolContext
from app.services.tool.ext_api import (
    EXT_API_NAMESPACE,
    allowed_ext_hosts,
    get_manifest_index,
    last_load_report,
)
from app.services.tool.registry import ToolRegistry, get_tool_registry
from app.services.tool.surface import ToolSurfaceResolver
from app.services.tool.user_defined import get_user_tool_registrar
from app.services.tool.world_context import build_tool_context
from app.services.tool.world_intent import get_world_intent_submitter
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

PLAN_PROJECTION_LIMIT = 200
PLAN_AUDIT_SEARCH_LIMIT = 200

PLAN_SOURCE_NAMES: tuple[str, ...] = (
    "goal",
    "context",
    "world",
    "memory",
    "reflection",
    "tool_surface",
)
"""`/debug/plans/context` 的六源键（architecture §3.3：Goal / Context / World / Memory /
Reflection / ToolSurface）；键集与顺序是本端点的形状契约。"""

PLAN_CONTEXT_PROJECTION_FAILED = "context_projection_failed"
"""装配投影异常的降级标记（§6.5：投影读取异常 → 降级结构 + log，不抛错）。

§6.5 的「降级结构（含 `degraded` 标记）」落在**本面唯一带降级位的输出模型**
（`PlanContextOut`）上：只有上下文装配有「可降级源」这一语义。其余五个端点是纯只读投影
（无降级位），读取失败与既有 `/debug/tools*` 面板同款上抛（`500`）——**不把故障吞成空列表**，
否则调试面会掩盖自己的故障。
"""

def _tools_enabled() -> bool:
    return bool(get_settings().tool_system_enabled)


def _require_tool_registry() -> ToolRegistry:
    """写类端点门控：总闸 off → 403；注册表不可用按未启用处理。"""
    if not _tools_enabled():
        raise HTTPException(
            status_code=403, detail="工具系统未启用（tool_system_enabled=false）"
        )
    registry = get_tool_registry()
    if registry is None:
        raise HTTPException(
            status_code=403, detail="工具系统未启用（tool_system_enabled=false）"
        )
    return registry


def _permission_layer_enabled() -> bool:
    return bool(getattr(get_settings(), "tool_permission_enabled", False))


def _require_permission_layer() -> None:
    """权限闸写类端点门控：总闸 off → 403；权限闸 off → 403，与 WS-018 惯例一致。"""
    _require_tool_registry()
    if not _permission_layer_enabled():
        raise HTTPException(
            status_code=403, detail="工具权限闸未启用（tool_permission_enabled=false）"
        )


def _permission_read_gate() -> bool:
    """权限闸读类端点门控：总闸 off → 200 `{"enabled": false}`；权限闸 off → 403。"""
    if not _tools_enabled():
        return False
    if not _permission_layer_enabled():
        raise HTTPException(
            status_code=403, detail="工具权限闸未启用（tool_permission_enabled=false）"
        )
    return True


def _external_api_enabled() -> bool:
    return bool(getattr(get_settings(), "tool_external_api_enabled", False))


def _user_defined_enabled() -> bool:
    return bool(getattr(get_settings(), "tool_user_defined_enabled", False))


def _require_external_api() -> None:
    """外部 API 面写类门控：总闸 off / 外部面 off → 403（与 WS-018 惯例一致）。"""
    _require_tool_registry()
    if not _external_api_enabled():
        raise HTTPException(
            status_code=403,
            detail="外部 API 工具未启用（tool_external_api_enabled=false）",
        )


def _external_api_read_gate() -> bool:
    """外部 API 面读类门控：总闸 off → 200 `{"enabled": false}`；外部面 off → 403。"""
    if not _tools_enabled():
        return False
    if not _external_api_enabled():
        raise HTTPException(
            status_code=403,
            detail="外部 API 工具未启用（tool_external_api_enabled=false）",
        )
    return True


def _require_user_defined() -> None:
    _require_tool_registry()
    if not _user_defined_enabled():
        raise HTTPException(
            status_code=403,
            detail="自定义工具未启用（tool_user_defined_enabled=false）",
        )


def _user_defined_read_gate() -> bool:
    if not _tools_enabled():
        return False
    if not _user_defined_enabled():
        raise HTTPException(
            status_code=403,
            detail="自定义工具未启用（tool_user_defined_enabled=false）",
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
    """工具清单（声明 + 状态 + 健康度）；总闸 off → `{"enabled": false}`。

    TOOL-007：附加 `world_intent` 段暴露 `world.intent.submit` 的接线状态
    （本版本恒 `status="not_wired"`、`writes=0`），防止"看着有其实没有"。
    P1-1：附加 `capability_registry_flags`（能力注册表的**构建期** Flag 快照）与
    `capability_names`，排障"为何某能力未注册"——注册表内容在首次构建时冻结，
    开关后开不会补注册。P2-3：附加 `tool_surface_degrade_count`（自治工具面降级计数）。
    """
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
        world_intent=ToolWorldIntentOut(**get_world_intent_submitter().status()),
        capability_registry_flags=capability_registry_flags(),
        capability_names=_capability_names(),
        tool_surface_degrade_count=tool_surface_degrade_count(),
    )


def _capability_names() -> list[str]:
    """已构建能力注册表的能力名（只读快照，**不触发构建**）。"""
    peeked = peek_capability_registry()
    if peeked is None:
        return []
    return sorted(entry["name"] for entry in peeked.describe())


@debug_router.get("/debug/tools/surface", response_model=ToolSurfaceOut)
def get_tool_surface(run_kind: str | None = None, user_id: str | None = None):
    """工具面投影结果（含裁剪原因）；双闸：总闸 + `tool_surface_enabled`。"""
    settings = get_settings()
    if not _tools_enabled():
        return ToolSurfaceOut(enabled=False)
    if not settings.tool_surface_enabled:
        raise HTTPException(
            status_code=403,
            detail="工具面投影未启用（tool_surface_enabled=false）",
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


@debug_router.get("/debug/tools/manifests", response_model=ToolManifestsOut)
def list_tool_manifests():
    """外部 API 清单加载报告（loaded / skipped / reasons）+ 已加载声明投影。

    TOOL-011：报告是**进程内存态**（重启由声明文件重建）；投影只含声明信息与凭据**变量名**，
    凭据值从不落内存结构、不落日志、不落端点（E17）。
    """
    if not _external_api_read_gate():
        return ToolManifestsOut(enabled=False)
    report = last_load_report()
    return ToolManifestsOut(
        enabled=True,
        path=report.path,
        loaded=list(report.loaded),
        skipped=[ToolManifestSkipOut(**item) for item in report.skipped],
        total=report.total,
        manifests=[
            ToolManifestOut(**manifest.public_view())
            for manifest in get_manifest_index().all()
        ],
    )


@debug_router.get("/debug/tools/external", response_model=ToolExternalOut)
def list_external_tools():
    """外部 API 工具清单：白名单现状 + 每条声明的**执行期**状态（不含凭据值）。"""
    if not _external_api_read_gate():
        return ToolExternalOut(enabled=False)
    hosts = sorted(allowed_ext_hosts(get_settings()))
    registry = get_tool_registry()
    tools: list[dict] = []
    for manifest in get_manifest_index().all():
        view = manifest.public_view()
        view["status"] = (
            "unregistered" if registry is None else registry.effective_status(manifest.tool_id)
        )
        tools.append(view)
    return ToolExternalOut(
        enabled=True,
        allowed_hosts=hosts,
        host_whitelist_empty=not hosts,
        tools=tools,
    )


@debug_router.get("/debug/tools/user-defined", response_model=ToolUserDefinedOut)
def list_user_defined_tools():
    """自定义工具清单（进程内存态；重启即空，E13）：含推导副作用与强制纪律生效值。"""
    if not _user_defined_read_gate():
        return ToolUserDefinedOut(enabled=False)
    registrar = get_user_tool_registrar()
    registered = registrar.list_registered()
    return ToolUserDefinedOut(
        enabled=True,
        registered=registered,
        tools=[
            view for view in (registrar.view(tool_id) for tool_id in registered) if view
        ],
    )


@debug_router.post(
    "/debug/tools/user-defined/{tool_id}/revoke", response_model=ToolUserDefinedRevokeOut
)
def revoke_user_defined_tool(tool_id: str):
    """注销自定义工具（运维）：未注册 → 404；注销后调用得 `unavailable`（E14）。"""
    _require_user_defined()
    registrar = get_user_tool_registrar()
    if registrar.view(tool_id) is None:
        raise HTTPException(status_code=404, detail="自定义工具未注册")
    registrar.unregister(tool_id)
    return ToolUserDefinedRevokeOut(
        enabled=True,
        tool_id=tool_id,
        revoked=True,
        registered=registrar.list_registered(),
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


def _plan_debug_enabled() -> bool:
    """计划调试面门控（总闸 + 调试子闸）。

    「调试总闸」即本面所属子系统的总闸 `planning_enabled`——与 WS-018
    （`world_simulation_enabled` + `debug_tick_enabled`）、TOOL-012
    （`tool_system_enabled`）同构；`PlanSettings` / `enablement` 中不存在第三个独立
    「调试总闸」Flag（PLAN-011 §4.2.6 / §6.3 D8 的三闸表述即此二闸）。
    """
    settings = get_settings()
    return bool(settings.planning_enabled) and bool(settings.plan_debug_enabled)


def _require_plan_debug() -> None:
    """Flag off → **404**（端点不可见，§6.5）。

    与既有面板的差别及理由：既有面板以 `{"enabled": false}` 兑现「总闸 off」是因为其输出模型
    带 `enabled` 字段；计划调试面的六个输出模型按 §6.3 字段契约**不含** `enabled`，故以 404
    兑现「未注册 / 不可见」语义（对调用方等价于端点不存在）。
    """
    if not _plan_debug_enabled():
        raise HTTPException(
            status_code=404,
            detail="计划调试面未启用（planning_enabled / plan_debug_enabled）",
        )


def _plan_statuses(status: str | None) -> tuple[str, ...]:
    """状态过滤（§6.1 D3）：缺省 = 全部五态；显式取值越界 → 400（不做静默收敛）。"""
    if status is None:
        return PLAN_STATUS_VALUES
    if status not in PLAN_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"计划状态取值非法：{status!r}；合法值集: {', '.join(PLAN_STATUS_VALUES)}",
        )
    return (status,)


@dataclass(frozen=True)
class _PlanScheduleContext:
    """`PlanScheduler` 的鸭子类型上下文（§8.4 的 `ctx` 在本端点的只读形态）。

    只投影判定所需的三项：`now`（冷却窗口）、`tool_surface`（面感知）、`settings`
    （既有 `plan_step_cooldown_minutes`）。六源装配**不在此发生**——调度只读计划本体，
    零新增读取面。
    """

    now: datetime
    tool_surface: object | None
    settings: object


def _autonomous_tool_surface(user_id: str, settings, now: datetime):
    """计划的执行面（`RUN_KIND_AUTONOMOUS_TICK`）只读投影：与 `PlanContextAssembler` 同一 Run Profile。

    工具系统总闸 off / 注册表不可得 / 解析失败 → `None`：此时调度**不判** `off_surface`
    （`PlanScheduler` 的缺省语义「缺面即不判」，绝不猜测）。
    """
    base = ToolContext(
        user_id=user_id,
        now=now,
        settings=settings,
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        source=plan_context.PLAN_TOOL_RUN_SOURCE,
    )
    try:
        if not settings.plan_tool_required:
            return ToolSurfaceResolver(None, settings).resolve(
                RUN_KIND_AUTONOMOUS_TICK, base
            )
        if not settings.tool_system_enabled:
            return None
        registry = get_tool_registry()
        if registry is None:
            return None
        tool_ctx = build_tool_context(base, settings=settings, now=now)
        return ToolSurfaceResolver(registry, settings).resolve(
            RUN_KIND_AUTONOMOUS_TICK, tool_ctx
        )
    except Exception:
        logger.exception("计划调试面工具面投影失败，按无面处理（不判 off_surface）")
        return None


def _schedule_context(user_id: str, settings, now: datetime) -> _PlanScheduleContext:
    return _PlanScheduleContext(
        now=now,
        tool_surface=_autonomous_tool_surface(user_id, settings, now),
        settings=settings,
    )


def _plan_summary(plan) -> PlanSummaryOut:
    return PlanSummaryOut(
        plan_id=plan.id,
        goal_id=plan.goal_id,
        version=plan.version,
        status=plan.status,
        step_count=len(plan.sub_goals),
        updated_at=plan.updated_at,
    )


def _plan_blocking(plan, ctx) -> tuple[int | None, str | None]:
    """计划级阻塞裁决 → (承载它的步序号, 原因)；`(None, None)` = 有可执行步或不可判。

    语义校核：`blocked_reason` 回答的是「**为何此刻没有可执行步**」，属**计划级**裁决，故原因
    只落在当前待推进步（`PlanScheduler.current_step`，执行序中首个未终态步）上，不对其余步
    作推断——同一计划内多个就绪步可能各有不同阻塞因，逐一贴同一原因会是猜测。
    """
    reason = plan_scheduler.PlanScheduler.blocked_reason(plan, ctx)
    if reason is None:
        return None, None
    step = plan_scheduler.PlanScheduler.current_step(plan)
    return (None, None) if step is None else (step.index, reason)


def _plan_step_rows(plan, ctx) -> list[PlanStepRowOut]:
    blocked_index, blocked_reason = _plan_blocking(plan, ctx)
    return [
        PlanStepRowOut(
            index=spec.index,
            description=spec.description,
            kind=spec.kind,
            tool_id=spec.tool_id,
            binding_reason=spec.binding_reason,
            status=spec.status,
            attempt_count=spec.attempt_count,
            blocked_reason=(blocked_reason if spec.index == blocked_index else None),
        )
        for spec in plan.sub_goals
    ]


def _plan_bindings(plan) -> list[dict]:
    return [
        {
            "step_index": spec.index,
            "kind": spec.kind,
            "tool_id": spec.tool_id,
            "binding_reason": spec.binding_reason,
            "capability": spec.capability,
        }
        for spec in plan.sub_goals
    ]


def _plan_criteria(plan) -> list[dict]:
    return [
        {
            "step_index": spec.index,
            "status": spec.status,
            "criteria": spec.criteria,
            "observation_keys": list(spec.observation_keys),
            "expected_effects": list(spec.expected_effects),
        }
        for spec in plan.sub_goals
    ]


def _plan_advance_history(plan) -> list[dict]:
    """推进历史：`decision_records`（`kind='goal_lifecycle'`）里该计划的 `PlanAdvance` 行。

    只读 + 投影：形态不符的行由 `project_plan_advance` 判为 `None` 而跳过（既有 lifecycle
    归因行同样落 `goal_lifecycle` kind，靠 `input_snapshot` 能否还原为 `PlanAdvance` 区分）。
    """
    goal = goal_repository.get_goal(plan.goal_id)
    if goal is None:
        return []
    history: list[dict] = []
    for record in decision_repository.search(
        user_id=goal.user_id,
        kind=DecisionKind.GOAL_LIFECYCLE.value,
        limit=PLAN_AUDIT_SEARCH_LIMIT,
    ):
        advance = plan_observer.project_plan_advance(record)
        if advance is None or advance.plan_id != plan.id:
            continue
        history.append(advance.model_dump(mode="json"))
    return sorted(history, key=lambda item: str(item.get("at") or ""))


def _plan_context_sources(context) -> dict:
    """六源投影（architecture §3.3）。

    脱敏纪律（§5.4）：**记忆与洞察只给计数与 id**（不回显记忆正文与洞察陈述），与既有
    `/debug/memory/{memory_id}/attribution` 的脱敏惯例一致；世界源只给键名与简报长度，
    不回显简报正文。
    """
    brief = context.world_brief
    return {
        "goal": {
            "id": context.goal.id,
            "type": context.goal.type,
            "status": context.goal.status,
            "layer": context.goal.layer,
            "domain": context.goal.domain,
            "priority": context.goal.priority,
            "ancestor_ids": [item.id for item in context.ancestors],
            "sibling_ids": [item.id for item in context.siblings],
        },
        "context": {
            "scene": None if context.scene is None else context.scene.location_id,
            "situation_ids": [situation.id for situation in context.situations],
            "relationship": dict(context.relationship),
            "run": dict(context.run),
        },
        "world": {
            "keys": sorted(context.world.keys()),
            "part_of_day": context.world.get("part_of_day"),
            "location": context.world.get("location"),
            "brief_chars": 0 if brief is None else len(brief.text or ""),
            "world_context_present": context.world_context is not None,
        },
        "memory": {
            "count": len(context.memories),
            "memory_ids": [memory.id for memory in context.memories],
            "types": sorted({memory.type for memory in context.memories if memory.type}),
        },
        "reflection": {
            "count": len(context.insights),
            "insight_ids": [insight.insight_id for insight in context.insights],
            "types": sorted({insight.type for insight in context.insights}),
            "confidences": [insight.confidence for insight in context.insights],
        },
        "tool_surface": {
            "run_kind": context.tool_surface.run_kind,
            "tool_count": len(context.tool_surface.tool_ids),
            "tool_ids": list(context.tool_surface.tool_ids),
            "surface_hash": context.tool_surface.surface_hash,
        },
    }


def _plan_revision_rows(goal_id: str, goal) -> list[PlanRevisionRowOut]:
    """修订链重建（§4.2.4）：链行以 `goal_plans` 版本行**存在**为前提，字段取审计行。

    两张既有表缺一即该步不成立：`goal_plans` 给出该目标的版本行（`from_version` /
    `to_version` 必须真实存在），`decision_records` 给出六字段（`plan_revised` 审计）。
    排序按 `to_version` 升序（链的自然序）。
    """
    versions = {plan.version for plan in goal_repository.list_plans(goal_id)}
    rows: list[PlanRevisionRowOut] = []
    for record in decision_repository.search(
        user_id=goal.user_id,
        kind=DecisionKind.GOAL_LIFECYCLE.value,
        limit=PLAN_AUDIT_SEARCH_LIMIT,
    ):
        revision = plan_observer.project_plan_revision(record)
        if revision is None:
            continue
        snapshot = record.input_snapshot or {}
        if str(snapshot.get("goal_id") or "") != goal_id:
            continue
        if revision.from_version not in versions or revision.to_version not in versions:
            continue
        rows.append(
            PlanRevisionRowOut(
                from_version=revision.from_version,
                to_version=revision.to_version,
                reason=revision.reason,
                trigger_source=revision.trigger_source,
                evidence_refs=list(revision.evidence_refs),
                kept_steps=list(revision.kept_steps),
                at=revision.at,
            )
        )
    return sorted(rows, key=lambda row: row.to_version)


def _load_plan(plan_id: str) -> tuple:
    """计划 + 归属目标（未找到 → 404，与既有 `/debug/tools/{tool_id}` 风格一致）。"""
    plan = goal_repository.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    goal = goal_repository.get_goal(plan.goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="计划归属目标不存在")
    return plan, goal


@debug_router.get("/debug/plans", response_model=PlansOut)
def list_plans(user_id: str, status: str | None = None):
    """计划清单（含版本链与状态）：`goal_id` 相同的多行即该目标的版本链。"""
    _require_plan_debug()
    plans = goal_repository.list_plans_by_status(user_id, _plan_statuses(status))
    return PlansOut(plans=[_plan_summary(plan) for plan in plans[:PLAN_PROJECTION_LIMIT]])


@debug_router.get("/debug/plans/context", response_model=PlanContextOut)
async def get_plan_context(user_id: str, goal_id: str):
    """`PlanContext` 装配结果投影：六源 + `degraded` 清单（脱敏：记忆 / 洞察只计数与 id）。

    硬依赖不可得（工具系统 off / 注册表不可得 / 目标缺失）时返回**降级结构**
    （`degraded` 记 `PlanUnavailable.reason`），不抛错——与 §6.5 的投影读取异常同款处置。
    """
    _require_plan_debug()
    goal = goal_repository.get_goal(goal_id)
    if goal is None or (user_id and goal.user_id != user_id):
        raise HTTPException(status_code=404, detail="目标不存在")
    try:
        assembled = await plan_context.PlanContextAssembler().assemble(
            goal, run=None, now=datetime.now()
        )
    except Exception:
        logger.exception("计划上下文装配失败，返回降级结构：%s", goal_id)
        return PlanContextOut(sources={}, degraded=[PLAN_CONTEXT_PROJECTION_FAILED])
    if isinstance(assembled, plan_context.PlanUnavailable):
        return PlanContextOut(sources={}, degraded=[assembled.reason])
    return PlanContextOut(
        sources=_plan_context_sources(assembled),
        degraded=list(assembled.degraded),
    )


@debug_router.get("/debug/plans/revisions", response_model=PlanRevisionsOut)
def list_plan_revisions(goal_id: str):
    """修订链（from/to version + reason + trigger_source + evidence_refs + kept_steps）。"""
    _require_plan_debug()
    goal = goal_repository.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    return PlanRevisionsOut(revisions=_plan_revision_rows(goal_id, goal))


@debug_router.get("/debug/plans/pending", response_model=PlanPendingOut)
def list_pending_plans(user_id: str):
    """待推进步骤（含 `off_surface` / 冷却中 / 前置失败原因）：每个被阻塞的活跃计划一行。"""
    _require_plan_debug()
    settings = get_settings()
    now = datetime.now()
    ctx = _schedule_context(user_id, settings, now)
    pending: list[PlanPendingRowOut] = []
    for goal, plan in goal_repository.list_active_plans(user_id):
        step_index, reason = _plan_blocking(plan, ctx)
        if step_index is None or reason is None:
            continue
        step = plan_scheduler.PlanScheduler.current_step(plan)
        if step is None:
            continue
        pending.append(
            PlanPendingRowOut(
                goal_id=goal.id,
                plan_id=plan.id,
                step_index=step_index,
                tool_id=step.tool_id,
                reason=reason,
            )
        )
    return PlanPendingOut(pending=pending)


@debug_router.get("/debug/plans/{plan_id}/steps", response_model=PlanStepsOut)
def list_plan_steps(plan_id: str):
    """步骤视图：绑定（`tool_id` / `binding_reason`）与 `blocked_reason` 逐条可读。"""
    _require_plan_debug()
    plan, goal = _load_plan(plan_id)
    ctx = _schedule_context(goal.user_id, get_settings(), datetime.now())
    return PlanStepsOut(steps=_plan_step_rows(plan, ctx))


@debug_router.get("/debug/plans/{plan_id}", response_model=PlanDetailOut)
def get_plan(plan_id: str):
    """单计划详情：本体 + 步骤 + 绑定 + 判据 + 推进历史（`decision_records` 投影）。"""
    _require_plan_debug()
    plan, goal = _load_plan(plan_id)
    ctx = _schedule_context(goal.user_id, get_settings(), datetime.now())
    return PlanDetailOut(
        plan=_plan_summary(plan).model_dump(mode="json"),
        steps=_plan_step_rows(plan, ctx),
        bindings=_plan_bindings(plan),
        criteria=_plan_criteria(plan),
        advance_history=_plan_advance_history(plan),
    )
