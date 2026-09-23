"""PLA-010 待确认登记薄适配：复用 scene_state.pending_action + action_schedules，零新表。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.action import ActionIntent, ActionRecord, ActionSchedule
from app.models.ledger import LedgerExtraction
from app.models.scene import PendingAction, SceneState
from app.repositories import action_repository, scene_state_repository
from app.services.ledger.confirmation import (
    ConfirmationRequest,
    request_from_mapping,
    request_to_mapping,
)

PENDING_PREFIX = "ledger_confirm:"


def _extract_to_mapping(extraction: LedgerExtraction) -> dict[str, Any]:
    data = extraction.model_dump(mode="json")
    return data


def _extract_from_mapping(payload: dict[str, Any]) -> LedgerExtraction:
    return LedgerExtraction.model_validate(payload)


def register_pending(
    *,
    user_id: str,
    session_id: str,
    request: ConfirmationRequest,
    extraction: LedgerExtraction,
    now: datetime | None = None,
) -> ActionRecord | None:
    """登记待确认：ActionRecord 载荷 + scene_state 指针 + action_schedules 到期。"""
    timestamp = now or datetime.now()
    existing_state = scene_state_repository.get_scene_state(session_id)
    existing = existing_state.pending_action
    if existing is not None and existing.status == "pending" and existing.action.startswith(
        PENDING_PREFIX
    ):
        loaded = load_pending(session_id)
        if loaded is not None and loaded[0].pending_key == request.pending_key:
            return None

    record = ActionRecord(
        id=action_repository.new_record_id(),
        user_id=user_id,
        session_id=session_id,
        source="conversation",
        action_type="record_ledger_entry",
        intent=ActionIntent(
            action_type="record_ledger_entry",
            confidence="ambiguous",
            params={"pending_key": request.pending_key},
            dedupe_key=request.pending_key,
        ).model_dump(mode="json"),
        dedupe_key=request.pending_key,
        params={
            "confirmation": request_to_mapping(request),
            "extraction": _extract_to_mapping(extraction),
        },
        status="planned",
        gate_reason="pending_confirmation",
        created_at=timestamp,
        updated_at=timestamp,
        scheduled_at=request.expires_at,
    )
    action_repository.save_record(record)
    action_repository.save_schedule(
        ActionSchedule(
            id=action_repository.new_schedule_id(),
            action_id=record.id,
            when_type="delay",
            scheduled_at=request.expires_at,
            status="scheduled",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    state = scene_state_repository.get_scene_state(session_id)
    marker = f"{PENDING_PREFIX}{record.id}"[:50]
    next_state = state.model_copy(
        update={
            "pending_action": PendingAction(
                action=marker,
                status="pending",
                created_at_turn=state.turn_id,
                created_at=timestamp,
            )
        }
    )
    scene_state_repository.upsert_scene_state(session_id, next_state)
    return record


def load_pending(
    session_id: str,
) -> tuple[ConfirmationRequest, LedgerExtraction, ActionRecord] | None:
    state = scene_state_repository.get_scene_state(session_id)
    pending = state.pending_action
    if pending is None or pending.status != "pending" or not pending.action.startswith(
        PENDING_PREFIX
    ):
        return None
    record_id = pending.action[len(PENDING_PREFIX) :]
    record = action_repository.get_record(record_id)
    if record is None:
        return None
    payload = record.params or {}
    if "confirmation" not in payload or "extraction" not in payload:
        return None
    return (
        request_from_mapping(payload["confirmation"]),
        _extract_from_mapping(payload["extraction"]),
        record,
    )


def clear_pending(session_id: str, *, status: str = "cancelled") -> None:
    state = scene_state_repository.get_scene_state(session_id)
    if state.pending_action is None:
        return
    pending = state.pending_action.model_copy(update={"status": status})
    scene_state_repository.upsert_scene_state(
        session_id, state.model_copy(update={"pending_action": pending})
    )


def expire_if_due(
    session_id: str, *, now: datetime | None = None
) -> bool:
    """到期未确认：清除登记，不产生账目。返回是否已失效。"""
    timestamp = now or datetime.now()
    loaded = load_pending(session_id)
    if loaded is None:
        return False
    request, _extraction, record = loaded
    if request.expires_at > timestamp:
        return False
    clear_pending(session_id, status="cancelled")
    record.status = "cancelled"
    record.gate_reason = "pending_confirmation"
    record.updated_at = timestamp
    action_repository.save_record(record)
    schedule = action_repository.get_schedule(record.id)
    if schedule is not None:
        schedule.status = "cancelled"
        schedule.updated_at = timestamp
        action_repository.save_schedule(schedule)
    return True


__all__ = [
    "PENDING_PREFIX",
    "clear_pending",
    "expire_if_due",
    "load_pending",
    "register_pending",
]
