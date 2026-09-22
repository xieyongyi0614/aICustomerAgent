from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

OWNER_CHARACTER = "character"
OWNER_USER = "user"

DEFAULT_CHARACTER_FALLBACK = "asuna"


@dataclass(frozen=True, slots=True)
class OwnerRef:
    owner_type: str
    owner_id: str
    is_legacy: bool


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str


def resolve_owner(
    row: Mapping[str, Any] | Any,
    *,
    character_id: str,
    user_id: str,
) -> OwnerRef:
    if isinstance(row, Mapping):
        raw_type = row.get("owner_type")
        raw_id = row.get("owner_id")
    else:
        raw_type = getattr(row, "owner_type", None)
        raw_id = getattr(row, "owner_id", None)

    is_legacy = raw_type is None or raw_type == ""
    if is_legacy or raw_type == OWNER_CHARACTER:
        owner_type = OWNER_CHARACTER
        owner_id = raw_id or character_id or DEFAULT_CHARACTER_FALLBACK
        return OwnerRef(
            owner_type=owner_type,
            owner_id=owner_id,
            is_legacy=is_legacy,
        )
    if raw_type == OWNER_USER:
        owner_id = raw_id or user_id
        return OwnerRef(owner_type=OWNER_USER, owner_id=owner_id, is_legacy=False)
    return OwnerRef(
        owner_type=OWNER_CHARACTER,
        owner_id=character_id or DEFAULT_CHARACTER_FALLBACK,
        is_legacy=True,
    )


def assert_access(
    owner: OwnerRef,
    *,
    user_id: str,
    character_id: str,
    mode: Literal["read", "write"] = "read",
) -> AccessDecision:
    if owner.owner_type == OWNER_USER:
        if owner.owner_id and user_id and owner.owner_id == user_id:
            return AccessDecision(allowed=True, reason="same_owner")
        return AccessDecision(allowed=False, reason="cross_user_denied")
    if owner.owner_type == OWNER_CHARACTER:
        if mode == "read":
            return AccessDecision(allowed=True, reason="character_world_readonly")
        return AccessDecision(allowed=False, reason="character_world_readonly")
    return AccessDecision(allowed=False, reason="unknown_owner_denied")


def scope_filter(owner: OwnerRef) -> dict[str, Any]:
    return {
        "owner_type": owner.owner_type,
        "owner_id": owner.owner_id,
    }
