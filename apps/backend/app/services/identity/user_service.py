"""用户身份：凭据经 `channel_identities` 绑定到稳定 `user_id`（token 是唯一身份源）。

默认用户概念已退役（2026-09-28）：不再有固定 owner id、不再启动播种。
`user_id` 是雪花 ID（ADR-16），**不由凭据派生**；邮箱 / 通道 open_id 只作为
`channel_identities` 里的一行绑定，改绑凭据不改变 `user_id`。
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib

from app.core import ids
from app.repositories import channel_identity_repository, user_repository

EMAIL_CHANNEL = "email"


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    display_name: str | None
    status: str


def _to_context(row) -> UserContext:
    return UserContext(
        user_id=row.id,
        display_name=row.display_name,
        status=row.status,
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user(user_id: str) -> UserContext | None:
    row = user_repository.get(user_id)
    if row is None:
        return None
    return _to_context(row)


def create_user(
    *, display_name: str | None = None, now: datetime | None = None
) -> UserContext:
    row = user_repository.create(str(ids.new_id()), display_name=display_name, now=now)
    return _to_context(row)


def find_or_create_by_email(email: str, *, now: datetime | None = None) -> UserContext:
    normalized = normalize_email(email)
    binding = channel_identity_repository.find(EMAIL_CHANNEL, normalized)
    if binding is not None:
        existing = get_user(binding.internal_user_id)
        if existing is not None:
            return existing
    display_name = normalized.split("@", 1)[0]
    row = user_repository.create_with_email(
        str(ids.new_id()),
        normalized,
        display_name=display_name,
        now=now,
    )
    if binding is None:
        channel_identity_repository.get_or_create(
            EMAIL_CHANNEL,
            normalized,
            row.id,
            display_name=display_name,
        )
    else:
        channel_identity_repository.update_identity(
            EMAIL_CHANNEL,
            normalized,
            internal_user_id=row.id,
            display_name=display_name,
        )
    return _to_context(row)


def legacy_email_user_id(normalized_email: str) -> str:
    """历史口径（`email-<sha256[:16]>`），仅供旧库迁移脚本复现，不得用于新身份。"""
    digest = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
    return f"email-{digest[:16]}"
