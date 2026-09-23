"""PLA-013 超支预警：模板渲染，数字只来自聚合/预算检查（零 LLM）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from app.channels.base import ChannelErrorKind, SendResult
from app.core.settings import get_settings
from app.services.autonomy_policy import in_quiet_hours
from app.services.ledger.budget import (
    REASON_NEAR_LIMIT,
    REASON_NO_DATA,
    REASON_OVER_LIMIT,
    check_all_budgets,
)
from app.services.ledger.format import format_minor
from app.services.ledger.query import Period, summary

KIND_BUDGET_OVER = "budget_over"
KIND_BUDGET_NEAR = "budget_near"
KIND_DAILY_SPIKE = "daily_spike"
KIND_MONTHLY_SURGE = "monthly_surge"
SEVERITY = "notice"
TRIGGER_SOURCE = "ledger_alert"

DAILY_SPIKE_RATIO = 3.0
DAILY_SPIKE_FLOOR_MINOR = 5000
MONTHLY_SURGE_RATIO = 0.5
MONTHLY_SURGE_FLOOR_MINOR = 20000
NEAR_LIMIT_ALERT_RATIO = 0.9


@dataclass(frozen=True, slots=True)
class AlertDraft:
    kind: str
    scope_ref: str
    title: str
    body: str
    dedupe_key: str
    severity: str
    observed: Mapping[str, int]


def alert_dedupe_key(kind: str, scope_ref: str, period_start: datetime) -> str:
    return f"ledger_alert:{kind}:{scope_ref}:{period_start.isoformat()}"


def _period_start_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _draft(
    *,
    kind: str,
    scope_ref: str,
    title: str,
    body: str,
    period_start: datetime,
    observed: Mapping[str, int],
) -> AlertDraft:
    return AlertDraft(
        kind=kind,
        scope_ref=scope_ref,
        title=title,
        body=body,
        dedupe_key=alert_dedupe_key(kind, scope_ref, period_start),
        severity=SEVERITY,
        observed=dict(observed),
    )


def evaluate_alerts(user_id: str, *, now: datetime | None = None, settings=None) -> list[AlertDraft]:
    cfg = settings if settings is not None else get_settings()
    timestamp = now or datetime.now()
    drafts: list[AlertDraft] = []
    period_start = _period_start_month(timestamp)
    month = Period.month(timestamp)
    month_data = summary(user_id, period=month, now=timestamp, compare_previous=False)

    for check in check_all_budgets(user_id, now=timestamp, period="month"):
        if check.reason == REASON_NO_DATA:
            continue
        scope_ref = check.budget.goal_id
        if check.reason == REASON_OVER_LIMIT or (
            check.consumed_minor > check.budget.limit_minor
        ):
            drafts.append(
                _draft(
                    kind=KIND_BUDGET_OVER,
                    scope_ref=scope_ref,
                    title="预算超支",
                    body=(
                        f"本月已支出 {format_minor(check.consumed_minor)}，"
                        f"超出预算 {format_minor(check.budget.limit_minor)}"
                    ),
                    period_start=period_start,
                    observed={
                        "consumed_minor": check.consumed_minor,
                        "limit_minor": check.budget.limit_minor,
                    },
                )
            )
        elif (
            check.budget.limit_minor
            and check.consumed_minor / check.budget.limit_minor >= NEAR_LIMIT_ALERT_RATIO
        ):
            drafts.append(
                _draft(
                    kind=KIND_BUDGET_NEAR,
                    scope_ref=scope_ref,
                    title="预算接近上限",
                    body=(
                        f"本月已支出 {format_minor(check.consumed_minor)}，"
                        f"预算 {format_minor(check.budget.limit_minor)}"
                    ),
                    period_start=period_start,
                    observed={
                        "consumed_minor": check.consumed_minor,
                        "limit_minor": check.budget.limit_minor,
                    },
                )
            )

    day_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    day_data = summary(
        user_id,
        period=Period.custom(day_start, timestamp, label="day"),
        now=timestamp,
        compare_previous=False,
    )
    if day_data.entry_count > 0:
        prev_days = []
        for offset in range(1, 8):
            start = day_start - timedelta(days=offset)
            end = start + timedelta(days=1)
            prev = summary(
                user_id,
                period=Period.custom(start, end, label="prev"),
                now=timestamp,
                compare_previous=False,
            )
            if prev.entry_count > 0:
                prev_days.append(prev.expense_minor)
        if prev_days:
            avg = sum(prev_days) / len(prev_days)
            if (
                avg > 0
                and day_data.expense_minor >= avg * DAILY_SPIKE_RATIO
                and day_data.expense_minor >= DAILY_SPIKE_FLOOR_MINOR
            ):
                drafts.append(
                    _draft(
                        kind=KIND_DAILY_SPIKE,
                        scope_ref="day",
                        title="今日消费异常",
                        body=(
                            f"今日支出 {format_minor(day_data.expense_minor)}，"
                            f"高于近日水平"
                        ),
                        period_start=day_start,
                        observed={
                            "today_minor": day_data.expense_minor,
                            "baseline_minor": int(avg),
                        },
                    )
                )

    prev_month_start = (period_start - timedelta(days=1)).replace(day=1)
    prev_month = Period.month(prev_month_start)
    prev_data = summary(
        user_id, period=prev_month, now=timestamp, compare_previous=False
    )
    if (
        prev_data.entry_count > 0
        and month_data.entry_count > 0
        and prev_data.expense_minor > 0
        and month_data.expense_minor
        >= prev_data.expense_minor * (1 + MONTHLY_SURGE_RATIO)
        and month_data.expense_minor - prev_data.expense_minor >= MONTHLY_SURGE_FLOOR_MINOR
    ):
        drafts.append(
            _draft(
                kind=KIND_MONTHLY_SURGE,
                scope_ref="month",
                title="本月支出突增",
                body=(
                    f"本月支出 {format_minor(month_data.expense_minor)}，"
                    f"较上月 {format_minor(prev_data.expense_minor)} 明显上升"
                ),
                period_start=period_start,
                observed={
                    "this_month_minor": month_data.expense_minor,
                    "prev_month_minor": prev_data.expense_minor,
                },
            )
        )
    return drafts


def should_alert(draft: AlertDraft, *, now: datetime, settings=None) -> bool:
    cfg = settings if settings is not None else get_settings()
    if in_quiet_hours(now, cfg.autonomy_quiet_hours_start, cfg.autonomy_quiet_hours_end):
        return False
    from app.repositories import proactive_repository

    return proactive_repository.find_by_dedupe_key(draft.dedupe_key) is None


def deliver_alert(
    draft: AlertDraft, *, now: datetime, user_id: str = "default-user"
) -> SendResult:
    from app.models.autonomy import ProactiveAction
    from app.repositories import proactive_repository
    from app.services import proactive_delivery

    try:
        action = ProactiveAction(
            id="pa_"
            + __import__("hashlib").sha1(draft.dedupe_key.encode()).hexdigest()[:12],
            user_id=user_id,
            session_id=f"alert:{draft.kind}",
            trigger_type="scheduled_followup",
            dedupe_key=draft.dedupe_key,
            intention="check_in",
            reason=draft.kind,
            payload_text=draft.body,
            status="candidate",
            created_at=now,
            updated_at=now,
        )
        if not proactive_repository.enqueue(action):
            return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)
        outbound = proactive_delivery.get_proactive_outbound()
        if outbound is None:
            proactive_repository.transition(
                action.id, "approved", now=now, payload_text=draft.body
            )
            proactive_repository.transition(
                action.id, "delivered", delivered_at=now, payload_text=draft.body
            )
            return SendResult(ok=True)
        import asyncio

        async def _run() -> SendResult:
            return await outbound.send(user_id, draft.body, draft.dedupe_key)

        return asyncio.run(_run())
    except Exception:
        return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)


def run_maintenance(now: datetime | None = None) -> dict[str, Any]:
    from app.repositories import user_repository

    timestamp = now or datetime.now()
    users = [row.id for row in user_repository.list_all(limit=50)]
    if not users:
        users = ["default-user"]
    sent = 0
    skipped = 0
    for user_id in users:
        for draft in evaluate_alerts(user_id, now=timestamp):
            if not should_alert(draft, now=timestamp):
                skipped += 1
                continue
            result = deliver_alert(draft, now=timestamp, user_id=user_id)
            if result.ok:
                sent += 1
            else:
                skipped += 1
    return {"status": "ok", "sent": sent, "skipped": skipped}


ALERT_TRIGGER_SOURCE = TRIGGER_SOURCE

__all__ = [
    "ALERT_TRIGGER_SOURCE",
    "AlertDraft",
    "KIND_BUDGET_NEAR",
    "KIND_BUDGET_OVER",
    "KIND_DAILY_SPIKE",
    "KIND_MONTHLY_SURGE",
    "alert_dedupe_key",
    "deliver_alert",
    "evaluate_alerts",
    "run_maintenance",
    "should_alert",
]
