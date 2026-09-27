from dataclasses import dataclass
from datetime import datetime
import hashlib

from app.core.settings import get_settings
from app.repositories import user_repository


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    display_name: str | None
    status: str
    is_default: bool


def _to_context(row) -> UserContext:
    return UserContext(
        user_id=row.id,
        display_name=row.display_name,
        status=row.status,
        is_default=bool(row.is_default),
    )


def ensure_default_user(*, now: datetime | None = None) -> UserContext:
    default_user = get_settings().default_user
    row = user_repository.upsert_default(default_user, now=now)
    return _to_context(row)


def resolve_user(user_id: str | None, *, now: datetime | None = None) -> UserContext:
    if not user_id:
        return ensure_default_user(now=now)
    row = user_repository.get(user_id)
    if row is not None:
        return _to_context(row)
    return UserContext(
        user_id=user_id,
        display_name=None,
        status="active",
        is_default=user_id == get_settings().default_user,
    )


def get_user(user_id: str) -> UserContext | None:
    row = user_repository.get(user_id)
    if row is None:
        return None
    return _to_context(row)


def _email_user_id(normalized_email: str) -> str:
    digest = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
    return f"email-{digest[:16]}"


def find_or_create_by_email(email: str, *, now: datetime | None = None) -> UserContext:
    normalized = email.strip().lower()
    row = user_repository.get_by_email(normalized)
    if row is not None:
        return _to_context(row)
    display_name = normalized.split("@", 1)[0]
    row = user_repository.create_with_email(
        _email_user_id(normalized),
        normalized,
        display_name=display_name,
        now=now,
    )
    return _to_context(row)
