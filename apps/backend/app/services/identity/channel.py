"""通道身份映射服务：内部/外部身份双向翻译的唯一读写入口（FEISHU-003）。

`internal_user_id` 是雪花 ID（ADR-16），不再由 `{channel}:{external_id}` 派生；
通道身份首次出现时补建 `users` 行，使同一个人跨通道收敛到同一 `user_id`。
派生规则 `f"{channel}:{external_id}"` 仅保留给**会话**（`build_session_id`）。
服务只允许 import `app.channels.base` 契约（R2），不得 import `app.channels.<impl>`。
"""

from dataclasses import dataclass

from app.channels.base import RecipientRef
from app.repositories import channel_identity_repository
from app.services.identity import user_service


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    channel: str
    external_id: str
    internal_user_id: str
    session_id: str | None
    created: bool


def build_session_id(channel: str, external_id: str) -> str:
    _validate(channel, external_id)
    return f"{channel}:{external_id}"


def resolve(
    channel: str,
    external_id: str,
    *,
    union_id: str | None = None,
    tenant_key: str | None = None,
    display_name: str | None = None,
) -> ResolvedIdentity:
    _validate(channel, external_id)
    existing = channel_identity_repository.find(channel, external_id)
    if existing is not None:
        return _to_resolved(existing, created=False)
    user = user_service.create_user(display_name=display_name)
    row, created = channel_identity_repository.get_or_create(
        channel,
        external_id,
        user.user_id,
        build_session_id(channel, external_id),
        union_id=union_id,
        tenant_key=tenant_key,
        display_name=display_name,
    )
    return _to_resolved(row, created=created)


def resolve_recipient(internal_user_id: str, channel: str) -> RecipientRef | None:
    if not internal_user_id or not channel:
        return None
    rows = channel_identity_repository.list_by_internal_user(internal_user_id)
    for row in rows:
        if row.channel == channel:
            return RecipientRef(channel=row.channel, external_id=row.external_id)
    return None


def _to_resolved(row, *, created: bool) -> ResolvedIdentity:
    return ResolvedIdentity(
        channel=row.channel,
        external_id=row.external_id,
        internal_user_id=row.internal_user_id,
        session_id=row.session_id,
        created=created,
    )


def _validate(channel: str, external_id: str) -> None:
    if not channel or not channel.strip():
        raise ValueError("channel 不能为空")
    if not external_id or not external_id.strip():
        raise ValueError("external_id 不能为空")
