"""V2.3.0 DayCycleEngine（architecture.md §5.2/§5.4）：日循环标记计算与发射。

纯函数计算 + 薄发射层；标记以 idempotency_key 幂等落 world_events（唯一 SoT）。
多日追赶折叠见 catch_up（WS-017）；本模块只处理单 tick 邻近区间。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.models.world import WEEKDAY_CN, TimeContext
from app.repositories import world_repository, world_simulation_repository

logger = logging.getLogger(__name__)

_last_contexts: dict[str, TimeContext] = {}


@dataclass
class TimeMarkerDraft:
    key: str
    title: str
    importance: str
    event_type: str = "time_marker"
    source: str = "time"
    payload: dict = field(default_factory=dict)


def _is_weekend(now: datetime) -> bool:
    return now.weekday() >= 5


def _day_start_draft(now: datetime) -> TimeMarkerDraft:
    return TimeMarkerDraft(
        key=f"time:day_start:{now.date().isoformat()}",
        title="新的一天开始了",
        importance="normal",
        payload={
            "date": now.date().isoformat(),
            "weekday": WEEKDAY_CN[now.weekday()],
            "is_weekend": _is_weekend(now),
        },
    )


def _day_close_draft(day) -> TimeMarkerDraft:
    return TimeMarkerDraft(
        key=f"time:day_close:{day.isoformat()}",
        title="今天结束了",
        importance="low",
        payload={"date": day.isoformat()},
    )


def _part_transition_draft(date_value, from_part: str, to_part: str) -> TimeMarkerDraft:
    return TimeMarkerDraft(
        key=f"time:part:{date_value.isoformat()}:{to_part}",
        title="时段变化",
        importance="low",
        payload={"date": date_value.isoformat(), "from_part": from_part, "to_part": to_part},
    )


def _week_boundary_draft(now: datetime) -> TimeMarkerDraft:
    iso = now.isocalendar()
    return TimeMarkerDraft(
        key=f"time:week:{iso[0]}-W{iso[1]:02d}",
        title="新的一周",
        importance="low",
        payload={"iso_year": iso[0], "iso_week": iso[1]},
    )


def compute_due_markers(
    prev: TimeContext | None,
    curr: TimeContext,
) -> list[TimeMarkerDraft]:
    """纯函数：对比相邻两次观测产出候选标记；冷启动只发 day_start。"""
    from app.character.asuna.calendar import holiday_of, season_of

    drafts: list[TimeMarkerDraft] = []
    if prev is None:
        drafts.append(_day_start_draft(curr.now))
        return drafts
    prev_day = prev.now.date()
    curr_day = curr.now.date()
    if curr_day != prev_day:
        drafts.append(_day_close_draft(prev_day))
        drafts.append(_day_start_draft(curr.now))
        if season_of(curr_day) != season_of(prev_day):
            drafts.append(
                TimeMarkerDraft(
                    key=f"time:season:{curr_day.isoformat()}",
                    title="季节更替",
                    importance="low",
                    payload={"date": curr_day.isoformat(), "season": season_of(curr_day)},
                )
            )
        holiday = holiday_of(curr_day)
        if holiday is not None:
            drafts.append(
                TimeMarkerDraft(
                    key=f"calendar:{curr_day.isoformat()}",
                    title=f"今天是{holiday['name']}",
                    importance="normal",
                    event_type="calendar_event",
                    source="calendar",
                    payload={
                        "date": curr_day.isoformat(),
                        "name": holiday["name"],
                        "kind": holiday["kind"],
                    },
                )
            )
        if curr.part_of_day != prev.part_of_day:
            drafts.append(
                _part_transition_draft(curr_day, prev.part_of_day, curr.part_of_day)
            )
    elif curr.part_of_day != prev.part_of_day:
        drafts.append(_part_transition_draft(curr_day, prev.part_of_day, curr.part_of_day))
    if (curr.now.isocalendar()[0], curr.now.isocalendar()[1]) != (
        prev.now.isocalendar()[0],
        prev.now.isocalendar()[1],
    ):
        drafts.append(_week_boundary_draft(curr.now))
    return drafts


def emit_time_markers(user_id: str, now: datetime | None = None) -> list[str]:
    """发射层：比对上次观测 → 幂等落库；返回本次发出的标记键。"""
    from app.application import world_engine

    try:
        world = world_repository.ensure_world(user_id)
        if world is None:
            return []
        curr = world_engine._default_provider.context(world)
        prev = _last_contexts.get(user_id)
        candidates = compute_due_markers(prev, curr)
        keys = [draft.key for draft in candidates]
        fired = world_simulation_repository.get_latest_idempotency_keys(world.world_id, keys)
        emitted: list[str] = []
        for draft in candidates:
            if draft.key in fired:
                continue
            created = world_engine.create_event(
                user_id,
                event_type=draft.event_type,
                title=draft.title,
                importance=draft.importance,
                source=draft.source,
                status="completed",
                payload=draft.payload,
                idempotency_key=draft.key,
            )
            if created is not None:
                emitted.append(draft.key)
        _last_contexts[user_id] = curr
        return emitted
    except Exception:
        logger.exception("日循环标记发射失败")
        return []


def reset_observation(user_id: str) -> None:
    _last_contexts.pop(user_id, None)
