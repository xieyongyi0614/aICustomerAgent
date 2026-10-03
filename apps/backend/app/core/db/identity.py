"""身份与通道域模型：用户、通道绑定、飞书去重/投递台账与简报偏好。"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_users_status",
        ),
        Index(
            "ux_users_email",
            "email",
            unique=True,
            sqlite_where=text("email IS NOT NULL"),
            postgresql_where=text("email IS NOT NULL"),
        ),
    )


class ChannelIdentityRow(Base):
    __tablename__ = "channel_identities"

    channel: Mapped[str] = mapped_column(String, nullable=False, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False, primary_key=True)
    internal_user_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_union_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_tenant_key: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("channel", "external_id"),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_channel_identities_status",
        ),
        Index("idx_channel_identities_user", "internal_user_id"),
    )


class FeishuDedupeLedgerRow(Base):
    __tablename__ = "feishu_dedupe_ledger"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("idx_feishu_dedupe_ledger_received_at", "received_at"),)


class FeishuDeliveryRow(Base):
    __tablename__ = "feishu_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("idx_feishu_deliveries_delivered_at", "delivered_at"),)


class BriefingPreferenceRow(Base):
    __tablename__ = "briefing_preferences"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    morning_at: Mapped[str | None] = mapped_column(String, nullable=True)
    evening_at: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
