"""用户身份：按邮箱 find-or-create（token 是唯一身份源）。

默认用户概念已退役（2026-09-28）：不再有固定 owner id、不再启动播种。用户行一律由
登录链路按邮箱派生（`email-<sha256[:16]>`）或通道身份派生（`feishu:{open_id}`）。
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib

from app.repositories import user_repository


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


def get_user(user_id: str) -> UserContext | None:
    row = user_repository.get(user_id)
    if row is None:
        return None
    return _to_context(row)


def email_user_id(normalized_email: str) -> str:
    digest = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
    return f"email-{digest[:16]}"


def find_or_create_by_email(email: str, *, now: datetime | None = None) -> UserContext:
    normalized = email.strip().lower()
    row = user_repository.get_by_email(normalized)
    if row is not None:
        return _to_context(row)
    display_name = normalized.split("@", 1)[0]
    row = user_repository.create_with_email(
        email_user_id(normalized),
        normalized,
        display_name=display_name,
        now=now,
    )
    return _to_context(row)
