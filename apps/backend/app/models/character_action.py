"""Character Action Sync 域模型（ACTION-001）。

WorldAction 值对象 + 状态机 + 幂等键：三层之间的唯一契约。
纯数据与纯函数：零 IO、零数据库、零副作用。非法状态迁移返回 None。
"""

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from app.core import ids

ActionType = Literal["CREATE", "MOVE", "CONSUME"]

ACTION_TYPES: tuple[str, ...] = ("CREATE", "MOVE", "CONSUME")

Actor = Literal["character", "user", "autonomy"]

ACTORS: tuple[str, ...] = ("character", "user", "autonomy")

ActionSource = Literal["character_reply", "user_message", "autonomy", "manual"]

ACTION_SOURCES: tuple[str, ...] = ("character_reply", "user_message", "autonomy", "manual")


class WorldActionStatus(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"


TERMINAL_ACTION_STATUSES: tuple[str, ...] = (
    WorldActionStatus.REJECTED,
    WorldActionStatus.APPLIED,
    WorldActionStatus.FAILED,
    WorldActionStatus.SKIPPED,
)


class WorldActionReason(StrEnum):
    DISABLED = "DISABLED"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    NOT_CONSUMABLE = "NOT_CONSUMABLE"
    INSUFFICIENT_QUANTITY = "INSUFFICIENT_QUANTITY"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    LOCATION_UNRESOLVED = "LOCATION_UNRESOLVED"
    LOCATION_UNREACHABLE = "LOCATION_UNREACHABLE"
    DUPLICATE_ENTITY = "DUPLICATE_ENTITY"
    ENTITY_LIMIT = "ENTITY_LIMIT"
    NO_OP = "NO_OP"
    DUPLICATE = "DUPLICATE"
    WORLD_UNAVAILABLE = "WORLD_UNAVAILABLE"
    ENGINE_FAILED = "ENGINE_FAILED"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"


class ActionTransitionEvent(StrEnum):
    VALIDATE_PASS = "validate_pass"
    VALIDATE_REJECT = "validate_reject"
    SKIP = "skip"
    ENGINE_OK = "engine_ok"
    ENGINE_FAIL = "engine_fail"


_TRANSITIONS: dict[str, dict[str, str | None]] = {
    WorldActionStatus.CANDIDATE: {
        ActionTransitionEvent.VALIDATE_PASS: WorldActionStatus.VALIDATED,
        ActionTransitionEvent.VALIDATE_REJECT: WorldActionStatus.REJECTED,
        ActionTransitionEvent.SKIP: WorldActionStatus.SKIPPED,
    },
    WorldActionStatus.VALIDATED: {
        ActionTransitionEvent.ENGINE_OK: WorldActionStatus.APPLIED,
        ActionTransitionEvent.ENGINE_FAIL: WorldActionStatus.FAILED,
    },
    WorldActionStatus.REJECTED: {},
    WorldActionStatus.APPLIED: {},
    WorldActionStatus.FAILED: {},
    WorldActionStatus.SKIPPED: {},
}


def transition_world_action(
    status: WorldActionStatus,
    event: ActionTransitionEvent,
) -> WorldActionStatus | None:
    if status not in _TRANSITIONS:
        return None
    return _TRANSITIONS[status].get(event)


def _normalize_core_params(params: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key in sorted(params):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, float):
            text = str(int(value)) if value == int(value) else str(value)
        else:
            text = str(value).strip()
        if text:
            normalized[key] = " ".join(text.split())
    return normalized


def make_world_action_dedupe_key(
    action_type: str,
    core_params: dict[str, Any],
) -> str:
    normalized = _normalize_core_params(core_params)
    material = action_type + "|" + "|".join(
        f"{key}={normalized[key]}" for key in sorted(normalized)
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def make_action_id() -> str:
    return ids.new_id_str()


class TargetRef(BaseModel):
    name: str
    object_id: str | None = None
    category: str | None = None
    location_id: str | None = None
    location_from: str | None = None
    aliases_hint: list[str] = Field(default_factory=list)


class TurnRef(BaseModel):
    session_id: str
    turn_id: str
    ordinal: int = 0


class WorldAction(BaseModel):
    action_id: str = Field(default_factory=make_action_id)
    action_type: str
    actor: str = "character"
    target: TargetRef
    quantity: float | None = None
    source: str = "character_reply"
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: WorldActionStatus = WorldActionStatus.CANDIDATE
    dedupe_key: str = ""
    turn_ref: TurnRef
    created_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action_type not in ACTION_TYPES:
            raise ValueError(f"action_type must be one of {ACTION_TYPES}, got {self.action_type}")
        if not self.target.name or not self.target.name.strip():
            raise ValueError("target.name must be non-empty")
        if self.actor not in ACTORS:
            raise ValueError(f"actor must be one of {ACTORS}, got {self.actor}")
        if self.source not in ACTION_SOURCES:
            raise ValueError(f"source must be one of {ACTION_SOURCES}, got {self.source}")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        return self

    def transition(self, event: ActionTransitionEvent) -> WorldActionStatus | None:
        new_status = transition_world_action(self.status, event)
        if new_status is not None:
            self.status = new_status
        return new_status

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ACTION_STATUSES

    def snapshot(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "actor": self.actor,
            "target_name": self.target.name,
            "target_object_id": self.target.object_id,
            "quantity": self.quantity,
            "source": self.source,
            "status": self.status.value,
            "dedupe_key": self.dedupe_key,
            "evidence": self.metadata.get("evidence", ""),
            "confidence": self.metadata.get("confidence", ""),
        }


def build_dedupe_key(
    action_type: str,
    target_name: str,
    quantity: float | None,
    session_id: str,
    turn_id: str,
    ordinal: int,
) -> str:
    params: dict[str, Any] = {
        "target_name": target_name,
        "quantity": quantity,
        "session_id": session_id,
        "turn_id": turn_id,
        "ordinal": ordinal,
    }
    return make_world_action_dedupe_key(action_type, params)


class ExtractionResult(BaseModel):
    candidates: list[WorldAction] = Field(default_factory=list)
    channel: str = "lexicon"
    notes: list[str] = Field(default_factory=list)
    skipped_reason: str | None = None


class MutationOutcome(BaseModel):
    action_id: str
    status: str
    engine_fn: str | None = None
    engine_error: str | None = None
    object_id: str | None = None
    name: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    world_event_id: str | None = None
    title: str | None = None
