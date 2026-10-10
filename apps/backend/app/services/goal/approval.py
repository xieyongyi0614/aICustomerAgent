"""计划审批闸门（Plan Approval Gate，baseline §8.6 / ADR-21）：待批清单 / 批准 / 驳回。

闸门本体在 `services/goal/planning.py::plan_goal()`——`plan_require_approval` ON 时计划通过结构闸
后**停在 `validated` 等人工批准**；本模块承载**人工裁决写面**：批准把待批计划转 `active`，驳回
转 `rejected`。

三条纪律：

- 写面只经 `goal_repository` 计划面既有函数（`get_plan` / `get_goal` / `list_plans_by_status` /
  `set_plan_status` / `set_plan_rejection`），不新增仓储接口、不新增状态值、不新增
  `decision_records` kind（新增 kind 需改 CHECK = 需迁移）。
- 批准复用 `goal_planning.activate_plan`——「撤同目标其余 active + 置新 active」的语义与自动路径
  **同源**，保证「单一 active 计划」不变量不因人工路径分叉。
- 状态与归属守卫 fail-closed：仅 `validated` 可裁决，其余状态原样返回 `not_pending` 且**不改库**；
  计划不存在**或不属于该用户**一律返回 `not_found`（不区分二者，避免泄露他人计划的存在性）。
"""

from __future__ import annotations

from app.models.goal import GoalPlanRecord
from app.repositories import goal_repository
from app.services.goal import planning as goal_planning

STATUS_PENDING = goal_planning.PLAN_STATUS_PENDING_APPROVAL
STATUS_APPROVED = goal_planning.PLAN_STATUS_ACTIVE
STATUS_REJECTED = goal_planning.PLAN_STATUS_REJECTED

OUTCOME_APPROVED = "approved"
OUTCOME_REJECTED = "rejected"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_NOT_PENDING = "not_pending"

DEFAULT_REJECTION_REASON = "rejected_by_user"
REJECTION_REASON_MAX_CHARS = 200


def list_pending(user_id: str) -> list[GoalPlanRecord]:
    """待批计划（状态 `validated`），按 `updated_at` 倒序（仓储既有排序）。"""
    return goal_repository.list_plans_by_status(user_id, (STATUS_PENDING,))


def approve(user_id: str, plan_id: str) -> dict:
    """批准待批计划：撤同目标其余 active → 本计划置 active。"""
    plan = _owned_pending_plan(user_id, plan_id)
    if plan is None:
        return _missing(plan_id)
    if isinstance(plan, str):
        return {"outcome": OUTCOME_NOT_PENDING, "plan_id": plan_id, "status": plan}
    activated = goal_planning.activate_plan(plan.goal_id, plan_id)
    return {
        "outcome": OUTCOME_APPROVED,
        "plan_id": plan_id,
        "goal_id": plan.goal_id,
        "status": None if activated is None else activated.status,
    }


def reject(user_id: str, plan_id: str, reason: str = "") -> dict:
    """驳回待批计划：置 `rejected` 并留理由（空理由落 `rejected_by_user`）。"""
    plan = _owned_pending_plan(user_id, plan_id)
    if plan is None:
        return _missing(plan_id)
    if isinstance(plan, str):
        return {"outcome": OUTCOME_NOT_PENDING, "plan_id": plan_id, "status": plan}
    text = (reason or "").strip() or DEFAULT_REJECTION_REASON
    rejected = goal_repository.set_plan_rejection(
        plan_id, text[:REJECTION_REASON_MAX_CHARS]
    )
    return {
        "outcome": OUTCOME_REJECTED,
        "plan_id": plan_id,
        "goal_id": plan.goal_id,
        "status": None if rejected is None else rejected.status,
    }


def _owned_pending_plan(user_id: str, plan_id: str) -> GoalPlanRecord | str | None:
    """归属与状态守卫：`None` = 不存在/非本人；`str` = 非待批态的当前状态；否则待批计划。"""
    plan = goal_repository.get_plan(plan_id)
    if plan is None:
        return None
    goal = goal_repository.get_goal(plan.goal_id)
    if goal is None or goal.user_id != user_id:
        return None
    return plan if plan.status == STATUS_PENDING else plan.status


def _missing(plan_id: str) -> dict:
    return {"outcome": OUTCOME_NOT_FOUND, "plan_id": plan_id}
