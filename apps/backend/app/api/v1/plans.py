"""计划审批产品 API：待批清单 / 批准 / 驳回（baseline §8.6 / ADR-21）。

只做表现层——鉴权 + 参数/响应形状 + 错误→HTTP 映射；裁决逻辑在
`services/goal/approval.py`。与只读调试面 `api/v1/debug/plans.py` 分离：本面是**写面**，
生产侧可用（不挂 `debug_surface_gate`），身份一律经 `require_user` 从 token 解析。

状态码：404 = 计划不存在或不属于当前用户（不区分，避免泄露他人计划存在性）；
409 = 计划不在待批状态（已批准 / 已驳回 / 已 superseded，`not_pending`，不改库）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.auth import require_user
from app.services.goal import approval as plan_approval

plans_router = APIRouter(prefix="/plans", tags=["plans"])

NOT_FOUND_DETAIL = "计划不存在"
NOT_PENDING_DETAIL = "计划不在待批状态"


class PendingPlanOut(BaseModel):
    plan_id: str
    goal_id: str
    version: int
    status: str
    step_count: int
    updated_at: datetime


class PendingPlansOut(BaseModel):
    plans: list[PendingPlanOut]


class RejectPlanRequest(BaseModel):
    reason: str = ""


class PlanApprovalOut(BaseModel):
    plan_id: str
    outcome: str
    goal_id: str | None = None
    status: str | None = None


@plans_router.get("/pending", response_model=PendingPlansOut)
def list_pending_plans(user_id: str = Depends(require_user)):
    """待批计划清单（状态 `validated`）。"""
    return PendingPlansOut(
        plans=[
            PendingPlanOut(
                plan_id=plan.id,
                goal_id=plan.goal_id,
                version=plan.version,
                status=plan.status,
                step_count=len(plan.sub_goals),
                updated_at=plan.updated_at,
            )
            for plan in plan_approval.list_pending(user_id)
        ]
    )


@plans_router.post("/{plan_id}/approve", response_model=PlanApprovalOut)
def approve_plan(plan_id: str, user_id: str = Depends(require_user)):
    """批准待批计划：置 `active` 并撤下同目标其余 `active` 计划。"""
    return _resolve(plan_approval.approve(user_id, plan_id))


@plans_router.post("/{plan_id}/reject", response_model=PlanApprovalOut)
def reject_plan(
    plan_id: str,
    body: RejectPlanRequest | None = None,
    user_id: str = Depends(require_user),
):
    """驳回待批计划：置 `rejected` 并留理由。"""
    reason = "" if body is None else body.reason
    return _resolve(plan_approval.reject(user_id, plan_id, reason))


def _resolve(result: dict) -> PlanApprovalOut:
    outcome = result["outcome"]
    if outcome == plan_approval.OUTCOME_NOT_FOUND:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    if outcome == plan_approval.OUTCOME_NOT_PENDING:
        raise HTTPException(status_code=409, detail=NOT_PENDING_DETAIL)
    return PlanApprovalOut(
        plan_id=result["plan_id"],
        outcome=outcome,
        goal_id=result.get("goal_id"),
        status=result.get("status"),
    )
