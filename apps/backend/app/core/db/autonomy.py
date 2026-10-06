"""自主行为域模型：主动动作、动作执行与调度、后台任务、触发器、Outbox 与运行台账。"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, UtcDateTime


class ProactiveActionRow(Base):
    __tablename__ = "proactive_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False)
    goal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    intention: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    payload_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('send_message')",
            name="ck_proactive_actions_type",
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'delivered', 'acked',"
            " 'discarded', 'failed', 'expired')",
            name="ck_proactive_actions_status",
        ),
        CheckConstraint(
            "trigger_type IN ('conversation_inactivity', 'scheduled_followup')",
            name="ck_proactive_actions_trigger_type",
        ),
        Index("idx_proactive_actions_user_status", "user_id", "status"),
        Index("idx_proactive_actions_dedupe", "dedupe_key"),
    )


class ActionRecordRow(Base):
    __tablename__ = "action_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="conversation")
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    intent: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    goal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    gate_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    next_retry_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'planned', 'executing', 'succeeded', 'failed', 'cancelled')",
            name="ck_action_records_status",
        ),
        CheckConstraint(
            "source IN ('conversation', 'autonomy', 'cancel', 'plan', 'event_driven')",
            name="ck_action_records_source",
        ),
        Index("idx_action_records_user_status", "user_id", "status"),
        Index("idx_action_records_user_dedupe", "user_id", "dedupe_key"),
    )


class ActionScheduleRow(Base):
    __tablename__ = "action_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    action_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    when_type: Mapped[str] = mapped_column(String, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String, nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "when_type IN ('immediate', 'delay', 'cron')",
            name="ck_action_schedules_when_type",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'due', 'executed', 'cancelled')",
            name="ck_action_schedules_status",
        ),
        UniqueConstraint("action_id", name="uq_action_schedules_action"),
        Index(
            "idx_action_schedules_due",
            "status",
            "scheduled_at",
            "priority",
        ),
    )


class BackgroundJobRow(Base):
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_background_jobs_status",
        ),
        Index("idx_background_jobs_status_run_at", "status", "run_at"),
    )


class TriggerRegistryRow(Base):
    __tablename__ = "trigger_registry"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    trigger_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    due_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    cooldown_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('conversation_inactivity', 'scheduled_followup', 'action_due')",
            name="ck_trigger_registry_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'due', 'fired', 'done', 'cancelled')",
            name="ck_trigger_registry_status",
        ),
        Index("idx_trigger_registry_status_due_at", "status", "due_at"),
        Index("idx_trigger_registry_user_status", "user_id", "status"),
    )


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(
        String, nullable=False, default="action_result", server_default="action_result"
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'consumed', 'failed')",
            name="ck_outbox_events_status",
        ),
        Index("idx_outbox_events_status_next_retry", "status", "next_retry_at"),
    )


class LoopRunRow(Base):
    __tablename__ = "loop_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    run_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trigger_id: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="running", server_default="running"
    )
    current_step: Mapped[str | None] = mapped_column(String, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    llm_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('autonomy', 'chat', 'world_maintenance', 'world_simulation', "
            "'action_retry', 'action_schedule', 'outbox_consume', 'trigger_reconcile', "
            "'ledger_digest', 'ledger_alert')",
            name="ck_loop_runs_kind",
        ),
        CheckConstraint(
            "status IN ('running', 'done', 'aborted', 'degraded')",
            name="ck_loop_runs_status",
        ),
        Index("idx_loop_runs_status_started_at", "status", "started_at"),
        Index("idx_loop_runs_user_started_at", "user_id", "started_at"),
        Index("ix_loop_runs_session_id", "session_id"),
    )
