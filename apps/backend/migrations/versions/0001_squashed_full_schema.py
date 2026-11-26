"""0001~0058 迁移链折叠为单迁移：全量 Schema 基线（2026-09-29）。

Revision ID: 0001
Revises:
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import types as sa_types


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None


class VectorType(sa_types.UserDefinedType):
    """pgvector VECTOR(768) 列类型的迁移本地副本（与 app.core.db.VectorType 同构，
    独立于 app 代码演进，避免基线迁移被应用层重构破坏）。"""

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "VECTOR(768)"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        available = bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar()
        if available is None:
            raise RuntimeError(
                "pgvector 扩展不可用：请使用 pgvector/pgvector 镜像或在 PostgreSQL "
                "安装 vector 扩展后重试（Memory 2.0 生产仅支持启用 pgvector 的 PostgreSQL）。"
            )
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.create_table('action_records',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=True),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('action_type', sa.String(), nullable=False),
    sa.Column('intent', sa.JSON(), nullable=False),
    sa.Column('goal_id', sa.String(), nullable=True),
    sa.Column('target_record_id', sa.String(), nullable=True),
    sa.Column('dedupe_key', sa.String(), nullable=False),
    sa.Column('params', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('gate_reason', sa.String(), nullable=True),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('next_retry_at', sa.DateTime(), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('executed_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("source IN ('conversation', 'autonomy', 'cancel', 'plan', 'event_driven')", name='ck_action_records_source'),
    sa.CheckConstraint("status IN ('created', 'planned', 'executing', 'succeeded', 'failed', 'cancelled')", name='ck_action_records_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_action_records_user_dedupe', 'action_records', ['user_id', 'dedupe_key'], unique=False)
    op.create_index('idx_action_records_user_status', 'action_records', ['user_id', 'status'], unique=False)
    op.create_index(op.f('ix_action_records_run_id'), 'action_records', ['run_id'], unique=False)
    op.create_index(op.f('ix_action_records_user_id'), 'action_records', ['user_id'], unique=False)
    op.create_table('action_schedules',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('action_id', sa.String(), nullable=False),
    sa.Column('when_type', sa.String(), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('scheduled', 'due', 'executed', 'cancelled')", name='ck_action_schedules_status'),
    sa.CheckConstraint("when_type IN ('immediate', 'delay', 'cron')", name='ck_action_schedules_when_type'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('action_id', name='uq_action_schedules_action')
    )
    op.create_index('idx_action_schedules_due', 'action_schedules', ['status', 'scheduled_at', 'priority'], unique=False)
    op.create_index(op.f('ix_action_schedules_action_id'), 'action_schedules', ['action_id'], unique=True)
    op.create_table('agent_metric_snapshots',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), nullable=False),
    sa.Column('window_start', sa.DateTime(), nullable=False),
    sa.Column('window_end', sa.DateTime(), nullable=False),
    sa.Column('metrics', sa.JSON(), nullable=False),
    sa.Column('trend', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'character_id', 'window_start', name='uq_agent_metric_window')
    )
    op.create_table('agent_state_snapshots',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_agent_state_snapshots_user_created', 'agent_state_snapshots', ['user_id', 'created_at'], unique=False)
    op.create_table('background_jobs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('job_type', sa.String(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('run_at', sa.DateTime(), nullable=True),
    sa.Column('idempotency_key', sa.String(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'done', 'failed')", name='ck_background_jobs_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('idx_background_jobs_status_run_at', 'background_jobs', ['status', 'run_at'], unique=False)
    op.create_table('channel_identities',
    sa.Column('channel', sa.String(), nullable=False),
    sa.Column('external_id', sa.String(), nullable=False),
    sa.Column('internal_user_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('external_union_id', sa.String(), nullable=True),
    sa.Column('external_tenant_key', sa.String(), nullable=True),
    sa.Column('display_name', sa.String(), nullable=True),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('active', 'inactive')", name='ck_channel_identities_status'),
    sa.PrimaryKeyConstraint('channel', 'external_id')
    )
    op.create_index('idx_channel_identities_user', 'channel_identities', ['internal_user_id'], unique=False)
    op.create_table('character_goals',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('horizon', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('created_turn', sa.Integer(), nullable=False),
    sa.Column('expires_at_turn', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('parent_goal_id', sa.String(), nullable=True),
    sa.Column('layer', sa.String(), nullable=True),
    sa.Column('domain', sa.String(), nullable=True),
    sa.Column('origin', sa.String(), nullable=True),
    sa.Column('failure_reason', sa.String(), nullable=True),
    sa.Column('arbitration_state', sa.JSON(), nullable=True),
    sa.CheckConstraint("domain IN ('personal', 'relationship', 'world', 'budget') OR domain IS NULL", name='ck_character_goals_domain'),
    sa.CheckConstraint("horizon IN ('persistent', 'current')", name='ck_character_goals_horizon'),
    sa.CheckConstraint("layer IN ('short_term', 'medium', 'long_term') OR layer IS NULL", name='ck_character_goals_layer'),
    sa.CheckConstraint("source IN ('definition', 'policy', 'scene')", name='ck_character_goals_source'),
    sa.CheckConstraint("status IN ('active', 'completed', 'expired', 'cancelled', 'failed', 'suspended', 'abandoned')", name='ck_character_goals_status'),
    sa.CheckConstraint("type IN ('user_care', 'relationship', 'conversation', 'scene')", name='ck_character_goals_type'),
    sa.CheckConstraint('priority BETWEEN 1 AND 5', name='ck_character_goals_priority'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_character_goals_layer_domain', 'character_goals', ['layer', 'domain'], unique=False)
    op.create_index('idx_character_goals_parent', 'character_goals', ['parent_goal_id'], unique=False)
    op.create_index('idx_character_goals_user_status', 'character_goals', ['user_id', 'status'], unique=False)
    op.create_table('character_state',
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('mood', sa.String(), nullable=False),
    sa.Column('energy', sa.Float(), nullable=False),
    sa.Column('current_topic', sa.String(), nullable=False),
    sa.Column('inner_state', sa.Text(), nullable=False),
    sa.Column('intensity', sa.Float(), server_default='0.3', nullable=False),
    sa.Column('cause', sa.String(), server_default='', nullable=False),
    sa.Column('last_event_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("mood IN ('happy', 'calm', 'worried', 'sad', 'shy', 'excited', 'tired', 'angry')", name='ck_character_state_mood'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('conversations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('mode', sa.String(length=16), server_default='default', nullable=False),
    sa.Column('mode_entered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("mode IN ('professional', 'default', 'immersive')", name='ck_conversations_mode'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('daily_plans',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('plan_date', sa.Date(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('part_of_day', sa.String(), nullable=False),
    sa.Column('start_minutes', sa.Integer(), nullable=False),
    sa.Column('end_minutes', sa.Integer(), nullable=False),
    sa.Column('activity', sa.String(length=50), nullable=False),
    sa.Column('location_id', sa.String(length=50), nullable=False),
    sa.Column('variability_source', sa.String(), server_default='fixed', nullable=False),
    sa.Column('status', sa.String(), server_default='planned', nullable=False),
    sa.Column('routine_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("part_of_day IN ('morning', 'afternoon', 'dusk', 'evening', 'late_night')", name='ck_daily_plans_part_of_day'),
    sa.CheckConstraint("status IN ('planned', 'active', 'completed', 'skipped', 'superseded')", name='ck_daily_plans_status'),
    sa.CheckConstraint("variability_source IN ('fixed', 'variant', 'user_influenced')", name='ck_daily_plans_variability'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_daily_plans_lookup', 'daily_plans', ['user_id', 'plan_date', 'status'], unique=False)
    op.create_index('uq_daily_plans_user_date_seq', 'daily_plans', ['user_id', 'plan_date', 'seq'], unique=True, sqlite_where=sa.text("status IN ('planned', 'active')"), postgresql_where=sa.text("status IN ('planned', 'active')"))
    op.create_table('decision_records',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('request_id', sa.String(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('action_id', sa.String(), nullable=True),
    sa.Column('trigger', sa.String(), nullable=True),
    sa.Column('input_snapshot', sa.JSON(), nullable=False),
    sa.Column('decision', sa.String(), nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('outcome', sa.String(), nullable=True),
    sa.Column('candidates', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('proactive_autonomy', 'turn_goal', 'turn_intention', 'turn_behavior', 'goal_lifecycle')", name='ck_decision_records_kind'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_decision_records_action', 'decision_records', ['action_id'], unique=False)
    op.create_index('idx_decision_records_user_time', 'decision_records', ['user_id', 'kind', 'created_at'], unique=False)
    op.create_table('development_changes',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('development_state_id', sa.String(), nullable=True),
    sa.Column('personality_state_id', sa.String(), nullable=True),
    sa.Column('before', sa.JSON(), nullable=True),
    sa.Column('after', sa.JSON(), nullable=True),
    sa.Column('insight_id', sa.String(), nullable=False),
    sa.Column('reason', sa.String(), server_default='compiled', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("reason IN ('compiled', 'arbitrated', 'arbitrated_lost', 'rolled_back', 'retired', 'replayed', 'personality')", name='ck_development_changes_reason'),
    sa.CheckConstraint("development_state_id IS NOT NULL OR personality_state_id IS NOT NULL", name='ck_development_changes_subject'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_development_changes_insight', 'development_changes', ['insight_id'], unique=False)
    op.create_index('idx_development_changes_state', 'development_changes', ['development_state_id'], unique=False)
    op.create_table('development_state',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('strength', sa.Float(), nullable=False),
    sa.Column('source_insight_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('belief', 'preference', 'pattern')", name='ck_development_state_kind'),
    sa.CheckConstraint("status IN ('active', 'superseded', 'retired')", name='ck_development_state_status'),
    sa.CheckConstraint('strength >= 0 AND strength <= 1', name='ck_development_state_strength'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_development_state_user_kind', 'development_state', ['user_id', 'kind', 'status'], unique=False)
    op.create_index('idx_development_state_user_status', 'development_state', ['user_id', 'status'], unique=False)
    op.create_index('uq_development_state_active_key', 'development_state', ['user_id', 'key'], unique=True, sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.create_table('emotion_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('user_emotion', sa.String(), nullable=False),
    sa.Column('event', sa.String(), nullable=False),
    sa.Column('behavior', sa.String(), nullable=False),
    sa.Column('mood_before', sa.String(), nullable=False),
    sa.Column('mood_after', sa.String(), nullable=False),
    sa.Column('energy_after', sa.Float(), nullable=False),
    sa.Column('stage_after', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_emotion_history_user', 'emotion_history', ['user_id', 'created_at'], unique=False)
    op.create_table('evaluation_reports',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('subject', sa.String(), nullable=False),
    sa.Column('subject_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('overall_score', sa.Float(), nullable=True),
    sa.Column('verdict', sa.String(), nullable=False),
    sa.Column('scores', sa.JSON(), nullable=False),
    sa.Column('issues', sa.JSON(), nullable=False),
    sa.Column('context_digest', sa.JSON(), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("subject IN ('turn', 'proactive_action', 'offline_batch')", name='ck_evaluation_reports_subject'),
    sa.CheckConstraint("verdict IN ('pass', 'warn', 'fail')", name='ck_evaluation_reports_verdict'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_evaluation_subject', 'evaluation_reports', ['subject', 'subject_id'], unique=False)
    op.create_index('idx_evaluation_user_time', 'evaluation_reports', ['user_id', 'created_at'], unique=False)
    op.create_table('evidence_links',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('insight_id', sa.String(), nullable=False),
    sa.Column('memory_id', sa.String(), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('insight_id', 'memory_id', name='uq_evidence_links_insight_memory')
    )
    op.create_index('idx_evidence_links_memory', 'evidence_links', ['memory_id'], unique=False)
    op.create_table('feishu_dedupe_ledger',
    sa.Column('event_id', sa.String(), nullable=False),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('event_id')
    )
    op.create_index('idx_feishu_dedupe_ledger_received_at', 'feishu_dedupe_ledger', ['received_at'], unique=False)
    op.create_table('feishu_deliveries',
    sa.Column('idempotency_key', sa.String(), nullable=False),
    sa.Column('delivered_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('idempotency_key')
    )
    op.create_index('idx_feishu_deliveries_delivered_at', 'feishu_deliveries', ['delivered_at'], unique=False)
    op.create_table('goal_plans',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('goal_id', sa.String(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), server_default='draft', nullable=False),
    sa.Column('sub_goals', sa.JSON(), nullable=False),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'validated', 'active', 'rejected', 'superseded')", name='ck_goal_plans_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('goal_id', 'version', name='uq_goal_plans_goal_version')
    )
    op.create_index('idx_goal_plans_goal_status', 'goal_plans', ['goal_id', 'status'], unique=False)
    op.create_table('insights',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('scope', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('invalidated_reason', sa.Text(), nullable=True),
    sa.Column('superseded_by', sa.String(), nullable=True),
    sa.CheckConstraint("scope IN ('user', 'relationship', 'world')", name='ck_insights_scope'),
    sa.CheckConstraint("status != 'invalidated' OR invalidated_reason IS NOT NULL", name='ck_insights_invalidated_reason'),
    sa.CheckConstraint("status IN ('active', 'superseded', 'invalidated')", name='ck_insights_status'),
    sa.CheckConstraint("type IN ('belief', 'preference', 'pattern', 'capability_note', 'usage_preference', 'interaction_calibration')", name='ck_insights_type'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_insights_user_scope_status', 'insights', ['user_id', 'scope', 'status'], unique=False)
    op.create_index('idx_insights_user_status', 'insights', ['user_id', 'status'], unique=False)
    op.create_table('ledger_accounts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='CNY', nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('active', 'archived')", name='ck_ledger_accounts_status'),
    sa.CheckConstraint("type IN ('cash', 'bank', 'ewallet', 'credit', 'other')", name='ck_ledger_accounts_type'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_ledger_accounts_user_name')
    )
    op.create_index('ix_ledger_accounts_user', 'ledger_accounts', ['user_id', 'status'], unique=False)
    op.create_table('ledger_categories',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('parent_id', sa.String(), nullable=True),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('aliases', sa.JSON(), nullable=True),
    sa.Column('is_seed', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('expense', 'income')", name='ck_ledger_categories_kind'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'parent_id', 'name', name='uq_ledger_categories_user_parent_name')
    )
    op.create_index('ix_ledger_categories_user', 'ledger_categories', ['user_id', 'kind'], unique=False)
    op.create_table('life_tasks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), server_default='task', nullable=False),
    sa.Column('status', sa.String(), server_default='open', nullable=False),
    sa.Column('tag', sa.String(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('order_reason', sa.String(), nullable=True),
    sa.Column('remind_at', sa.DateTime(), nullable=True),
    sa.Column('due_date', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("kind IN ('task', 'memo')", name='ck_life_tasks_kind'),
    sa.CheckConstraint("status IN ('open', 'done', 'cancelled')", name='ck_life_tasks_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_life_tasks_user_remind', 'life_tasks', ['user_id', 'remind_at'], unique=False)
    op.create_index('ix_life_tasks_user_status', 'life_tasks', ['user_id', 'status'], unique=False)
    op.create_table('llm_call_records',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('request_id', sa.String(), nullable=True),
    sa.Column('turn_id', sa.String(), nullable=True),
    sa.Column('call_site', sa.String(), nullable=False),
    sa.Column('profile_id', sa.String(), nullable=True),
    sa.Column('model', sa.String(), nullable=True),
    sa.Column('provider', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('latency_ms', sa.Float(), nullable=False),
    sa.Column('ttft_ms', sa.Float(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('cost_estimate', sa.Float(), nullable=True),
    sa.Column('error_kind', sa.String(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('ok', 'error')", name='ck_llm_call_records_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_llm_calls_request', 'llm_call_records', ['request_id'], unique=False)
    op.create_index('idx_llm_calls_time', 'llm_call_records', ['created_at'], unique=False)
    op.create_index('idx_llm_calls_turn', 'llm_call_records', ['turn_id'], unique=False)
    op.create_table('loop_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('run_kind', sa.String(), nullable=True),
    sa.Column('profile', sa.JSON(), nullable=True),
    sa.Column('trigger_id', sa.String(), nullable=True),
    sa.Column('trigger_type', sa.String(), nullable=True),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), server_default='running', nullable=False),
    sa.Column('current_step', sa.String(), nullable=True),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('llm_call_count', sa.Integer(), nullable=False),
    sa.Column('token_total', sa.Integer(), nullable=False),
    sa.Column('budget_state', sa.JSON(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('autonomy', 'chat', 'world_maintenance', 'world_simulation', 'action_retry', 'action_schedule', 'outbox_consume', 'trigger_reconcile', 'ledger_digest', 'ledger_alert')", name='ck_loop_runs_kind'),
    sa.CheckConstraint("status IN ('running', 'done', 'aborted', 'degraded')", name='ck_loop_runs_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_loop_runs_status_started_at', 'loop_runs', ['status', 'started_at'], unique=False)
    op.create_index('idx_loop_runs_user_started_at', 'loop_runs', ['user_id', 'started_at'], unique=False)
    op.create_index('ix_loop_runs_session_id', 'loop_runs', ['session_id'], unique=False)
    op.create_table('memories',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('importance', sa.Float(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='*', nullable=False),
    sa.Column('confidence', sa.Float(), server_default='0', nullable=False),
    sa.Column('source', sa.String(), server_default='ai_inferred', nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('superseded_by', sa.String(), nullable=True),
    sa.Column('last_accessed_at', sa.DateTime(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('embedding', VectorType(), nullable=True),
    sa.Column('salience', sa.Float(), nullable=True),
    sa.Column('last_reinforced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_decayed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('forgotten_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('merge_chain', sa.JSON(), nullable=True),
    sa.Column('source_ref', sa.JSON(), nullable=True),
    sa.Column('visibility', sa.String(), nullable=True),
    sa.CheckConstraint("type IN ('user_preference', 'user_fact', 'important_event', 'relationship_event', 'experience', 'relationship_fact', 'commitment', 'milestone_event', 'behavior_pattern')", name='ck_memories_type'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_memories_user', 'memories', ['user_id'], unique=False)
    op.create_index('idx_memories_user_character_status', 'memories', ['user_id', 'character_id', 'status'], unique=False)
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "CREATE INDEX idx_memories_embedding_hnsw ON memories USING hnsw "
                "(embedding vector_cosine_ops)"
            )
        )
    op.create_table('memory_candidates',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='*', nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('proposed_type', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('source_ref', sa.JSON(), nullable=True),
    sa.Column('source_table', sa.String(), nullable=True),
    sa.Column('source_id', sa.String(), nullable=True),
    sa.Column('salience', sa.Float(), nullable=True),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('visibility', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'promoted')", name='ck_memory_candidates_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_table', 'source_id', name='uq_memory_candidates_source')
    )
    op.create_index('idx_memory_candidates_user_status', 'memory_candidates', ['user_id', 'status'], unique=False)
    op.create_table('memory_links',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('memory_id', sa.String(), nullable=False),
    sa.Column('related_memory_id', sa.String(), nullable=False),
    sa.Column('relation', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("relation IN ('supersedes', 'merges', 'contradicts')", name='ck_memory_links_relation'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_memory_links_memory', 'memory_links', ['memory_id'], unique=False)
    op.create_table('outbox_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('event_type', sa.String(), server_default='action_result', nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('idempotency_key', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_retry_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'consumed', 'failed')", name='ck_outbox_events_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('idx_outbox_events_status_next_retry', 'outbox_events', ['status', 'next_retry_at'], unique=False)
    op.create_table('personality_state',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), nullable=False),
    sa.Column('axis', sa.String(), nullable=False),
    sa.Column('baseline', sa.Float(), nullable=False),
    sa.Column('current', sa.Float(), nullable=False),
    sa.Column('bound_min', sa.Float(), nullable=False),
    sa.Column('bound_max', sa.Float(), nullable=False),
    sa.Column('source_insight_id', sa.String(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'character_id', 'axis', name='uq_personality_state_axis')
    )
    op.create_table('proactive_actions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('trigger_type', sa.String(), nullable=False),
    sa.Column('dedupe_key', sa.String(), nullable=False),
    sa.Column('goal_id', sa.String(), nullable=True),
    sa.Column('intention', sa.String(), nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('payload_text', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('next_retry_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('delivered_at', sa.DateTime(), nullable=True),
    sa.Column('message_id', sa.String(), nullable=True),
    sa.Column('external_message_id', sa.String(), nullable=True),
    sa.Column('acked_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("status IN ('candidate', 'approved', 'delivered', 'acked', 'discarded', 'failed', 'expired')", name='ck_proactive_actions_status'),
    sa.CheckConstraint("trigger_type IN ('conversation_inactivity', 'scheduled_followup')", name='ck_proactive_actions_trigger_type'),
    sa.CheckConstraint("type IN ('send_message')", name='ck_proactive_actions_type'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_proactive_actions_dedupe', 'proactive_actions', ['dedupe_key'], unique=False)
    op.create_index('idx_proactive_actions_user_status', 'proactive_actions', ['user_id', 'status'], unique=False)
    op.create_table('prompt_snapshots',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('request_id', sa.String(), nullable=False),
    sa.Column('turn_id', sa.String(), nullable=True),
    sa.Column('call_site', sa.String(), nullable=False),
    sa.Column('profile_id', sa.String(), nullable=True),
    sa.Column('model', sa.String(), nullable=True),
    sa.Column('messages', sa.JSON(), nullable=False),
    sa.Column('section_budget', sa.JSON(), nullable=True),
    sa.Column('truncated', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_prompt_snapshots_request', 'prompt_snapshots', ['request_id'], unique=False)
    op.create_index('idx_prompt_snapshots_time', 'prompt_snapshots', ['created_at'], unique=False)
    op.create_index('idx_prompt_snapshots_turn', 'prompt_snapshots', ['turn_id'], unique=False)
    op.create_table('reflection_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('trigger', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='queued', nullable=False),
    sa.Column('evidence_summary', sa.JSON(), nullable=True),
    sa.Column('outcome', sa.String(), nullable=True),
    sa.Column('llm_used', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('insight_ids', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'skipped', 'failed')", name='ck_reflection_runs_status'),
    sa.CheckConstraint("trigger IN ('scheduled', 'event')", name='ck_reflection_runs_trigger'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_reflection_runs_status_created', 'reflection_runs', ['status', 'created_at'], unique=False)
    op.create_index('idx_reflection_runs_user_status', 'reflection_runs', ['user_id', 'status'], unique=False)
    op.create_table('relationship_conflicts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('trigger_event_id', sa.String(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('last_negative_at', sa.DateTime(), nullable=True),
    sa.Column('recovery_started_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolution', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('strain', 'conflict', 'cold', 'recovery', 'resolved')", name='ck_relationship_conflicts_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_relationship_conflicts_user_status', 'relationship_conflicts', ['user_id', 'status'], unique=False)
    op.create_table('relationship_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('magnitude', sa.String(), nullable=False),
    sa.Column('impact_intimacy', sa.Float(), nullable=False),
    sa.Column('impact_trust', sa.Float(), nullable=False),
    sa.Column('impact_familiarity', sa.Float(), nullable=False),
    sa.Column('impact_respect', sa.Float(), server_default='0', nullable=False),
    sa.Column('impact_comfort', sa.Float(), server_default='0', nullable=False),
    sa.Column('impact_tension', sa.Float(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('source', sa.String(), server_default='conversation', nullable=False),
    sa.Column('cause', sa.String(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("magnitude IN ('weak', 'normal', 'strong')", name='ck_relationship_events_magnitude'),
    sa.CheckConstraint("source IN ('conversation', 'memory_replay', 'system')", name='ck_relationship_events_source'),
    sa.CheckConstraint("type IN ('user_care', 'user_help', 'intimate_moment', 'long_interaction', 'praise', 'warm_moment', 'criticized', 'conflict', 'boundary_violation', 'promise_kept', 'promise_broken', 'none')", name='ck_relationship_events_type'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_relationship_events_user', 'relationship_events', ['user_id', 'created_at'], unique=False)
    op.create_table('relationship_milestones',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), nullable=False),
    sa.Column('milestone_key', sa.String(), nullable=False),
    sa.Column('period_key', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('applied_bonus', sa.JSON(), nullable=False),
    sa.Column('unlocks', sa.JSON(), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'milestone_key', 'period_key', name='uq_relationship_milestones_user_key_period')
    )
    op.create_index('idx_relationship_milestones_user', 'relationship_milestones', ['user_id', 'created_at'], unique=False)
    op.create_table('relationship_snapshots',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('dimensions', sa.JSON(), nullable=False),
    sa.Column('stage', sa.String(), nullable=False),
    sa.Column('conflict_status', sa.String(), server_default='none', nullable=False),
    sa.Column('trigger', sa.String(), server_default='manual', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("conflict_status IN ('none', 'strain', 'conflict', 'cold', 'recovery', 'resolved')", name='ck_relationship_snapshots_conflict_status'),
    sa.CheckConstraint("stage IN ('stranger', 'friend', 'close_friend', 'partner')", name='ck_relationship_snapshots_stage'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_relationship_snapshots_user_version', 'relationship_snapshots', ['user_id', 'version'], unique=False)
    op.create_table('relationship_state',
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('intimacy', sa.Float(), nullable=False),
    sa.Column('trust', sa.Float(), nullable=False),
    sa.Column('familiarity', sa.Float(), nullable=False),
    sa.Column('respect', sa.Float(), server_default='0.6', nullable=False),
    sa.Column('comfort', sa.Float(), server_default='0.6', nullable=False),
    sa.Column('tension', sa.Float(), server_default='0', nullable=False),
    sa.Column('stage', sa.String(), nullable=False),
    sa.Column('conflict_status', sa.String(), server_default='none', nullable=False),
    sa.Column('neglect_active', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('last_interaction_at', sa.DateTime(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("conflict_status IN ('none', 'strain', 'conflict', 'cold', 'recovery', 'resolved')", name='ck_relationship_state_conflict_status'),
    sa.CheckConstraint("stage IN ('stranger', 'friend', 'close_friend', 'partner')", name='ck_relationship_state_stage'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('runtime_traces',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('turn_id', sa.String(), nullable=True),
    sa.Column('action_id', sa.String(), nullable=True),
    sa.Column('correlation_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('duration_ms', sa.Float(), nullable=False),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('events', sa.JSON(), nullable=False),
    sa.Column('token_usage', sa.JSON(), nullable=False),
    sa.Column('model_name', sa.String(), nullable=True),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('turn', 'proactive', 'autonomy_tick')", name='ck_runtime_traces_kind'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_runtime_traces_conversation', 'runtime_traces', ['conversation_id', 'created_at'], unique=False)
    op.create_index('idx_runtime_traces_turn', 'runtime_traces', ['turn_id'], unique=False)
    op.create_index('idx_runtime_traces_user_time', 'runtime_traces', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_runtime_traces_correlation_id', 'runtime_traces', ['correlation_id'], unique=False)
    op.create_table('scene_state',
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('turn_id', sa.Integer(), nullable=False),
    sa.Column('location', sa.String(), nullable=True),
    sa.Column('current_activity', sa.String(), nullable=True),
    sa.Column('current_action', sa.String(), nullable=True),
    sa.Column('pending_action', sa.Text(), nullable=True),
    sa.Column('completed_actions', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('session_id')
    )
    op.create_table('trigger_registry',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('character_id', sa.String(), server_default='asuna', nullable=False),
    sa.Column('trigger_type', sa.String(), nullable=False),
    sa.Column('trigger_key', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('cooldown_until', sa.DateTime(), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'due', 'fired', 'done', 'cancelled')", name='ck_trigger_registry_status'),
    sa.CheckConstraint("trigger_type IN ('conversation_inactivity', 'scheduled_followup', 'action_due')", name='ck_trigger_registry_type'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trigger_key')
    )
    op.create_index('idx_trigger_registry_status_due_at', 'trigger_registry', ['status', 'due_at'], unique=False)
    op.create_index('idx_trigger_registry_user_status', 'trigger_registry', ['user_id', 'status'], unique=False)
    op.create_table('user_situations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('dimension', sa.String(length=30), nullable=False),
    sa.Column('summary', sa.String(length=100), nullable=False),
    sa.Column('intensity', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('source', sa.String(), server_default='conversation_pattern', nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('detected_at', sa.DateTime(), nullable=False),
    sa.Column('valid_until', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("source IN ('conversation_pattern', 'user_directive', 'llm_assist')", name='ck_user_situations_source'),
    sa.CheckConstraint("status IN ('active', 'expired', 'dismissed')", name='ck_user_situations_status'),
    sa.CheckConstraint('intensity BETWEEN 1 AND 5', name='ck_user_situations_intensity'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_user_situations_active', 'user_situations', ['user_id', 'status', 'valid_until'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('display_name', sa.String(), nullable=True),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('active', 'inactive')", name='ck_users_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ux_users_email', 'users', ['email'], unique=True, sqlite_where=sa.text('email IS NOT NULL'), postgresql_where=sa.text('email IS NOT NULL'))
    op.create_table('world_entities',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('world_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('aliases', sa.JSON(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('location_id', sa.String(), nullable=False),
    sa.Column('state', sa.String(), nullable=False),
    sa.Column('quantity', sa.Float(), server_default='1', nullable=False),
    sa.Column('unit', sa.String(), server_default='', nullable=False),
    sa.Column('consumable', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('properties', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('last_action_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("category IN ('food', 'drink', 'tool', 'furniture', 'clothing', 'device', 'misc')", name='ck_world_entities_category'),
    sa.CheckConstraint("status IN ('active', 'destroyed')", name='ck_world_entities_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_world_entities_world_location', 'world_entities', ['world_id', 'location_id'], unique=False)
    op.create_index('idx_world_entities_world_status', 'world_entities', ['world_id', 'status'], unique=False)
    op.create_table('world_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('world_id', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('importance', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('due_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('source', sa.String(), server_default='user_mention', nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("importance IN ('low', 'normal', 'high')", name='ck_world_events_importance'),
    sa.CheckConstraint("source IN ('user_mention', 'manual', 'autonomy', 'character', 'time', 'weather', 'calendar', 'user_evidence', 'daily_life', 'simulation')", name='ck_world_events_source'),
    sa.CheckConstraint("status IN ('scheduled', 'active', 'completed', 'cancelled', 'expired')", name='ck_world_events_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_world_events_world_due', 'world_events', ['world_id', 'status', 'due_at'], unique=False)
    op.create_index('uq_world_events_idempotency', 'world_events', ['idempotency_key'], unique=True, sqlite_where=sa.text('idempotency_key IS NOT NULL'), postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.create_table('world_snapshots',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('world_id', sa.String(), nullable=False),
    sa.Column('label', sa.String(), nullable=True),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_world_snapshots_world_time', 'world_snapshots', ['world_id', 'created_at'], unique=False)
    op.create_table('worlds',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), server_default='home', nullable=False),
    sa.Column('time_mode', sa.String(), server_default='real_sync', nullable=False),
    sa.Column('sim_time', sa.DateTime(), nullable=True),
    sa.Column('sim_last_advanced_at', sa.DateTime(), nullable=True),
    sa.Column('sim_rate', sa.Float(), server_default='1', nullable=False),
    sa.Column('current_location', sa.String(), nullable=False),
    sa.Column('environment', sa.JSON(), nullable=False),
    sa.Column('notes', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('owner_type', sa.String(), nullable=True),
    sa.Column('owner_id', sa.String(), nullable=True),
    sa.CheckConstraint("time_mode IN ('real_sync', 'simulated', 'story')", name='ck_worlds_time_mode'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_worlds_owner', 'worlds', ['owner_type', 'owner_id'], unique=False)
    op.create_table('conversation_summaries',
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('conversation_id')
    )
    op.create_table('ledger_entries',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('account_id', sa.String(), nullable=False),
    sa.Column('category_id', sa.String(), nullable=True),
    sa.Column('amount_minor', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='CNY', nullable=False),
    sa.Column('direction', sa.String(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('merchant', sa.String(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('source_ref', sa.String(), nullable=True),
    sa.Column('idempotency_key', sa.String(), nullable=False),
    sa.Column('reversal_of', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("direction IN ('expense', 'income', 'transfer')", name='ck_ledger_entries_direction'),
    sa.CheckConstraint("source IN ('conversation', 'action', 'manual', 'import')", name='ck_ledger_entries_source'),
    sa.CheckConstraint('amount_minor > 0', name='ck_ledger_entries_amount_minor'),
    sa.ForeignKeyConstraint(['account_id'], ['ledger_accounts.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['ledger_categories.id'], ),
    sa.ForeignKeyConstraint(['reversal_of'], ['ledger_entries.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('ix_ledger_entries_reversal', 'ledger_entries', ['reversal_of'], unique=False)
    op.create_index('ix_ledger_entries_user_cat', 'ledger_entries', ['user_id', 'category_id'], unique=False)
    op.create_index('ix_ledger_entries_user_time', 'ledger_entries', ['user_id', 'occurred_at'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('is_proactive', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("role IN ('human', 'ai')", name='ck_messages_role'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_messages_conv', 'messages', ['conversation_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_messages_conv', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_ledger_entries_user_time', table_name='ledger_entries')
    op.drop_index('ix_ledger_entries_user_cat', table_name='ledger_entries')
    op.drop_index('ix_ledger_entries_reversal', table_name='ledger_entries')
    op.drop_table('ledger_entries')
    op.drop_table('conversation_summaries')
    op.drop_index('ix_worlds_owner', table_name='worlds')
    op.drop_table('worlds')
    op.drop_index('idx_world_snapshots_world_time', table_name='world_snapshots')
    op.drop_table('world_snapshots')
    op.drop_index('uq_world_events_idempotency', table_name='world_events', sqlite_where=sa.text('idempotency_key IS NOT NULL'), postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.drop_index('idx_world_events_world_due', table_name='world_events')
    op.drop_table('world_events')
    op.drop_index('idx_world_entities_world_status', table_name='world_entities')
    op.drop_index('idx_world_entities_world_location', table_name='world_entities')
    op.drop_table('world_entities')
    op.drop_index('ux_users_email', table_name='users', sqlite_where=sa.text('email IS NOT NULL'), postgresql_where=sa.text('email IS NOT NULL'))
    op.drop_table('users')
    op.drop_index('idx_user_situations_active', table_name='user_situations')
    op.drop_table('user_situations')
    op.drop_index('idx_trigger_registry_user_status', table_name='trigger_registry')
    op.drop_index('idx_trigger_registry_status_due_at', table_name='trigger_registry')
    op.drop_table('trigger_registry')
    op.drop_table('scene_state')
    op.drop_index('ix_runtime_traces_correlation_id', table_name='runtime_traces')
    op.drop_index('idx_runtime_traces_user_time', table_name='runtime_traces')
    op.drop_index('idx_runtime_traces_turn', table_name='runtime_traces')
    op.drop_index('idx_runtime_traces_conversation', table_name='runtime_traces')
    op.drop_table('runtime_traces')
    op.drop_table('relationship_state')
    op.drop_index('idx_relationship_snapshots_user_version', table_name='relationship_snapshots')
    op.drop_table('relationship_snapshots')
    op.drop_index('idx_relationship_milestones_user', table_name='relationship_milestones')
    op.drop_table('relationship_milestones')
    op.drop_index('idx_relationship_events_user', table_name='relationship_events')
    op.drop_table('relationship_events')
    op.drop_index('idx_relationship_conflicts_user_status', table_name='relationship_conflicts')
    op.drop_table('relationship_conflicts')
    op.drop_index('idx_reflection_runs_user_status', table_name='reflection_runs')
    op.drop_index('idx_reflection_runs_status_created', table_name='reflection_runs')
    op.drop_table('reflection_runs')
    op.drop_index('idx_prompt_snapshots_turn', table_name='prompt_snapshots')
    op.drop_index('idx_prompt_snapshots_time', table_name='prompt_snapshots')
    op.drop_index('idx_prompt_snapshots_request', table_name='prompt_snapshots')
    op.drop_table('prompt_snapshots')
    op.drop_index('idx_proactive_actions_user_status', table_name='proactive_actions')
    op.drop_index('idx_proactive_actions_dedupe', table_name='proactive_actions')
    op.drop_table('proactive_actions')
    op.drop_table('personality_state')
    op.drop_index('idx_outbox_events_status_next_retry', table_name='outbox_events')
    op.drop_table('outbox_events')
    op.drop_index('idx_memory_links_memory', table_name='memory_links')
    op.drop_table('memory_links')
    op.drop_index('idx_memory_candidates_user_status', table_name='memory_candidates')
    op.drop_table('memory_candidates')
    op.drop_index('idx_memories_user_character_status', table_name='memories')
    op.drop_index('idx_memories_user', table_name='memories')
    op.drop_table('memories')
    op.drop_index('ix_loop_runs_session_id', table_name='loop_runs')
    op.drop_index('idx_loop_runs_user_started_at', table_name='loop_runs')
    op.drop_index('idx_loop_runs_status_started_at', table_name='loop_runs')
    op.drop_table('loop_runs')
    op.drop_index('idx_llm_calls_turn', table_name='llm_call_records')
    op.drop_index('idx_llm_calls_time', table_name='llm_call_records')
    op.drop_index('idx_llm_calls_request', table_name='llm_call_records')
    op.drop_table('llm_call_records')
    op.drop_index('ix_life_tasks_user_status', table_name='life_tasks')
    op.drop_index('ix_life_tasks_user_remind', table_name='life_tasks')
    op.drop_table('life_tasks')
    op.drop_index('ix_ledger_categories_user', table_name='ledger_categories')
    op.drop_table('ledger_categories')
    op.drop_index('ix_ledger_accounts_user', table_name='ledger_accounts')
    op.drop_table('ledger_accounts')
    op.drop_index('idx_insights_user_status', table_name='insights')
    op.drop_index('idx_insights_user_scope_status', table_name='insights')
    op.drop_table('insights')
    op.drop_index('idx_goal_plans_goal_status', table_name='goal_plans')
    op.drop_table('goal_plans')
    op.drop_index('idx_feishu_deliveries_delivered_at', table_name='feishu_deliveries')
    op.drop_table('feishu_deliveries')
    op.drop_index('idx_feishu_dedupe_ledger_received_at', table_name='feishu_dedupe_ledger')
    op.drop_table('feishu_dedupe_ledger')
    op.drop_index('idx_evidence_links_memory', table_name='evidence_links')
    op.drop_table('evidence_links')
    op.drop_index('idx_evaluation_user_time', table_name='evaluation_reports')
    op.drop_index('idx_evaluation_subject', table_name='evaluation_reports')
    op.drop_table('evaluation_reports')
    op.drop_index('idx_emotion_history_user', table_name='emotion_history')
    op.drop_table('emotion_history')
    op.drop_index('idx_development_state_user_status', table_name='development_state')
    op.drop_index('uq_development_state_active_key', table_name='development_state', sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.drop_index('idx_development_state_user_kind', table_name='development_state')
    op.drop_table('development_state')
    op.drop_index('idx_development_changes_state', table_name='development_changes')
    op.drop_index('idx_development_changes_insight', table_name='development_changes')
    op.drop_table('development_changes')
    op.drop_index('idx_decision_records_user_time', table_name='decision_records')
    op.drop_index('idx_decision_records_action', table_name='decision_records')
    op.drop_table('decision_records')
    op.drop_index('uq_daily_plans_user_date_seq', table_name='daily_plans', sqlite_where=sa.text("status IN ('planned', 'active')"), postgresql_where=sa.text("status IN ('planned', 'active')"))
    op.drop_index('idx_daily_plans_lookup', table_name='daily_plans')
    op.drop_table('daily_plans')
    op.drop_table('conversations')
    op.drop_table('character_state')
    op.drop_index('idx_character_goals_user_status', table_name='character_goals')
    op.drop_index('idx_character_goals_parent', table_name='character_goals')
    op.drop_index('idx_character_goals_layer_domain', table_name='character_goals')
    op.drop_table('character_goals')
    op.drop_index('idx_channel_identities_user', table_name='channel_identities')
    op.drop_table('channel_identities')
    op.drop_index('idx_background_jobs_status_run_at', table_name='background_jobs')
    op.drop_table('background_jobs')
    op.drop_index('idx_agent_state_snapshots_user_created', table_name='agent_state_snapshots')
    op.drop_table('agent_state_snapshots')
    op.drop_table('agent_metric_snapshots')
    op.drop_index(op.f('ix_action_schedules_action_id'), table_name='action_schedules')
    op.drop_index('idx_action_schedules_due', table_name='action_schedules')
    op.drop_table('action_schedules')
    op.drop_index(op.f('ix_action_records_user_id'), table_name='action_records')
    op.drop_index(op.f('ix_action_records_run_id'), table_name='action_records')
    op.drop_index('idx_action_records_user_status', table_name='action_records')
    op.drop_index('idx_action_records_user_dedupe', table_name='action_records')
    op.drop_table('action_records')
    # ### end Alembic commands ###
