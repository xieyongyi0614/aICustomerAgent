"""通道身份映射服务：内部/外部身份双向翻译的唯一读写入口（FEISHU-003）。

派生规则 `f"{channel}:{external_id}"` 通道无关，冻结在此（不在渠道侧）；
服务只允许 import `app.channels.base` 契约（R2），不得 import `app.channels.<impl>`。
"""

from dataclasses import dataclass

from app.channels.base import RecipientRef
from app.repositories import channel_identity_repository


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    channel: str
    external_id: str
    internal_user_id: str
    session_id: str
    created: bool


def build_internal_user_id(channel: str, external_id: str) -> str:
    _validate(channel, external_id)
    return f"{channel}:{external_id}"


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
    internal_user_id = build_internal_user_id(channel, external_id)
    session_id = build_session_id(channel, external_id)
    row, created = channel_identity_repository.get_or_create(
        channel,
        external_id,
        internal_user_id,
        session_id,
        union_id=union_id,
        tenant_key=tenant_key,
        display_name=display_name,
    )
    return ResolvedIdentity(
        channel=row.channel,
        external_id=row.external_id,
        internal_user_id=row.internal_user_id,
        session_id=row.session_id,
        created=created,
    )


def resolve_recipient(internal_user_id: str, channel: str) -> RecipientRef | None:
    if not internal_user_id or not channel:
        return None
    rows = channel_identity_repository.list_by_internal_user(internal_user_id)
    for row in rows:
        if row.channel == channel:
            return RecipientRef(channel=row.channel, external_id=row.external_id)
    return None


def _validate(channel: str, external_id: str) -> None:
    if not channel or not channel.strip():
        raise ValueError("channel 不能为空")
    if not external_id or not external_id.strip():
        raise ValueError("external_id 不能为空")
