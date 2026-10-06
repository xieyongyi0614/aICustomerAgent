from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import timeutil
from app.core.settings import get_settings
from app.models.car import CarReminder

SERVICE_KIND = "service"
INSURANCE_KIND = "insurance"
INSPECTION_KIND = "inspection"
RESTRICTION_KIND = "restriction"

RESTRICTION_GUIDE = "还没配置限行城市、尾号与限行日，配置后我会提前提醒"

_WEEKDAY_INDEX: dict[str, int] = {
    "周一": 0,
    "周二": 1,
    "周三": 2,
    "周四": 3,
    "周五": 4,
    "周六": 5,
    "周日": 6,
    "星期一": 0,
    "星期二": 1,
    "星期三": 2,
    "星期四": 3,
    "星期五": 4,
    "星期六": 5,
    "星期日": 6,
}


@dataclass(frozen=True, slots=True)
class ReminderBundle:
    reminders: tuple[CarReminder, ...]
    restriction_configured: bool
    guide: str | None


@dataclass(frozen=True, slots=True)
class ServiceDue:
    basis: str
    due_km: int | None
    due_at: datetime | None
    remaining_km: int | None
    remaining_days: int | None
    ratio: float


def add_months(value: datetime, months: int) -> datetime:
    value = timeutil.local(value)
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = value.day
    while True:
        try:
            return value.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def age_text(purchased_at: datetime | None, now: datetime) -> str | None:
    if purchased_at is None:
        return None
    purchased_at = timeutil.local(purchased_at)
    now = timeutil.local(now)
    months = (now.year - purchased_at.year) * 12 + (now.month - purchased_at.month)
    if now.day < purchased_at.day:
        months -= 1
    if months < 0:
        months = 0
    years, rest = divmod(months, 12)
    if years and rest:
        return f"{years} 年 {rest} 个月"
    if years:
        return f"{years} 年"
    return f"{rest} 个月"


def service_due(
    *,
    odometer_km: int,
    interval_km: int | None,
    interval_months: int | None,
    anchor_km: int,
    anchor_at: datetime,
    now: datetime,
) -> ServiceDue | None:
    candidates: list[ServiceDue] = []
    now = timeutil.ensure_aware(now)
    anchor_at = timeutil.ensure_aware(anchor_at)
    if interval_km:
        due_km = anchor_km + interval_km
        remaining_km = due_km - odometer_km
        candidates.append(
            ServiceDue(
                basis="km",
                due_km=due_km,
                due_at=None,
                remaining_km=remaining_km,
                remaining_days=None,
                ratio=remaining_km / interval_km,
            )
        )
    if interval_months:
        due_at = add_months(anchor_at, interval_months)
        total_days = max(1, (due_at - anchor_at).days)
        remaining_days = (
        timeutil.ensure_aware(due_at) - timeutil.ensure_aware(now)
    ).days
        candidates.append(
            ServiceDue(
                basis="time",
                due_km=None,
                due_at=due_at,
                remaining_km=None,
                remaining_days=remaining_days,
                ratio=remaining_days / total_days,
            )
        )
    if not candidates:
        return None
    return min(candidates, key=lambda item: item.ratio)


def _service_anchor(
    *,
    purchased_at: datetime | None,
    last_service_odometer: int | None,
    last_service_at: datetime | None,
    now: datetime,
) -> tuple[int, datetime]:
    anchor_km = last_service_odometer if last_service_odometer is not None else 0
    anchor_at = last_service_at or purchased_at or now
    return anchor_km, anchor_at


def _service_reminder(
    profile,
    last_service,
    now: datetime,
    settings,
) -> CarReminder | None:
    last_odometer = (
        int(last_service.odometer_km)
        if last_service is not None and last_service.odometer_km is not None
        else None
    )
    last_at = last_service.occurred_at if last_service is not None else None
    anchor_km, anchor_at = _service_anchor(
        purchased_at=profile.purchased_at,
        last_service_odometer=last_odometer,
        last_service_at=last_at,
        now=now,
    )
    due = service_due(
        odometer_km=int(profile.odometer_km),
        interval_km=profile.service_interval_km,
        interval_months=profile.service_interval_months,
        anchor_km=anchor_km,
        anchor_at=anchor_at,
        now=now,
    )
    if due is None:
        return None
    parts: list[str] = []
    if due.remaining_km is not None:
        parts.append(f"还剩 {due.remaining_km:,} km")
    if due.remaining_days is not None:
        parts.append(f"{due.remaining_days} 天")
    if not parts:
        detail = "该安排保养了"
    elif due.remaining_km is not None and due.remaining_km <= 0:
        detail = "已到保养里程"
    elif due.remaining_days is not None and due.remaining_days <= 0:
        detail = "已到保养时间"
    else:
        detail = " 或 ".join(parts)
    level = "normal"
    if due.remaining_km is not None and due.remaining_km <= settings.car_service_remind_km_before:
        level = "soon"
    elif (
        due.remaining_days is not None
        and due.remaining_days <= settings.car_service_remind_days_before
    ):
        level = "soon"
    return CarReminder(
        kind=SERVICE_KIND,
        title="下次保养",
        detail=detail,
        due_at=due.due_at,
        due_km=due.due_km,
        level=level,
    )


def _due_reminder(
    *,
    kind: str,
    title: str,
    due_at: datetime | None,
    days_before: int,
    now: datetime,
    suffix: str,
) -> CarReminder | None:
    if due_at is None:
        return None
    remaining_days = (
        timeutil.ensure_aware(due_at) - timeutil.ensure_aware(now)
    ).days
    level = "soon" if remaining_days <= days_before else "normal"
    return CarReminder(
        kind=kind,
        title=title,
        detail=f"{timeutil.local(due_at):%Y-%m-%d} 到期{suffix}",
        due_at=due_at,
        level=level,
    )


def _restriction_reminder(profile, now: datetime) -> CarReminder | None:
    weekday = _WEEKDAY_INDEX.get(str(profile.restriction_weekday or "").strip())
    digits = str(profile.restriction_digits or "").strip()
    city = str(profile.restriction_city or "").strip()
    if not city or weekday is None or not digits:
        return None
    days_ahead = (weekday - timeutil.local(now).weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    due_at = (timeutil.local(now) + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    detail = f"{city} · 尾号 {digits} 限行"
    return CarReminder(
        kind=RESTRICTION_KIND,
        title="限行提醒",
        detail=detail,
        due_at=due_at,
        level="normal",
    )


def derive(
    *,
    profile,
    last_service=None,
    now: datetime | None = None,
    settings=None,
) -> ReminderBundle:
    moment = timeutil.ensure_aware(now) or timeutil.now()
    resolved = settings or get_settings()
    reminders: list[CarReminder] = []
    if profile is not None:
        service = _service_reminder(profile, last_service, moment, resolved)
        if service is not None:
            reminders.append(service)
        insurance = _due_reminder(
            kind=INSURANCE_KIND,
            title="车辆保险",
            due_at=profile.insurance_due_at,
            days_before=resolved.car_insurance_remind_days_before,
            now=moment,
            suffix="，该比价续保了",
        )
        if insurance is not None:
            reminders.append(insurance)
        inspection = _due_reminder(
            kind=INSPECTION_KIND,
            title="年检",
            due_at=profile.inspection_due_at,
            days_before=resolved.car_inspection_remind_days_before,
            now=moment,
            suffix="，该安排年检了",
        )
        if inspection is not None:
            reminders.append(inspection)
        restriction = _restriction_reminder(profile, moment)
        if restriction is not None:
            reminders.append(restriction)
        configured = restriction is not None
    else:
        configured = False
    return ReminderBundle(
        reminders=tuple(reminders),
        restriction_configured=configured,
        guide=None if configured else RESTRICTION_GUIDE,
    )
