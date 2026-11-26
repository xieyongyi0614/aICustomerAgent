"""API-020 车辆提醒纯函数用例。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core import timeutil
from app.core.settings.car import CarSettings
from app.services.car import reminders as car_reminders

pytestmark = pytest.mark.unit

NOW = timeutil.ensure_aware(datetime(2026, 9, 30, 12, 0, 0))
SETTINGS = CarSettings()


def _profile(**overrides) -> SimpleNamespace:
    payload = {
        "purchased_at": timeutil.ensure_aware(datetime(2025, 10, 1, 0, 0, 0)),
        "odometer_km": 12480,
        "service_interval_km": 10000,
        "service_interval_months": 12,
        "insurance_due_at": None,
        "inspection_due_at": None,
        "restriction_city": None,
        "restriction_digits": None,
        "restriction_weekday": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _last_service(odometer_km: int, occurred_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(odometer_km=odometer_km, occurred_at=occurred_at)


def test_car_settings_are_parameter_not_toggle():
    for name in CarSettings.model_fields:
        assert "enabled" not in name
        assert "enable" not in name


def test_add_months_clamps_day_overflow():
    assert car_reminders.add_months(timeutil.ensure_aware(datetime(2026, 1, 31)), 1) == timeutil.ensure_aware(datetime(2026, 2, 28))
    assert car_reminders.add_months(timeutil.ensure_aware(datetime(2026, 9, 30)), 12) == timeutil.ensure_aware(datetime(2027, 9, 30))


def test_age_text_reports_years_and_months():
    assert car_reminders.age_text(timeutil.ensure_aware(datetime(2024, 6, 15)), NOW) == "2 年 3 个月"
    assert car_reminders.age_text(None, NOW) is None


def test_car_reminders_service_prefers_time_when_time_ratio_is_smaller():
    bundle = car_reminders.derive(
        profile=_profile(),
        last_service=_last_service(5000, timeutil.ensure_aware(datetime(2025, 10, 1, 0, 0, 0))),
        now=NOW,
        settings=SETTINGS,
    )

    service = next(item for item in bundle.reminders if item.kind == "service")
    assert service.due_km is None
    assert service.due_at == timeutil.ensure_aware(datetime(2026, 10, 1, 0, 0, 0))
    assert service.level == "soon"


def test_car_reminders_service_uses_km_and_days_whichever_first():
    bundle = car_reminders.derive(
        profile=_profile(odometer_km=21900),
        last_service=_last_service(12000, timeutil.ensure_aware(datetime(2026, 9, 1, 0, 0, 0))),
        now=NOW,
        settings=SETTINGS,
    )

    service = next(item for item in bundle.reminders if item.kind == "service")
    assert service.due_km == 22000
    assert service.due_at is None
    assert service.detail == "还剩 100 km"
    assert service.level == "soon"


def test_car_reminders_service_normal_when_far_from_both():
    bundle = car_reminders.derive(
        profile=_profile(odometer_km=11000),
        last_service=_last_service(12000, timeutil.ensure_aware(datetime(2026, 9, 1, 0, 0, 0))),
        now=NOW,
        settings=SETTINGS,
    )

    service = next(item for item in bundle.reminders if item.kind == "service")
    assert service.level == "normal"


def test_car_reminders_service_absent_without_interval():
    bundle = car_reminders.derive(
        profile=_profile(service_interval_km=None, service_interval_months=None),
        last_service=None,
        now=NOW,
        settings=SETTINGS,
    )

    assert [item.kind for item in bundle.reminders] == []


def test_car_reminders_insurance_level_follows_lead_days():
    soon = car_reminders.derive(
        profile=_profile(insurance_due_at=timeutil.ensure_aware(datetime(2026, 11, 1))),
        now=NOW,
        settings=SETTINGS,
    )
    far = car_reminders.derive(
        profile=_profile(insurance_due_at=timeutil.ensure_aware(datetime(2027, 6, 1))),
        now=NOW,
        settings=SETTINGS,
    )

    insurance = next(item for item in soon.reminders if item.kind == "insurance")
    assert insurance.level == "soon"
    assert insurance.detail == "2026-11-01 到期，该比价续保了"
    assert (
        next(item for item in far.reminders if item.kind == "insurance").level
        == "normal"
    )


def test_car_reminders_inspection_absent_without_due_date():
    bundle = car_reminders.derive(
        profile=_profile(insurance_due_at=timeutil.ensure_aware(datetime(2026, 11, 1))),
        now=NOW,
        settings=SETTINGS,
    )

    assert not any(item.kind == "inspection" for item in bundle.reminders)


def test_car_reminders_restriction_absent_when_not_configured():
    bundle = car_reminders.derive(profile=_profile(), now=NOW, settings=SETTINGS)

    assert not any(item.kind == "restriction" for item in bundle.reminders)
    assert bundle.restriction_configured is False
    assert bundle.guide == car_reminders.RESTRICTION_GUIDE


def test_car_reminders_never_invents_restriction_digits():
    bundle = car_reminders.derive(
        profile=_profile(restriction_city="上海", restriction_weekday="周三"),
        now=NOW,
        settings=SETTINGS,
    )

    assert not any(item.kind == "restriction" for item in bundle.reminders)
    assert not any(character.isdigit() for character in (bundle.guide or ""))
    assert bundle.restriction_configured is False


def test_car_reminders_restriction_uses_user_configuration():
    bundle = car_reminders.derive(
        profile=_profile(
            restriction_city="上海",
            restriction_digits="4 和 9",
            restriction_weekday="周三",
        ),
        now=NOW,
        settings=SETTINGS,
    )

    restriction = next(
        item for item in bundle.reminders if item.kind == "restriction"
    )
    assert restriction.detail == "上海 · 尾号 4 和 9 限行"
    assert restriction.due_at == timeutil.ensure_aware(datetime(2026, 10, 7, 0, 0, 0))
    assert bundle.restriction_configured is True
    assert bundle.guide is None


def test_car_reminders_absent_profile_yields_guidance_only():
    bundle = car_reminders.derive(profile=None, now=NOW, settings=SETTINGS)

    assert bundle.reminders == ()
    assert bundle.restriction_configured is False
    assert bundle.guide == car_reminders.RESTRICTION_GUIDE
