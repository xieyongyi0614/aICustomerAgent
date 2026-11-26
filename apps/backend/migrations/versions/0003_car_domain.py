"""0003：车辆域（档案 / 车贷 / 保养记录 / 里程记录）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "car_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("plate", sa.String(), nullable=True),
        sa.Column("trim_note", sa.String(), nullable=True),
        sa.Column("battery_kwh", sa.Float(), nullable=True),
        sa.Column("purchased_at", sa.DateTime(), nullable=True),
        sa.Column("odometer_km", sa.Integer(), server_default="0", nullable=False),
        sa.Column("insurance_due_at", sa.DateTime(), nullable=True),
        sa.Column("insurance_note", sa.String(), nullable=True),
        sa.Column("insurance_annual_minor", sa.Integer(), nullable=True),
        sa.Column("inspection_due_at", sa.DateTime(), nullable=True),
        sa.Column("inspection_note", sa.String(), nullable=True),
        sa.Column("charger_power_kw", sa.Float(), nullable=True),
        sa.Column("charger_note", sa.String(), nullable=True),
        sa.Column("service_interval_km", sa.Integer(), nullable=True),
        sa.Column("service_interval_months", sa.Integer(), nullable=True),
        sa.Column("restriction_city", sa.String(), nullable=True),
        sa.Column("restriction_digits", sa.String(), nullable=True),
        sa.Column("restriction_weekday", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "battery_kwh IS NULL OR battery_kwh > 0",
            name="ck_car_profiles_battery_kwh",
        ),
        sa.CheckConstraint(
            "charger_power_kw IS NULL OR charger_power_kw > 0",
            name="ck_car_profiles_charger_power_kw",
        ),
        sa.CheckConstraint(
            "insurance_annual_minor IS NULL OR insurance_annual_minor >= 0",
            name="ck_car_profiles_insurance_annual_minor",
        ),
        sa.CheckConstraint(
            "odometer_km >= 0", name="ck_car_profiles_odometer_km"
        ),
        sa.CheckConstraint(
            "service_interval_km IS NULL OR service_interval_km > 0",
            name="ck_car_profiles_service_interval_km",
        ),
        sa.CheckConstraint(
            "service_interval_months IS NULL OR service_interval_months > 0",
            name="ck_car_profiles_service_interval_months",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_car_profiles_user"),
    )
    op.create_table(
        "car_loans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("principal_minor", sa.Integer(), nullable=True),
        sa.Column("monthly_minor", sa.Integer(), nullable=False),
        sa.Column("paid_periods", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_periods", sa.Integer(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "monthly_minor > 0", name="ck_car_loans_monthly_minor"
        ),
        sa.CheckConstraint(
            "paid_periods >= 0 AND paid_periods <= total_periods",
            name="ck_car_loans_periods",
        ),
        sa.CheckConstraint(
            "total_periods > 0", name="ck_car_loans_total_periods"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_car_loans_user"),
    )
    op.create_table(
        "car_service_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("place", sa.String(), nullable=True),
        sa.Column("odometer_km", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("next_due_at", sa.DateTime(), nullable=True),
        sa.Column("next_due_km", sa.Integer(), nullable=True),
        sa.Column("ledger_entry_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "amount_minor IS NULL OR amount_minor > 0",
            name="ck_car_service_records_amount_minor",
        ),
        sa.CheckConstraint(
            "odometer_km IS NULL OR odometer_km >= 0",
            name="ck_car_service_records_odometer_km",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_car_service_records_user_time",
        "car_service_records",
        ["user_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "car_mileage_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("odometer_km", sa.Integer(), nullable=False),
        sa.Column("delta_km", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "delta_km IS NULL OR delta_km >= 0", name="ck_car_mileage_logs_delta_km"
        ),
        sa.CheckConstraint(
            "odometer_km >= 0", name="ck_car_mileage_logs_odometer_km"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_car_mileage_logs_user_time",
        "car_mileage_logs",
        ["user_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_car_mileage_logs_user_time", table_name="car_mileage_logs")
    op.drop_table("car_mileage_logs")
    op.drop_index("ix_car_service_records_user_time", table_name="car_service_records")
    op.drop_table("car_service_records")
    op.drop_table("car_loans")
    op.drop_table("car_profiles")
