"""API-018 车辆域建表、约束与迁移 0003 用例。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from app.core.db import (
    Base,
    CarLoanRow,
    CarMileageLogRow,
    CarProfileRow,
    CarServiceRecordRow,
)
from tests.support.schema_pins import (
    MIGRATION_HEAD,
    MIGRATION_HEAD_PARENT,
    SCHEMA_COLUMNS_DIGEST,
    SCHEMA_TABLE_COUNT,
    schema_columns_digest,
)

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION_FILE = BACKEND / "migrations" / "versions" / "0003_car_domain.py"
CAR_TABLES = (
    "car_profiles",
    "car_loans",
    "car_service_records",
    "car_mileage_logs",
)
MONEY_COLUMNS = {"amount_minor", "price_minor", "total_minor", "cost_minor"}
NOW = datetime(2026, 9, 30, 12, 0, 0)


def _migration_source() -> str:
    return MIGRATION_FILE.read_text(encoding="utf-8")


def test_car_tables_are_registered_in_metadata():
    assert set(CAR_TABLES) <= set(Base.metadata.tables)


def test_schema_table_count_matches_pin():
    assert len(Base.metadata.tables) == SCHEMA_TABLE_COUNT == 55


def test_schema_columns_digest_matches_pin():
    assert schema_columns_digest() == SCHEMA_COLUMNS_DIGEST


def test_migration_chain_head_matches_pin():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == [MIGRATION_HEAD]
    revision = script.get_revision(MIGRATION_HEAD)
    assert revision is not None
    assert revision.down_revision == MIGRATION_HEAD_PARENT


def test_car_migration_declares_upgrade_and_downgrade_for_all_tables():
    source = _migration_source()
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    for name in CAR_TABLES:
        assert f'"{name}"' in source
        assert f'op.drop_table("{name}")' in source


def test_car_check_constraints_are_complete_boolean_expressions():
    source = _migration_source()
    assert '"paid_periods >= 0 AND paid_periods <= total_periods"' in source
    assert '"odometer_km >= 0"' in source
    assert '"delta_km IS NULL OR delta_km >= 0"' in source
    assert '"amount_minor IS NULL OR amount_minor > 0"' in source


def test_car_tables_have_no_amount_of_ledger_entries():
    for name in CAR_TABLES:
        columns = {column.name for column in Base.metadata.tables[name].columns}
        if name == "car_service_records":
            assert columns & MONEY_COLUMNS == {"amount_minor"}
        else:
            assert not (columns & MONEY_COLUMNS)


def test_car_service_records_backlinks_ledger_entry():
    columns = {column.name for column in Base.metadata.tables["car_service_records"].columns}
    assert "ledger_entry_id" in columns


def test_car_profiles_odometer_check_constraint_rejects_negative(db_session_factory):
    session = db_session_factory()
    session.add(
        CarProfileRow(
            id="car-profile-neg",
            user_id="car-schema-user",
            odometer_km=-1,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_car_profiles_battery_check_constraint_rejects_non_positive(db_session_factory):
    session = db_session_factory()
    session.add(
        CarProfileRow(
            id="car-profile-battery",
            user_id="car-schema-user",
            battery_kwh=0.0,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_car_profiles_are_single_row_per_user(db_session_factory):
    session = db_session_factory()
    session.add(
        CarProfileRow(
            id="car-profile-1",
            user_id="car-schema-single",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.add(
        CarProfileRow(
            id="car-profile-2",
            user_id="car-schema-single",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_car_loans_periods_check_constraint_rejects_invalid(db_session_factory):
    session = db_session_factory()
    session.add(
        CarLoanRow(
            id="car-loan-periods",
            user_id="car-schema-user",
            monthly_minor=385000,
            paid_periods=19,
            total_periods=18,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_car_loans_monthly_and_total_constraints_reject_non_positive(db_session_factory):
    for loan_id, monthly_minor, total_periods in (
        ("car-loan-monthly", 0, 36),
        ("car-loan-total", 385000, 0),
    ):
        session = db_session_factory()
        session.add(
            CarLoanRow(
                id=loan_id,
                user_id="car-schema-user",
                monthly_minor=monthly_minor,
                total_periods=total_periods,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.close()


def test_car_loans_are_single_row_per_user(db_session_factory):
    session = db_session_factory()
    session.add(
        CarLoanRow(
            id="car-loan-1",
            user_id="car-schema-loan-single",
            monthly_minor=385000,
            total_periods=36,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.add(
        CarLoanRow(
            id="car-loan-2",
            user_id="car-schema-loan-single",
            monthly_minor=385000,
            total_periods=36,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_car_mileage_logs_delta_check_rejects_negative(db_session_factory):
    session = db_session_factory()
    session.add(
        CarMileageLogRow(
            id="car-mileage-neg",
            user_id="car-schema-user",
            odometer_km=12480,
            delta_km=-1,
            recorded_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_car_service_records_amount_must_be_positive_or_null(db_session_factory):
    session = db_session_factory()
    session.add(
        CarServiceRecordRow(
            id="car-service-zero",
            user_id="car-schema-user",
            title="小保养 · 机油机滤",
            occurred_at=NOW,
            amount_minor=0,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(
        CarServiceRecordRow(
            id="car-service-free",
            user_id="car-schema-user",
            title="首保",
            occurred_at=NOW,
            amount_minor=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()
    session.close()
