"""V2.3.0 Catch-up（architecture.md §7.4）：长离线追赶折叠。

≤ catch_up_max_days 逐日 day_summary；超出折叠为单条 long_gap；
今日边界由 DayCycleEngine 正常流程处理，本模块不重放 part 标记。
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from app.repositories import world_repository, world_simulation_repository

logger = logging.getLogger(__name__)

_COVERED_KEY_PREFIXES = ("time:day_start:", "time:day_summary:", "time:long_gap:")


@dataclass
class CatchUpPlan:
    mode: str
    days_behind: int = 0
    missing_days: list[date] = field(default_factory=list)
    gap_from: date | None = None
    gap_to: date | None = None


def compute_catch_up_plan(
    last_covered: date | None, today: date, max_days: int
) -> CatchUpPlan:
    """纯函数：last_covered=None（冷启动）→ none；1 天走正常日界流程。"""
    if last_covered is None or today <= last_covered:
        return CatchUpPlan(mode="none")
    days_behind = (today - last_covered).days
    missing = [
        date.fromordinal(last_covered.toordinal() + offset)
        for offset in range(1, days_behind)
    ]
    if days_behind == 1:
        return CatchUpPlan(mode="none", days_behind=days_behind)
    if days_behind <= max_days:
        return CatchUpPlan(mode="daily", days_behind=days_behind, missing_days=missing)
    return CatchUpPlan(
        mode="long_gap", days_behind=days_behind, gap_from=last_covered, gap_to=today
    )


def _latest_covered_day(world_id: str, today: date) -> date | None:
    latest: date | None = None
    events = world_repository.list_events(
        world_id,
        statuses=["completed"],
        types=["time_marker"],
        order="created_at_desc",
        limit=200,
    )
    for event in events:
        key = event.idempotency_key
        if not key or not key.startswith(_COVERED_KEY_PREFIXES):
            continue
        candidate = _extract_date(key, today)
        if candidate is not None and candidate <= today:
            if latest is None or candidate > latest:
                latest = candidate
    return latest


def _extract_date(key: str, today: date) -> date | None:
    parts = key.split(":")
    for part in reversed(parts):
        try:
            return date.fromisoformat(part)
        except ValueError:
            continue
    return None


def run_catch_up(user_id: str, now=None) -> dict:
    """编排入口：检查覆盖日期 → 折叠补发；幂等键防重。"""
    from app.application import world_engine

    try:
        world = world_repository.get_world(user_id)
        if world is None:
            return {"mode": "none"}
        from app.models.world import WorldTimeMode

        ctx = world_engine._default_provider.context(world)
        today = ctx.now.date()
        last_covered = _latest_covered_day(world.world_id, today)
        settings = world_engine.get_settings()
        plan = compute_catch_up_plan(last_covered, today, settings.catch_up_max_days)
        if plan.mode == "none":
            return {"mode": "none", "days_behind": plan.days_behind}

        emitted: list[str] = []
        if plan.mode == "daily":
            for day in plan.missing_days:
                emitted.extend(
                    world_engine._emit_simulation_events(
                        user_id,
                        [
                            {
                                "event_type": "time_marker",
                                "title": f"{day.isoformat()} 平静地过去了",
                                "importance": "low",
                                "source": "time",
                                "status": "completed",
                                "payload": {"date": day.isoformat(), "kind": "day_summary"},
                                "idempotency_key": f"time:day_summary:{day.isoformat()}",
                            }
                        ],
                    )
                )
        else:
            emitted.extend(
                world_engine._emit_simulation_events(
                    user_id,
                    [
                        {
                            "event_type": "time_marker",
                            "title": f"过去了 {plan.days_behind} 天",
                            "importance": "normal",
                            "source": "time",
                            "status": "completed",
                            "payload": {
                                "kind": "long_gap",
                                "from": plan.gap_from.isoformat(),
                                "to": plan.gap_to.isoformat(),
                                "days": plan.days_behind,
                            },
                            "idempotency_key": f"time:long_gap:{plan.gap_from.isoformat()}:{plan.gap_to.isoformat()}",
                        }
                    ],
                )
            )
        return {"mode": plan.mode, "days_behind": plan.days_behind, "emitted": emitted}
    except Exception:
        logger.exception("追赶检查失败")
        return {"mode": "none", "error": "catch_up_failed"}
