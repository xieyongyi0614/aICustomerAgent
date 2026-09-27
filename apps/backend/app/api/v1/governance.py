"""生活数据治理端点（导出 / 删除）：user_id 仅从 token 解析（IDENT-002 收口）。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.api.v1.auth import require_user
from app.services.governance import (
    bundle_to_csv,
    delete_user_data,
    export_user_data,
)

governance_router = APIRouter()


class DeletionReportOut(BaseModel):
    user_id: str
    deleted_at: str
    per_domain: dict[str, int]
    total: int
    failed_domains: list[str]


class ExportBundleOut(BaseModel):
    user_id: str
    generated_at: str
    format: str
    domains: dict[str, dict]


@governance_router.get("/life/export")
def export_life_data(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    user_id: str = Depends(require_user),
):
    if format == "csv":
        bundle = export_user_data(user_id, fmt="csv")
        return Response(
            content=bundle_to_csv(bundle),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=life-export.csv"},
        )
    bundle = export_user_data(user_id, fmt="json")
    return ExportBundleOut(
        user_id=bundle.user_id,
        generated_at=bundle.generated_at.isoformat(),
        format=bundle.format,
        domains={name: dict(payload) for name, payload in bundle.domains.items()},
    )


@governance_router.delete("/life/data")
def delete_life_data(
    confirm: bool = Query(default=False),
    user_id: str = Depends(require_user),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="需要 confirm=true")
    report = delete_user_data(user_id)
    return DeletionReportOut(
        user_id=report.user_id,
        deleted_at=report.deleted_at.isoformat(),
        per_domain=dict(report.per_domain),
        total=report.total,
        failed_domains=list(report.failed_domains),
    )
