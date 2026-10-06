"""0008：剩余全部域时间列统一 UTC-aware（timestamptz）—— 迁移收官批。

覆盖 car / character / goal / world / autonomy / action / planning / ledger /
reflection / relationship / runtime / observability / development 等全部剩余表。
- 朴素列存的是部署本地墙钟，按 `Asia/Shanghai` 解释为真实瞬间。
- `insights.invalidated_at` 历史为 `timestamptz`（旧错标，写入的是朴素本地墙钟），
  先按 UTC 取回墙钟、再按 `Asia/Shanghai` 重建正确瞬间。

至此全库时间列口径统一为 UTC-aware。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"

LOCAL_TZ = "Asia/Shanghai"

_NAIVE_COLUMNS = (
    ("action_records", "created_at"),
    ("action_records", "executed_at"),
    ("action_records", "next_retry_at"),
    ("action_records", "scheduled_at"),
    ("action_records", "updated_at"),
    ("action_schedules", "created_at"),
    ("action_schedules", "scheduled_at"),
    ("action_schedules", "updated_at"),
    ("agent_metric_snapshots", "created_at"),
    ("agent_metric_snapshots", "window_end"),
    ("agent_metric_snapshots", "window_start"),
    ("agent_state_snapshots", "created_at"),
    ("background_jobs", "created_at"),
    ("background_jobs", "run_at"),
    ("car_loans", "created_at"),
    ("car_loans", "next_due_at"),
    ("car_loans", "settled_at"),
    ("car_loans", "updated_at"),
    ("car_mileage_logs", "created_at"),
    ("car_mileage_logs", "recorded_at"),
    ("car_mileage_logs", "updated_at"),
    ("car_profiles", "created_at"),
    ("car_profiles", "inspection_due_at"),
    ("car_profiles", "insurance_due_at"),
    ("car_profiles", "purchased_at"),
    ("car_profiles", "updated_at"),
    ("car_service_records", "created_at"),
    ("car_service_records", "next_due_at"),
    ("car_service_records", "occurred_at"),
    ("car_service_records", "updated_at"),
    ("character_goals", "created_at"),
    ("character_goals", "updated_at"),
    ("character_state", "created_at"),
    ("character_state", "last_event_at"),
    ("character_state", "updated_at"),
    ("daily_plans", "created_at"),
    ("daily_plans", "updated_at"),
    ("decision_records", "created_at"),
    ("development_changes", "created_at"),
    ("development_state", "created_at"),
    ("development_state", "updated_at"),
    ("emotion_history", "created_at"),
    ("evaluation_reports", "created_at"),
    ("evidence_links", "created_at"),
    ("goal_plans", "created_at"),
    ("goal_plans", "updated_at"),
    ("insights", "created_at"),
    ("insights", "updated_at"),
    ("ledger_accounts", "created_at"),
    ("ledger_accounts", "updated_at"),
    ("ledger_categories", "created_at"),
    ("ledger_categories", "updated_at"),
    ("ledger_entries", "created_at"),
    ("ledger_entries", "occurred_at"),
    ("life_tasks", "completed_at"),
    ("life_tasks", "created_at"),
    ("life_tasks", "remind_at"),
    ("life_tasks", "updated_at"),
    ("llm_call_records", "created_at"),
    ("llm_call_records", "started_at"),
    ("loop_runs", "created_at"),
    ("loop_runs", "finished_at"),
    ("loop_runs", "started_at"),
    ("outbox_events", "created_at"),
    ("outbox_events", "next_retry_at"),
    ("outbox_events", "updated_at"),
    ("personality_state", "created_at"),
    ("personality_state", "updated_at"),
    ("proactive_actions", "acked_at"),
    ("proactive_actions", "created_at"),
    ("proactive_actions", "delivered_at"),
    ("proactive_actions", "next_retry_at"),
    ("proactive_actions", "updated_at"),
    ("prompt_snapshots", "created_at"),
    ("reflection_runs", "created_at"),
    ("reflection_runs", "updated_at"),
    ("relationship_conflicts", "created_at"),
    ("relationship_conflicts", "last_negative_at"),
    ("relationship_conflicts", "recovery_started_at"),
    ("relationship_conflicts", "resolved_at"),
    ("relationship_conflicts", "started_at"),
    ("relationship_events", "created_at"),
    ("relationship_milestones", "created_at"),
    ("relationship_snapshots", "created_at"),
    ("relationship_state", "created_at"),
    ("relationship_state", "last_interaction_at"),
    ("relationship_state", "updated_at"),
    ("runtime_traces", "created_at"),
    ("runtime_traces", "started_at"),
    ("trigger_registry", "cooldown_until"),
    ("trigger_registry", "created_at"),
    ("trigger_registry", "due_at"),
    ("trigger_registry", "updated_at"),
    ("user_situations", "detected_at"),
    ("user_situations", "updated_at"),
    ("user_situations", "valid_until"),
    ("world_entities", "created_at"),
    ("world_entities", "last_action_at"),
    ("world_entities", "updated_at"),
    ("world_events", "completed_at"),
    ("world_events", "created_at"),
    ("world_events", "due_at"),
    ("world_events", "started_at"),
    ("world_events", "updated_at"),
    ("world_snapshots", "created_at"),
    ("worlds", "created_at"),
    ("worlds", "sim_last_advanced_at"),
    ("worlds", "sim_time"),
    ("worlds", "updated_at"),
)

_MISLABELED_COLUMNS = (
    ("insights", "invalidated_at"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _NAIVE_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING ({column} AT TIME ZONE '{LOCAL_TZ}')"
        )
    for table, column in _MISLABELED_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING ({column} AT TIME ZONE 'UTC' AT TIME ZONE '{LOCAL_TZ}')"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _MISLABELED_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING ({column} AT TIME ZONE '{LOCAL_TZ}' AT TIME ZONE 'UTC')"
        )
    for table, column in _NAIVE_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamp "
            f"USING ({column} AT TIME ZONE '{LOCAL_TZ}')"
        )
