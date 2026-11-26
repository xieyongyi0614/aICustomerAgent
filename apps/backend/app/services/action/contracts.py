"""V2.6.0 内部接口契约冻结（Manager / Executor / Result 三组）。"""

from typing import Callable

from app.services.action import executor as action_executor_module
from app.services.action import integration, manager, result as result_service, scheduler

ACTION_MANAGER_API: dict[str, tuple[str, ...]] = {
    "create": (
        "user_id",
        "action_type",
        "params",
        "source",
        "session_id",
        "goal_id",
        "priority",
        "intent",
        "target",
    ),
    "update": ("action_id",),
    "query": ("action_id", "user_id", "status", "limit"),
    "cancel": ("action_id", "reason"),
    "retry": ("action_id",),
    "get_status": ("action_id",),
}

ACTION_EXECUTOR_API: dict[str, tuple[str, ...]] = {
    "dispatch": ("action",),
    "run": ("action", "ctx"),
    "execute_internal": ("action", "ctx"),
    "execute_tool": ("action", "ctx"),
    "execute_external": ("action", "ctx"),
}

ACTION_RESULT_API_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "action_id",
        "status",
        "output",
        "error",
        "metadata",
        "observations",
        "created_at",
        "effects",
        "failure_kind",
    }
)

LOG_EVENTS: tuple[str, ...] = (
    "Action Created",
    "Action Scheduled",
    "Action Started",
    "Action Completed",
    "Action Failed",
    "Action Cancelled",
    "Action Retried",
)


def manager_contract_ok() -> bool:
    for name in ACTION_MANAGER_API:
        if not callable(getattr(manager, name, None)):
            return False
    return True


def executor_contract_ok() -> bool:
    for name in ACTION_EXECUTOR_API:
        if not hasattr(action_executor_module.ActionExecutor, name):
            return False
    return True


def result_contract_ok() -> bool:
    from app.models.action import ActionResult

    fields = set(ActionResult.model_fields)
    return ACTION_RESULT_API_FIELDS.issubset(fields)


def freeze_contracts() -> dict:
    return {
        "manager": manager_contract_ok(),
        "executor": executor_contract_ok(),
        "result": result_contract_ok(),
        "integration_feedback": hasattr(integration, "apply_result_feedback"),
        "scheduler_schedule": hasattr(scheduler, "schedule"),
    }
