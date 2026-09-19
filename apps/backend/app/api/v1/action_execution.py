"""V2.6.0 Action Execution 调试端点（门控已随 vXX_ 开关体系删除，恒可见）。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.repositories import action_repository

action_execution_router = APIRouter()


@action_execution_router.get("/debug/action-execution/actions")
def list_execution_actions(
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    records = action_repository.list_records(
        user_id or "", status=status, limit=max(1, min(limit, 200))
    )
    return [r.model_dump(mode="json") for r in records]


@action_execution_router.get("/debug/action-execution/actions/{action_id}")
def get_execution_action(action_id: str):
    record = action_repository.get_record(action_id)
    if record is None:
        raise HTTPException(status_code=404, detail="action record 不存在")
    schedule = action_repository.get_schedule(action_id)
    data = record.model_dump(mode="json")
    data["schedule"] = schedule.model_dump(mode="json") if schedule else None
    return data


@action_execution_router.get("/debug/action-execution/schedules")
def list_execution_schedules(now: datetime | None = None, limit: int = 50):
    when = now or datetime.now()
    schedules = action_repository.list_due_schedules(when, limit=max(1, min(limit, 200)))
    return [s.model_dump(mode="json") for s in schedules]


@action_execution_router.get("/debug/action-execution/metrics")
def execution_metrics(window_hours: float = 24):
    since = datetime.now() - timedelta(hours=window_hours)
    statuses = ("created", "planned", "executing", "succeeded", "failed", "cancelled")
    buckets: dict[str, int] = {}
    total = 0
    succeeded = 0
    cancelled = 0
    retried = 0
    by_type: dict[str, int] = {}
    durations: list[float] = []
    for status in statuses:
        records = action_repository.list_by_status(status, limit=500)
        recent = [r for r in records if (r.created_at or datetime.min) >= since]
        buckets[status] = len(recent)
        total += len(recent)
        if status == "succeeded":
            succeeded += len(recent)
        if status == "cancelled":
            cancelled += len(recent)
        for record in recent:
            by_type[record.action_type] = by_type.get(record.action_type, 0) + 1
            if record.attempt > 1:
                retried += 1
            if record.executed_at and record.created_at:
                durations.append((record.executed_at - record.created_at).total_seconds())
    success_rate = (succeeded / total) if total else 0.0
    cancel_rate = (cancelled / total) if total else 0.0
    retry_rate = (retried / total) if total else 0.0
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    return {
        "window_hours": window_hours,
        "total": total,
        "by_status": buckets,
        "by_type": by_type,
        "success_rate": round(success_rate, 4),
        "cancel_rate": round(cancel_rate, 4),
        "retry_rate": round(retry_rate, 4),
        "avg_duration_seconds": round(avg_duration, 4),
    }
