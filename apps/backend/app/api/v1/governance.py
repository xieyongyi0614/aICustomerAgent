from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.core.settings import get_settings
from app.services.governance import (
    bundle_to_csv,
    delete_user_data,
    export_user_data,
)
from app.services.identity.user_service import resolve_user

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


def _resolve_current_user(requested: str | None) -> str:
    resolved = resolve_user(requested)
    if requested and requested != resolved.user_id:
        raise HTTPException(status_code=403, detail="不得读写他人数据")
    allowed = get_settings().default_user
    if resolved.user_id != allowed:
        raise HTTPException(status_code=403, detail="不得读写他人数据")
    return resolved.user_id


@governance_router.get("/life/export")
def export_life_data(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    user_id: str | None = Query(default=None),
):
    current = _resolve_current_user(user_id)
    if format == "csv":
        bundle = export_user_data(current, fmt="csv")
        return Response(
            content=bundle_to_csv(bundle),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=life-export.csv"},
        )
    bundle = export_user_data(current, fmt="json")
    return ExportBundleOut(
        user_id=bundle.user_id,
        generated_at=bundle.generated_at.isoformat(),
        format=bundle.format,
        domains={name: dict(payload) for name, payload in bundle.domains.items()},
    )


@governance_router.delete("/life/data")
def delete_life_data(
    confirm: bool = Query(default=False),
    user_id: str | None = Query(default=None),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="需要 confirm=true")
    current = _resolve_current_user(user_id)
    report = delete_user_data(current)
    return DeletionReportOut(
        user_id=report.user_id,
        deleted_at=report.deleted_at.isoformat(),
        per_domain=dict(report.per_domain),
        total=report.total,
        failed_domains=list(report.failed_domains),
    )
