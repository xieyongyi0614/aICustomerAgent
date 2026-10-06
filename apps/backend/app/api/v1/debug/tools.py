"""工具域调试端点：清单 / 工具面 / 执行台账 / 授权与确认 / 清单加载报告。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.core import timeutil
from app.api.v1.auth import require_user
from app.api.v1.deps import debug_surface_gate
from app.api.v1.schemas import (
    ToolConfirmationOut,
    ToolConfirmationRevokeOut,
    ToolConfirmationsOut,
    ToolDetailOut,
    ToolExecutionRowOut,
    ToolExecutionsOut,
    ToolExternalOut,
    ToolGrantOut,
    ToolHealthOut,
    ToolManifestOut,
    ToolManifestSkipOut,
    ToolManifestsOut,
    ToolPermissionRevokeOut,
    ToolPermissionsOut,
    ToolRuntimeStatusOut,
    ToolsOut,
    ToolSummaryOut,
    ToolSurfaceOut,
    ToolUserDefinedOut,
    ToolUserDefinedRevokeOut,
    ToolWorldIntentOut,
)
from app.application.autonomy_engine import tool_surface_degrade_count
from app.character.asuna.tool import RUN_KIND_FOREGROUND_CHAT
from app.core.settings import get_settings
from app.repositories import action_repository
from app.services.action.registry import (
    capability_registry_flags,
    peek_capability_registry,
)
from app.services.tool.confirmation import get_confirmation_service
from app.services.tool.context import ToolContext
from app.services.tool.ext_api import (
    allowed_ext_hosts,
    get_manifest_index,
    last_load_report,
)
from app.services.tool.registry import ToolRegistry, get_tool_registry
from app.services.tool.surface import ToolSurfaceResolver
from app.services.tool.user_defined import get_user_tool_registrar
from app.services.tool.world_intent import get_world_intent_submitter

tools_router = APIRouter(
    dependencies=[Depends(debug_surface_gate), Depends(require_user)], tags=["debug"]
)


TOOL_SURFACE_DEFAULT_RUN_KIND = RUN_KIND_FOREGROUND_CHAT

TOOL_EXECUTIONS_MIN_LIMIT = 1
TOOL_EXECUTIONS_MAX_LIMIT = 200
def _tool_registry() -> ToolRegistry:
    """工具注册表（模块级单例，惰性构建；工具系统已随 V2.4.0 转正常开）。"""
    return get_tool_registry()


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


@tools_router.get("/debug/tools", response_model=ToolsOut)
def list_tools():
    """工具清单（声明 + 状态 + 健康度）；总闸 off → `{"enabled": false}`。

    TOOL-007：附加 `world_intent` 段暴露 `world.intent.submit` 的接线状态
    （本版本恒 `status="not_wired"`、`writes=0`），防止"看着有其实没有"。
    P1-1：附加 `capability_registry_flags`（能力注册表的**构建期** Flag 快照）与
    `capability_names`，排障"为何某能力未注册"——注册表内容在首次构建时冻结，
    开关后开不会补注册。P2-3：附加 `tool_surface_degrade_count`（自治工具面降级计数）。
    """
    registry = _tool_registry()
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


@tools_router.get("/debug/tools/surface", response_model=ToolSurfaceOut)
def get_tool_surface(run_kind: str | None = None, user_id: str | None = None):
    """工具面投影结果（含裁剪原因）。"""
    settings = get_settings()
    registry = _tool_registry()
    resolved_kind = run_kind or TOOL_SURFACE_DEFAULT_RUN_KIND
    surface = ToolSurfaceResolver(registry, settings).resolve(
        resolved_kind,
        ToolContext(
            user_id=user_id or "",
            now=timeutil.now(),
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


@tools_router.get("/debug/tools/executions", response_model=ToolExecutionsOut)
def list_tool_executions(user_id: str, limit: int = 50):
    """执行台账（从 `action_records.steps` 投影）；无记录返回空列表。"""
    return ToolExecutionsOut(
        enabled=True,
        user_id=user_id,
        executions=_project_executions(user_id, limit),
    )


@tools_router.get("/debug/tools/permissions", response_model=ToolPermissionsOut)
def list_tool_permissions(user_id: str):
    """有效授权清单（持久层 + 进程层 + 通道级隐含）；总闸 off → `{"enabled": false}`。"""
    service = get_confirmation_service(get_settings())
    grants = service.grant_records(user_id, timeutil.now())
    return ToolPermissionsOut(
        enabled=True,
        user_id=user_id,
        grants=[ToolGrantOut(**grant) for grant in grants],
    )


@tools_router.get("/debug/tools/confirmations", response_model=ToolConfirmationsOut)
def list_tool_confirmations(user_id: str):
    """未决确认请求（按 created_at 倒序）；总闸 off → `{"enabled": false}`。"""
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


@tools_router.post(
    "/debug/tools/confirmations/{request_id}/revoke",
    response_model=ToolConfirmationRevokeOut,
)
def revoke_tool_confirmation(request_id: str):
    """撤销未决确认请求（运维，等价否定，不执行）；未找到 → 404。"""
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


@tools_router.post("/debug/tools/permissions/revoke", response_model=ToolPermissionRevokeOut)
def revoke_tool_permissions(user_id: str, tool_id: str = "*"):
    """撤销授权（运维，工具级 / 范围级 / 会话级）；无匹配授权 → 404。"""
    service = get_confirmation_service(get_settings())
    revoked = service.revoke(user_id, tool_id)
    if revoked <= 0:
        raise HTTPException(status_code=404, detail="无匹配授权")
    return ToolPermissionRevokeOut(
        enabled=True, user_id=user_id, tool_id=tool_id, revoked=revoked
    )


@tools_router.post("/debug/tools/{tool_id}/disable", response_model=ToolRuntimeStatusOut)
def disable_tool(tool_id: str):
    """运行期禁用（风控，进程内存态叠加，不写回声明）。"""
    registry = _tool_registry()
    if registry.get(tool_id) is None:
        raise HTTPException(status_code=404, detail="工具未注册")
    registry.set_runtime_disabled(tool_id)
    return ToolRuntimeStatusOut(
        enabled=True,
        tool_id=tool_id,
        effective_status=registry.effective_status(tool_id),
        runtime_disabled=True,
    )


@tools_router.post("/debug/tools/{tool_id}/enable", response_model=ToolRuntimeStatusOut)
def enable_tool(tool_id: str):
    """解除运行期禁用（恢复）。"""
    registry = _tool_registry()
    if registry.get(tool_id) is None:
        raise HTTPException(status_code=404, detail="工具未注册")
    registry.clear_runtime_disabled(tool_id)
    return ToolRuntimeStatusOut(
        enabled=True,
        tool_id=tool_id,
        effective_status=registry.effective_status(tool_id),
        runtime_disabled=False,
    )


@tools_router.get("/debug/tools/manifests", response_model=ToolManifestsOut)
def list_tool_manifests():
    """外部 API 清单加载报告（loaded / skipped / reasons）+ 已加载声明投影。

    TOOL-011：报告是**进程内存态**（重启由声明文件重建）；投影只含声明信息与凭据**变量名**，
    凭据值从不落内存结构、不落日志、不落端点（E17）。
    """
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


@tools_router.get("/debug/tools/external", response_model=ToolExternalOut)
def list_external_tools():
    """外部 API 工具清单：白名单现状 + 每条声明的**执行期**状态（不含凭据值）。"""
    hosts = sorted(allowed_ext_hosts(get_settings()))
    registry = _tool_registry()
    tools: list[dict] = []
    for manifest in get_manifest_index().all():
        view = manifest.public_view()
        view["status"] = registry.effective_status(manifest.tool_id)
        tools.append(view)
    return ToolExternalOut(
        enabled=True,
        allowed_hosts=hosts,
        host_whitelist_empty=not hosts,
        tools=tools,
    )


@tools_router.get("/debug/tools/user-defined", response_model=ToolUserDefinedOut)
def list_user_defined_tools():
    """自定义工具清单（进程内存态；重启即空，E13）：含推导副作用与强制纪律生效值。"""
    registrar = get_user_tool_registrar()
    registered = registrar.list_registered()
    return ToolUserDefinedOut(
        enabled=True,
        registered=registered,
        tools=[
            view for view in (registrar.view(tool_id) for tool_id in registered) if view
        ],
    )


@tools_router.post(
    "/debug/tools/user-defined/{tool_id}/revoke", response_model=ToolUserDefinedRevokeOut
)
def revoke_user_defined_tool(tool_id: str):
    """注销自定义工具（运维）：未注册 → 404；注销后调用得 `unavailable`（E14）。"""
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


@tools_router.get("/debug/tools/{tool_id}", response_model=ToolDetailOut)
def get_tool(tool_id: str, user_id: str | None = None, limit: int = 20):
    """单工具详情（schema / permission / 健康度 / 最近执行）；未注册 → 404。"""
    registry = _tool_registry()
    definition = registry.get(tool_id)
    if definition is None:
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
