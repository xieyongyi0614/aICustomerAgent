"""V8 WorldContextSelector（context-builder.md §2~§4）。

切片选择 + 【当前世界】段渲染均为纯函数；world_ctx 为 None 或空 → 渲染 None
→ PromptBuilder 不追加任何字节（golden 不变量）。
ACTION-005：从 character_action 事件派生「最近世界变化」行（有界、去重）。
"""

from datetime import datetime

from app.character.asuna.world import ENVIRONMENT_EFFECT_NOTES
from app.models.world import (
    EventStatus,
    InventoryItem,
    TimeContext,
    World,
    WorldContext,
    WorldEnvironment,
    WorldEvent,
    WorldObject,
    part_of_day,
    usage_cost,
)
from app.services.world.locations import build_location_context, location_name

EVENT_STATUS_CN = {
    "scheduled": "已记下",
    "active": "正在进行",
    "completed": "已完成",
}


def recent_world_changes_from_events(events: list[WorldEvent], limit: int = 3) -> list[str]:
    if limit <= 0:
        return []
    seen: set[str] = set()
    rows: list[str] = []
    ordered = sorted(
        (event for event in events if event.type == "character_action"),
        key=lambda event: (event.created_at or datetime.fromtimestamp(0)),
        reverse=True,
    )
    for event in ordered:
        if not event.title:
            continue
        dedupe_key = (event.payload or {}).get("dedupe_key")
        if dedupe_key:
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
        rows.append(event.title)
        if len(rows) >= limit:
            break
    return rows


def build_world_context(
    world: World,
    entities: list[WorldObject],
    events: list[WorldEvent],
    time_ctx: TimeContext,
    nearby_limit: int = 3,
    events_limit: int = 3,
    change_events: list[WorldEvent] | None = None,
    changes_limit: int = 3,
) -> WorldContext:
    now = time_ctx.now
    location_ctx = build_location_context(world)

    at_current = [
        obj
        for obj in entities
        if obj.location_id == world.current_location
        or obj.location_id.startswith(world.current_location + ".")
    ]
    nearby = at_current

    object_briefs = []
    for obj in nearby[:nearby_limit]:
        object_briefs.append(
            {
                "name": obj.name,
                "state": obj.state,
                "quantity": obj.quantity,
                "location_name": location_name(obj.location_id),
            }
        )

    salient = []
    for event in events:
        if event.status is EventStatus.ACTIVE:
            salient.append(event)
        elif event.status is EventStatus.SCHEDULED:
            if event.due_at is not None and (event.due_at - now).total_seconds() <= 86400:
                salient.append(event)
            elif event.importance.value == "high":
                salient.append(event)
    salient.sort(key=lambda item: (item.due_at is None, item.due_at))
    event_briefs = [event.brief(now) for event in salient[:events_limit]]

    inventory = []
    for obj in entities:
        props = obj.properties or {}
        inventory.append(
            InventoryItem(
                name=obj.name,
                quantity=obj.quantity,
                unit=obj.unit or "",
                location_id=obj.location_id,
                location_name=location_name(obj.location_id),
                state=obj.state,
                consumable=obj.consumable,
                price_minor=props.get("price_minor"),
                purchased_at=props.get("purchased_at"),
            )
        )

    return WorldContext(
        time=time_ctx,
        location=location_ctx,
        environment=world.environment if _environment_salient(world.environment) else None,
        nearby_objects=object_briefs,
        inventory=inventory,
        salient_events=event_briefs,
        recent_world_changes=recent_world_changes_from_events(change_events or [], changes_limit),
        notes=list(world.notes or []),
    )


def _environment_salient(environment: WorldEnvironment) -> bool:
    return any(
        value is not None
        for value in (
            environment.weather,
            environment.temperature_c,
            environment.lighting,
            environment.noise,
            environment.atmosphere,
        )
    )


def render_world_section(
    ctx: WorldContext | None,
    budget: int = 600,
    brief=None,
    now: datetime | None = None,
) -> str | None:
    """渲染【当前世界】段；ctx 为 None → None（Prompt 字节不变的关键路径）。
    brief（V2.3.0 WorldBrief）非空时其行优先于其余行进入预算。
    now 仅用于「已用天数 / 日均金额」计算（缺省取当前时间）。"""
    if ctx is None:
        return None

    location_path = "·".join(ctx.location.path) if ctx.location.path else ctx.location.current_name
    head = f"{ctx.time.day_line()}。你在{location_path}。"

    env_line = _environment_line(ctx)
    event_lines = [_event_line(event) for event in ctx.salient_events]
    recent_lines = _recent_changes_lines(ctx.recent_world_changes)
    recent_set = set(ctx.recent_world_changes)
    note_lines = [note for note in ctx.notes if note not in recent_set]
    guide_line = (
        "家里的物品、数量、位置以本清单为准，不得凭空捏造或增减；"
        "未列出的物品视为不存在，不得声称拥有或还有。"
    )
    inventory_lines = _inventory_lines(ctx.inventory, now=now)

    brief_lines: list[str] = []
    if brief is not None:
        for line in (brief.time_line, brief.place_line, brief.situations_line, brief.events_line):
            if line:
                brief_lines.append(line)

    body: list[str] = []
    prefix = "【当前世界】\n"
    total = len(prefix) + len(head)
    for line in brief_lines + (
        [guide_line]
        + inventory_lines
        + recent_lines
        + event_lines
        + note_lines
        + ([env_line] if env_line else [])
    ):
        if total + len(line) + 1 > budget:
            break
        body.append(line)
        total += len(line) + 1

    if not body:
        return prefix + head
    return prefix + head + "\n" + "\n".join(body)


def _inventory_lines(items, now: datetime | None = None) -> list[str]:
    grouped: dict = {}
    for item in items:
        grouped.setdefault(item.location_id, []).append(item)
    lines: list[str] = []
    for _, objs in grouped.items():
        loc_name = next((obj.location_name for obj in objs), None) or next(
            (obj.location_id for obj in objs), "未命名"
        )
        lines.append(f"{loc_name}：")
        for obj in objs:
            lines.append(f"  {_inventory_item_line(obj, now=now)}")
    return lines


def _inventory_item_line(item, now: datetime | None = None) -> str:
    qty = int(item.quantity) if item.quantity == int(item.quantity) else f"{item.quantity:g}"
    if item.unit and item.unit not in ("piece", "个"):
        base = f"{item.name} × {qty}{item.unit}"
    else:
        base = f"{item.name} × {qty}"
    cost = usage_cost(item.price_minor, item.purchased_at, now=now)
    if cost is None:
        return base
    return (
        f"{base}（购于 {cost['purchased_at']}，¥{cost['price_minor'] / 100:.2f}，"
        f"已用 {cost['days_used']} 天，日均 ¥{cost['daily_cost_minor'] / 100:.2f}）"
    )


def _recent_changes_lines(rows: list[str]) -> list[str]:
    if not rows:
        return []
    lines = ["最近世界变化："]
    lines.extend(f"  - {row}" for row in rows)
    return lines


def _environment_line(ctx: WorldContext) -> str | None:
    environment = ctx.environment
    if environment is None:
        return None
    parts: list[str] = []
    if environment.weather:
        parts.append(f"外面{'正下着雨' if environment.weather == 'rain' else _weather_word(environment.weather)}")
    if environment.temperature_c is not None:
        parts.append(f"{environment.temperature_c:g}℃")
    if environment.lighting == "dark":
        parts.append("屋里灯光昏暗")
    note = ENVIRONMENT_EFFECT_NOTES.get(environment.weather)
    if note:
        parts.append(note)
    return "，".join(parts) + "。" if parts else None


def _weather_word(weather: str) -> str:
    return {
        "sunny": "是大晴天",
        "cloudy": "阴着天",
        "rain": "正下着雨",
        "snow": "飘着雪",
        "windy": "风很大",
    }.get(weather, weather)


def _event_line(brief) -> str:
    if brief.status == "active":
        return f"{brief.title}正在进行。"
    due = brief.due_in_hours
    if due is not None and 0 <= due <= 24:
        return f"{brief.title}（{brief.importance}，还有 {due:g} 小时）。"
    return f"{brief.title}（已记下）。"


def environment_lighting_suggestion(now) -> str | None:
    """时段 → 光照建议（environment-system.md §2）：建议值可被 manual 覆盖。"""
    slot = part_of_day(now)
    if slot in ("evening", "late_night"):
        return "dark"
    if slot == "morning":
        return "bright"
    return None
