"""V2.6.0 ActionResult 统一契约与投影映射（architecture.md §8.4）。"""

import uuid
from datetime import datetime
from typing import Any

from app.core.settings import get_settings
from app.models.action import (
    ActionEffect,
    ActionResult,
    CapabilityResult,
    FailureKind,
)


def _now() -> datetime:
    return datetime.now()


def result_timeout_enabled() -> bool:
    return bool(getattr(get_settings(), "v26_action_result_enabled", False))


def make_result_id() -> str:
    return f"res_{uuid.uuid4().hex[:8]}"


def ensure_result_identity(result: ActionResult, action_id: str) -> ActionResult:
    if not result.id:
        result = result.model_copy(update={"id": make_result_id()})
    if not result.action_id:
        result = result.model_copy(update={"action_id": action_id})
    if result.created_at is None:
        result = result.model_copy(update={"created_at": _now()})
    return result


def from_capability_result(
    result: CapabilityResult,
    *,
    action_id: str,
    effects: list[ActionEffect] | None = None,
) -> ActionResult:
    payload = dict(result.payload or {})
    legacy_failure = payload.get("failure_kind")
    failure_kind: FailureKind | None = None
    if isinstance(legacy_failure, str) and legacy_failure in (
        "transient",
        "permanent",
        "timeout",
        "unavailable",
    ):
        failure_kind = legacy_failure  # type: ignore[assignment]
    output = {k: v for k, v in payload.items() if k != "failure_kind"}
    status: str
    if result.status == "succeeded":
        status = "succeeded"
    elif result.status == "timeout":
        status = "timeout" if result_timeout_enabled() else "failed"
        failure_kind = failure_kind or "timeout"
    elif result.status == "unavailable":
        status = "failed"
        failure_kind = failure_kind or "unavailable"
    else:
        status = "failed"
        failure_kind = failure_kind or "transient"
    observations = {
        k: output[k]
        for k in ("world_event_id", "memory_id", "entity_id", "note")
        if k in output
    }
    return ensure_result_identity(
        ActionResult(
            status=status,  # type: ignore[arg-type]
            effects=list(effects or []),
            error=result.error,
            failure_kind=failure_kind,
            output=output,
            metadata={"usage": dict(result.usage or {}), "source": "capability"},
            observations=observations,
        ),
        action_id=action_id,
    )


def from_tool_execution(execution: Any, *, action_id: str) -> ActionResult:
    status_raw = getattr(execution, "status", "failed")
    error = getattr(execution, "error", None)
    result_payload = getattr(execution, "result", None)
    output: dict[str, Any] = {}
    if isinstance(result_payload, dict):
        nested = result_payload.get("payload")
        if isinstance(nested, dict):
            output = dict(nested)
        else:
            output = {
                k: v for k, v in result_payload.items() if k != "failure_kind"
            }
    elif result_payload is not None and hasattr(result_payload, "model_dump"):
        dumped = result_payload.model_dump(mode="json")
        nested = dumped.get("payload")
        if isinstance(nested, dict):
            output = dict(nested)
        else:
            output = dict(dumped)
    if status_raw == "succeeded":
        status = "succeeded"
        failure_kind = None
    elif status_raw == "timeout":
        status = "timeout" if result_timeout_enabled() else "failed"
        failure_kind = "timeout"
    elif status_raw in ("unavailable",):
        status = "failed"
        failure_kind = "unavailable"
    else:
        status = "failed"
        failure_kind = "permanent" if status_raw in ("denied", "invalid") else "transient"
    observations = {
        k: output[k]
        for k in ("world_event_id", "memory_id", "entity_id", "note")
        if k in output
    }
    return ensure_result_identity(
        ActionResult(
            status=status,  # type: ignore[arg-type]
            error=str(error)[:120] if error else None,
            failure_kind=failure_kind,  # type: ignore[arg-type]
            output=output,
            metadata={"tool_status": status_raw, "source": "tool"},
            observations=observations,
        ),
        action_id=action_id,
    )


def from_plan_step_outcome(outcome: Any, *, action_id: str) -> ActionResult:
    status_raw = getattr(outcome, "status", None) or (
        outcome.get("status") if isinstance(outcome, dict) else "failed"
    )
    error = getattr(outcome, "error", None) or (
        outcome.get("error") if isinstance(outcome, dict) else None
    )
    output: dict[str, Any] = {}
    if hasattr(outcome, "output") and isinstance(getattr(outcome, "output"), dict):
        output = dict(outcome.output)
    elif isinstance(outcome, dict):
        output = dict(outcome.get("output") or {})
    if status_raw in ("succeeded", "success"):
        status = "succeeded"
    elif status_raw == "partial":
        status = "partial"
    elif status_raw == "timeout":
        status = "timeout" if result_timeout_enabled() else "failed"
    else:
        status = "failed"
    return ensure_result_identity(
        ActionResult(
            status=status,  # type: ignore[arg-type]
            error=str(error)[:120] if error else None,
            output=output,
            metadata={"source": "plan_step"},
        ),
        action_id=action_id,
    )


def classify_retryable(result: ActionResult) -> bool:
    if result.status not in ("failed", "timeout"):
        return False
    return result.failure_kind in ("transient", "timeout")


def feedback_payload(result: ActionResult) -> dict[str, Any]:
    payload = result.dual_write_legacy_keys()
    payload["feedback_kinds"] = sorted({effect.kind for effect in result.effects})
    return payload
