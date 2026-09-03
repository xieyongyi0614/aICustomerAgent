"""V9 /debug/actions（tool-integration.md 与 architecture.md H-A7）。

调试/审计端点：查看 ActionRecord、状态、结果、失败原因与执行 trace。
只读为主，手动重试/取消属维护操作，非新的业务执行入口。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.models.action import transition_action
from app.repositories import action_repository

action_router = APIRouter()


@action_router.get("/debug/actions")
def list_actions(
    user_id: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    window_hours: float | None = None,
    limit: int = 50,
):
    since = (
        datetime.now() - timedelta(hours=window_hours) if window_hours is not None else None
    )
    records = action_repository.list_records(user_id or "", status=status, limit=max(1, min(limit, 200)))
    if action_type is not None:
        records = [r for r in records if r.action_type == action_type]
    if since is not None:
        records = [r for r in records if (r.created_at or datetime.min) >= since]
    return [r.model_dump(mode="json") for r in records]


@action_router.get("/debug/actions/{record_id}")
def get_action(record_id: str):
    record = action_repository.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="action record 不存在")
    return record.model_dump(mode="json")


@action_router.post("/debug/actions/{record_id}/retry")
def retry_action(record_id: str):
    """手动重试失败行动：仅 failed/executing(retryable) 可重试。"""
    record = action_repository.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="action record 不存在")
    if record.status not in ("failed", "executing"):
        raise HTTPException(status_code=409, detail=f"action status={record.status} 不可重试")
    next_status = transition_action(
        record.status, "step_retryable_failed", attempts_exceeded=False
    )
    if next_status is None:
        next_status = "executing"
    record.status = next_status
    record.attempt += 1
    from datetime import timedelta

    record.next_retry_at = datetime.now() + timedelta(seconds=5)
    record.updated_at = datetime.now()
    action_repository.save_record(record)
    return {"id": record.id, "status": record.status, "attempt": record.attempt}


@action_router.post("/debug/actions/{record_id}/cancel")
def cancel_action(record_id: str):
    record = action_repository.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="action record 不存在")
    if record.status not in ("created", "planned"):
        raise HTTPException(status_code=409, detail=f"action status={record.status} 不可取消")
    next_status = transition_action(record.status, "cancel_requested")
    if next_status is None:
        raise HTTPException(status_code=409, detail=f"action status={record.status} 不可取消")
    record.status = next_status
    record.gate_reason = "cancelled_by_user"
    record.updated_at = datetime.now()
    action_repository.save_record(record)
    return {"id": record.id, "status": record.status}
