"""channel_identities 单表数据访问（FEISHU-003）。"""

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core.db import ChannelIdentityRow, SessionLocal

logger = logging.getLogger(__name__)


def find(channel: str, external_id: str) -> ChannelIdentityRow | None:
    with SessionLocal() as session:
        row = (
            session.query(ChannelIdentityRow)
            .filter(
                ChannelIdentityRow.channel == channel,
                ChannelIdentityRow.external_id == external_id,
            )
            .first()
        )
        if row is None:
            return None
        session.expunge(row)
        return row


def get_or_create(
    channel: str,
    external_id: str,
    internal_user_id: str,
    session_id: str | None = None,
    *,
    union_id: str | None = None,
    tenant_key: str | None = None,
    display_name: str | None = None,
) -> tuple[ChannelIdentityRow, bool]:
    existing = find(channel, external_id)
    if existing is not None:
        return existing, False
    now = datetime.now()
    row = ChannelIdentityRow(
        channel=channel,
        external_id=external_id,
        internal_user_id=internal_user_id,
        session_id=session_id,
        external_union_id=union_id,
        external_tenant_key=tenant_key,
        display_name=display_name,
        status="active",
        created_at=now,
        updated_at=now,
    )
    try:
        with SessionLocal() as session:
            session.add(row)
            session.commit()
            session.expunge(row)
    except IntegrityError:
        existing = find(channel, external_id)
        if existing is None:
            raise
        return existing, False
    return row, True


def update_identity(
    channel: str,
    external_id: str,
    *,
    internal_user_id: str | None = None,
    session_id: str | None = None,
    display_name: str | None = None,
) -> ChannelIdentityRow | None:
    with SessionLocal() as session:
        row = (
            session.query(ChannelIdentityRow)
            .filter(
                ChannelIdentityRow.channel == channel,
                ChannelIdentityRow.external_id == external_id,
            )
            .first()
        )
        if row is None:
            return None
        if internal_user_id is not None:
            row.internal_user_id = internal_user_id
        if session_id is not None:
            row.session_id = session_id
        if display_name is not None:
            row.display_name = display_name
        row.updated_at = datetime.now()
        session.commit()
        session.expunge(row)
        return row


def list_by_internal_user(internal_user_id: str) -> list[ChannelIdentityRow]:
    with SessionLocal() as session:
        rows = (
            session.query(ChannelIdentityRow)
            .filter(ChannelIdentityRow.internal_user_id == internal_user_id)
            .order_by(
                ChannelIdentityRow.created_at.asc(),
                ChannelIdentityRow.channel.asc(),
            )
            .all()
        )
        for row in rows:
            session.expunge(row)
        return list(rows)
