"""PLA-011 账务节律：模板化日结 / 周报（数字只来自聚合，零 LLM）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from app.channels.base import ChannelErrorKind, SendResult
from app.core.settings import get_settings
from app.services.autonomy_policy import in_quiet_hours
from app.services.ledger.format import format_minor
from app.services.ledger.query import Period, list_entries, summary, top_categories

DEFAULT_DAILY_HHMM = "21:30"
DEFAULT_WEEKLY_HHMM = "20:00"
INFERENTIAL_WORDS = ("约", "大概", "可能", "应该", "估计", "差不多")


@dataclass(frozen=True, slots=True)
class DigestPayload:
    kind: str
    period: Period
    title: str
    body: str
    dedupe_key: str
    summary: Any


def _parse_hhmm(value: str) -> time | None:
    try:
        hour_s, minute_s = value.strip().split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def parse_send_time(raw: str) -> tuple[str, time]:
    """`"21:30"` / `"SUN 20:00"` / `""` → (weekday|``, time)。"""
    text = (raw or "").strip()
    if not text:
        return "", _parse_hhmm(DEFAULT_DAILY_HHMM) or time(21, 30)
    parts = text.split()
    if len(parts) == 1:
        parsed = _parse_hhmm(parts[0])
        return "", parsed or (_parse_hhmm(DEFAULT_DAILY_HHMM) or time(21, 30))
    weekday_token, clock = parts[0].upper(), parts[1]
    parsed = _parse_hhmm(clock) or (_parse_hhmm(DEFAULT_WEEKLY_HHMM) or time(20, 0))
    return weekday_token, parsed


def dedupe_key(kind: str, period: Period) -> str:
    return f"ledger_digest:{kind}:{period.since.isoformat()}"


def _category_line(summary_obj) -> str:
    pairs = [
        (key, value)
        for key, value in sorted(
            summary_obj.by_category.items(), key=lambda item: -abs(item[1])
        )
        if value
    ]
    if not pairs:
        return "（无）"
    return "；".join(f"{key or '未归类'} {format_minor(value)}" for key, value in pairs[:3])


def _render_daily(user_id: str, *, now: datetime) -> DigestPayload | None:
    period = Period.custom(
        now.replace(hour=0, minute=0, second=0, microsecond=0),
        now.replace(hour=23, minute=59, second=59, microsecond=999999),
        label="day",
    )
    data = summary(user_id, period=period, now=now, compare_previous=True)
    if data.entry_count <= 0 and data.reversal_count <= 0:
        return None
    entries = list_entries(user_id, period=period, limit=5)
    lines = [
        f"【日结】{now.date().isoformat()}",
        f"支出 {format_minor(data.expense_minor)}｜收入 {format_minor(data.income_minor)}｜净 {format_minor(data.net_minor)}",
        f"类目 {_category_line(data)}",
        f"条目 {data.entry_count}｜冲正 {data.reversal_count}",
    ]
    if data.compared_to_previous is not None:
        lines.append(
            f"较昨日 支出差 {format_minor(data.compared_to_previous.expense_delta)}"
        )
    if entries:
        lines.append("明细摘要：")
        for item in entries:
            lines.append(f"- {item.direction} {format_minor(item.amount_minor)}")
    body = "\n".join(lines)
    return DigestPayload(
        kind="daily",
        period=period,
        title=f"日结 {now.date().isoformat()}",
        body=body,
        dedupe_key=dedupe_key("daily", period),
        summary=data,
    )


def _render_weekly(user_id: str, *, now: datetime) -> DigestPayload | None:
    period = Period.week(now)
    data = summary(user_id, period=period, now=now, compare_previous=True)
    if data.entry_count <= 0 and data.reversal_count <= 0:
        return None
    top = top_categories(user_id, period=period, limit=5, now=now)
    top_text = "；".join(
        f"{item.category_id or '未归类'} {format_minor(item.expense_minor)}"
        for item in top
        if item.expense_minor
    ) or "（无）"
    lines = [
        f"【周报】{period.since.date().isoformat()} 起",
        f"支出 {format_minor(data.expense_minor)}｜收入 {format_minor(data.income_minor)}｜净 {format_minor(data.net_minor)}",
        f"类目 top {top_text}",
        f"条目 {data.entry_count}｜冲正 {data.reversal_count}",
    ]
    if data.compared_to_previous is not None:
        lines.append(
            f"较上周 支出差 {format_minor(data.compared_to_previous.expense_delta)}"
        )
    body = "\n".join(lines)
    return DigestPayload(
        kind="weekly",
        period=period,
        title=f"周报 {period.since.date().isoformat()}",
        body=body,
        dedupe_key=dedupe_key("weekly", period),
        summary=data,
    )


def build_daily_digest(user_id: str, *, now: datetime, settings=None) -> DigestPayload | None:
    return _render_daily(user_id, now=now)


def build_weekly_digest(user_id: str, *, now: datetime, settings=None) -> DigestPayload | None:
    return _render_weekly(user_id, now=now)


def should_send(payload: DigestPayload, *, now: datetime, settings=None) -> bool:
    cfg = settings if settings is not None else get_settings()
    if in_quiet_hours(
        now, cfg.autonomy_quiet_hours_start, cfg.autonomy_quiet_hours_end
    ):
        return False
    weekday_token, send_at = parse_send_time(cfg.ledger_digest_send_time)
    if payload.kind == "weekly":
        if weekday_token and now.strftime("%a").upper()[:3] != weekday_token[:3]:
            return False
        if weekday_token == "" and now.weekday() != 6:
            return False
        if now.time() < send_at:
            return False
    else:
        daily_at = send_at
        if weekday_token:
            daily_at = _parse_hhmm(DEFAULT_DAILY_HHMM) or time(21, 30)
        if now.time() < daily_at:
            return False
    from app.repositories import proactive_repository

    existing = proactive_repository.find_by_dedupe_key(payload.dedupe_key)
    return existing is None


def deliver_for_user(
    *, user_id: str, payload: DigestPayload, now: datetime
) -> SendResult:
    from app.models.autonomy import ProactiveAction
    from app.repositories import proactive_repository
    from app.services.delivery import outbound as proactive_delivery

    try:
        action = ProactiveAction(
            id="pa_" + __import__("hashlib").sha1(payload.dedupe_key.encode()).hexdigest()[:12],
            user_id=user_id,
            session_id=f"digest:{payload.kind}",
            trigger_type="scheduled_followup",
            dedupe_key=payload.dedupe_key,
            intention="check_in",
            reason="ledger_digest",
            payload_text=payload.body,
            status="candidate",
            created_at=now,
            updated_at=now,
        )
        if not proactive_repository.enqueue(action):
            return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)
        outbound = proactive_delivery.get_proactive_outbound()
        if outbound is None:
            proactive_repository.transition(
                action.id, "approved", now=now, payload_text=payload.body
            )
            proactive_repository.transition(
                action.id, "delivered", delivered_at=now, payload_text=payload.body
            )
            return SendResult(ok=True)
        return _send_sync(outbound, user_id, payload)
    except Exception:
        return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)


def _send_sync(outbound, user_id: str, payload: DigestPayload) -> SendResult:
    import asyncio

    async def _run() -> SendResult:
        return await outbound.send(user_id, payload.body, payload.dedupe_key)

    try:
        return asyncio.run(_run())
    except Exception:
        return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)


def run_maintenance(now: datetime | None = None) -> dict[str, Any]:
    """维护步入口：对每个用户构建 → 应发则投递。零条目 / 未到点 / 免打扰 / 已推均跳过。"""
    from app.core.settings import get_settings as _get_settings
    from app.repositories import user_repository

    timestamp = now or datetime.now()
    cfg = _get_settings()
    users = [row.id for row in user_repository.list_all(limit=50)]
    sent = 0
    skipped = 0
    for user_id in users:
        weekday_token, send_at = parse_send_time(cfg.ledger_digest_send_time)
        daily_payload = build_daily_digest(user_id, now=timestamp, settings=cfg)
        weekly_payload = None
        if (not weekday_token and timestamp.weekday() == 6) or (
            weekday_token and timestamp.strftime("%a").upper()[:3] == weekday_token[:3]
        ):
            weekly_payload = build_weekly_digest(user_id, now=timestamp, settings=cfg)
        for payload in (daily_payload, weekly_payload):
            if payload is None:
                skipped += 1
                continue
            if not should_send(payload, now=timestamp, settings=cfg):
                skipped += 1
                continue
            result = deliver_for_user(user_id=user_id, payload=payload, now=timestamp)
            if result.ok:
                sent += 1
            else:
                skipped += 1
    return {"status": "ok", "sent": sent, "skipped": skipped}


__all__ = [
    "DEFAULT_DAILY_HHMM",
    "DigestPayload",
    "build_daily_digest",
    "build_weekly_digest",
    "dedupe_key",
    "deliver_for_user",
    "parse_send_time",
    "run_maintenance",
    "should_send",
]
