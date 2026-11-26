"""PLA-010 待确认登记薄适配：复用 scene_state.pending_action + action_schedules，零新表。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core import timeutil
from app.models.action import ActionIntent, ActionRecord, ActionSchedule
from app.models.ledger import (
    LedgerAmountError,
    LedgerEntryDraft,
    LedgerExtraction,
    to_minor,
)
from app.models.scene import PendingAction, SceneState
from app.repositories import action_repository, scene_state_repository
from app.services.ledger import category as category_service
from app.services.ledger.confirmation import (
    CONFIRM_TTL_HOURS,
    CandidateOption,
    ConfirmationRequest,
    request_from_mapping,
    request_to_mapping,
)

PENDING_PREFIX = "ledger_confirm:"
PENDING_GATE_REASON = "pending_confirmation"
PENDING_ACTION_TYPE = "record_ledger_entry"
PENDING_SCAN_MAX = 200

DETECTED_KEY = "detected"
"""待确认载荷的 `detected` 段：同轮**确定性词表链路**的解析（明细 / 已归一类目）。

存在时优先于 LLM 抽取的 `category_hint`：实测 LLM 会给「饭」这类单字提示，
四级归一必然落回退类目「其他」；同时保证确认后落的这一笔与词表链路同源
（明细、类目都不丢）。
"""


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
    detected: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ActionRecord | None:
    """登记待确认：ActionRecord 载荷 + scene_state 指针 + action_schedules 到期。"""
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
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
            **({DETECTED_KEY: detected} if detected else {}),
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
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    loaded = load_pending(session_id)
    if loaded is None:
        return False
    request, _extraction, record = loaded
    if timeutil.ensure_aware(request.expires_at) > timestamp:
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


@dataclass(frozen=True, slots=True)
class PendingItem:
    pending_key: str
    record_id: str
    session_id: str
    reason: str
    question: str
    candidates: tuple[CandidateOption, ...]
    amount_minor: int | None
    source_ref: str
    expires_at: datetime
    category_hint: str | None
    direction: str | None
    merchant_hint: str | None
    occurred_at_hint: str | None
    confidence: float

    @property
    def has_ai_guess(self) -> bool:
        return any(
            [
                (self.category_hint or "").strip(),
                (self.direction or "").strip(),
                (self.merchant_hint or "").strip(),
            ]
        )


@dataclass(frozen=True, slots=True)
class PendingList:
    generated_at: datetime
    total: int
    degraded: int
    items: tuple[PendingItem, ...]


@dataclass(frozen=True, slots=True)
class ConfirmOutcome:
    entry_id: str
    created: bool
    learned_alias: str | None


@dataclass(frozen=True, slots=True)
class _Located:
    record: ActionRecord
    request: ConfirmationRequest
    extraction: LedgerExtraction
    consumed: bool


class PendingNotFoundError(ValueError):
    pass


class PendingValidationError(ValueError):
    pass


def _marker(record_id: str) -> str:
    return f"{PENDING_PREFIX}{record_id}"[:50]


def _payload(record: ActionRecord) -> tuple[ConfirmationRequest, LedgerExtraction] | None:
    payload = record.params or {}
    if "confirmation" not in payload or "extraction" not in payload:
        return None
    try:
        return (
            request_from_mapping(payload["confirmation"]),
            _extract_from_mapping(payload["extraction"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _detected_payload(record: ActionRecord) -> dict[str, Any]:
    payload = record.params or {}
    detected = payload.get(DETECTED_KEY)
    return detected if isinstance(detected, dict) else {}


def _is_pending_record(record: ActionRecord) -> bool:
    return (
        record.action_type == PENDING_ACTION_TYPE
        and record.gate_reason == PENDING_GATE_REASON
    )


def _pointer_is_live(session_id: str, record_id: str) -> bool:
    pending = scene_state_repository.get_scene_state(session_id).pending_action
    if pending is None or pending.status != "pending":
        return False
    return pending.action == _marker(record_id)


def _to_item(record: ActionRecord, request: ConfirmationRequest, extraction: LedgerExtraction) -> PendingItem:
    detected = _detected_payload(record)
    return PendingItem(
        pending_key=request.pending_key,
        record_id=record.id,
        session_id=record.session_id or "",
        reason=request.reason,
        question=request.question,
        candidates=request.candidates,
        amount_minor=request.amount_minor,
        source_ref=request.source_ref,
        expires_at=request.expires_at,
        category_hint=str(detected.get("category_name") or "") or extraction.category_hint,
        direction=str(detected.get("direction") or "") or extraction.direction,
        merchant_hint=extraction.merchant_hint,
        occurred_at_hint=extraction.occurred_at_hint,
        confidence=extraction.confidence,
    )


def list_pending(
    user_id: str, *, now: datetime | None = None, limit: int = 50
) -> PendingList:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    records = action_repository.list_records(
        user_id, status="planned", limit=max(limit, PENDING_SCAN_MAX)
    )
    items: list[PendingItem] = []
    degraded = 0
    for record in records:
        if not _is_pending_record(record):
            continue
        session_id = record.session_id or ""
        if not session_id:
            degraded += 1
            continue
        payload = _payload(record)
        if payload is None:
            degraded += 1
            continue
        if expire_if_due(session_id, now=timestamp):
            continue
        if not _pointer_is_live(session_id, record.id):
            continue
        request, extraction = payload
        if timeutil.ensure_aware(request.expires_at) <= timestamp:
            continue
        items.append(_to_item(record, request, extraction))
        if len(items) >= limit:
            break
    return PendingList(
        generated_at=timestamp, total=len(items), degraded=degraded, items=tuple(items)
    )


def _locate(user_id: str, pending_key: str, *, now: datetime | None = None) -> _Located | None:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    since = timestamp - timedelta(hours=CONFIRM_TTL_HOURS)
    for record in action_repository.list_by_dedupe(user_id, pending_key, since):
        if not _is_pending_record(record):
            continue
        payload = _payload(record)
        if payload is None:
            continue
        request, extraction = payload
        if request.pending_key != pending_key:
            continue
        if record.status == "succeeded":
            return _Located(record, request, extraction, True)
        if record.status != "planned":
            continue
        session_id = record.session_id or ""
        if not session_id or not _pointer_is_live(session_id, record.id):
            continue
        if expire_if_due(session_id, now=timestamp):
            continue
        return _Located(record, request, extraction, False)
    return None


def _mark_schedule(record_id: str, status: str, timestamp: datetime) -> None:
    schedule = action_repository.get_schedule(record_id)
    if schedule is None or schedule.status != "scheduled":
        return
    schedule.status = status
    schedule.updated_at = timestamp
    action_repository.save_schedule(schedule)


def _resolve_amount(
    request: ConfirmationRequest, extraction: LedgerExtraction
) -> int:
    if request.amount_minor:
        return request.amount_minor
    if extraction.amount_value:
        try:
            return to_minor(extraction.amount_value)
        except LedgerAmountError as exc:
            raise PendingValidationError(str(exc)) from exc
    raise PendingValidationError("缺少可入账金额")


def confirm_pending(
    user_id: str,
    pending_key: str,
    *,
    category_name: str | None = None,
    direction: str | None = None,
    amount_minor: int | None = None,
    occurred_at: datetime | None = None,
    now: datetime | None = None,
) -> ConfirmOutcome:
    from app.services.ledger import service as ledger_service

    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    located = _locate(user_id, pending_key, now=timestamp)
    if located is None:
        raise PendingNotFoundError(pending_key)
    record = located.record
    request = located.request
    extraction = located.extraction
    final_direction = direction or extraction.direction or "expense"
    final_amount = amount_minor if amount_minor else _resolve_amount(request, extraction)
    if final_amount <= 0:
        raise PendingValidationError("缺少可入账金额")
    kind = "income" if final_direction == "income" else "expense"
    detected = _detected_payload(record)
    chosen = (
        category_name or detected.get("category_name") or extraction.category_hint or ""
    ).strip() or None
    target = category_service.normalize(user_id, chosen, kind=kind, now=timestamp)
    account_id = ledger_service.resolve_account_id(user_id)
    draft = LedgerEntryDraft(
        user_id=user_id,
        account_id=account_id,
        category_id=target.category_id,
        amount_minor=final_amount,
        direction=final_direction,
        occurred_at=occurred_at or extraction.occurred_at_resolved or timestamp,
        merchant=extraction.merchant_hint,
        note=str(detected.get("note") or "") or extraction.evidence_span,
        source="conversation",
        source_ref=request.source_ref or None,
        idempotency_key=pending_key,
    )
    if not located.consumed:
        clear_pending(record.session_id or "", status="completed")
    try:
        outcome = ledger_service.record_entry(
            draft, idempotency_key=pending_key, now=timestamp
        )
    except ValueError:
        if not located.consumed:
            clear_pending(record.session_id or "", status="pending")
        raise
    learned: str | None = None
    if not located.consumed:
        record.status = "succeeded"
        record.executed_at = timestamp
        record.updated_at = timestamp
        action_repository.save_record(record)
        _mark_schedule(record.id, "executed", timestamp)
        learned = _learn_alias(user_id, category_name, extraction, target)
    return ConfirmOutcome(
        entry_id=outcome.entry.id, created=outcome.created, learned_alias=learned
    )


def _learn_alias(
    user_id: str,
    category_name: str | None,
    extraction: LedgerExtraction,
    target,
) -> str | None:
    if not category_name:
        return None
    if category_name.strip() == (extraction.category_hint or "").strip():
        return None
    alias = (extraction.category_hint or extraction.merchant_hint or "").strip()
    if not alias or alias == target.category_name or not target.category_id:
        return None
    if category_service.add_alias(user_id, target.category_id, alias):
        return alias
    return None


def ignore_pending(
    user_id: str, pending_key: str, *, now: datetime | None = None
) -> str:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    located = _locate(user_id, pending_key, now=timestamp)
    if located is None or located.consumed:
        raise PendingNotFoundError(pending_key)
    record = located.record
    clear_pending(record.session_id or "", status="cancelled")
    record.status = "cancelled"
    record.updated_at = timestamp
    action_repository.save_record(record)
    _mark_schedule(record.id, "cancelled", timestamp)
    return pending_key


__all__ = [
    "PENDING_ACTION_TYPE",
    "PENDING_GATE_REASON",
    "PENDING_PREFIX",
    "ConfirmOutcome",
    "PendingItem",
    "PendingList",
    "PendingNotFoundError",
    "PendingValidationError",
    "clear_pending",
    "confirm_pending",
    "expire_if_due",
    "ignore_pending",
    "list_pending",
    "load_pending",
    "register_pending",
]
