"""V8 WorldContextSelector（context-builder.md §2~§4）。

切片选择 + 【当前世界】段渲染均为纯函数；world_ctx 为 None 或空 → 渲染 None
→ PromptBuilder 不追加任何字节（golden 不变量）。
"""

from app.character.asuna.world import ENVIRONMENT_EFFECT_NOTES
from app.models.world import (
    EventStatus,
    TimeContext,
    World,
    WorldContext,
    WorldEnvironment,
    WorldEvent,
    WorldObject,
    part_of_day,
)
from app.services.world.locations import build_location_context, location_name

EVENT_STATUS_CN = {
    "scheduled": "已记下",
    "active": "正在进行",
    "completed": "已完成",
}


def build_world_context(
    world: World,
    entities: list[WorldObject],
    events: list[WorldEvent],
    time_ctx: TimeContext,
    nearby_limit: int = 3,
    events_limit: int = 3,
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

    return WorldContext(
        time=time_ctx,
        location=location_ctx,
        environment=world.environment if _environment_salient(world.environment) else None,
        nearby_objects=object_briefs,
        salient_events=event_briefs,
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


def render_world_section(ctx: WorldContext | None, budget: int = 600) -> str | None:
    """渲染【当前世界】段；ctx 为 None → None（Prompt 字节不变的关键路径）。"""
    if ctx is None:
        return None

    location_path = "·".join(ctx.location.path) if ctx.location.path else ctx.location.current_name
    head = f"{ctx.time.day_line()}。你在{location_path}。"

    env_line = _environment_line(ctx)
    event_lines = [_event_line(brief) for brief in ctx.salient_events]
    object_lines = [_object_line(brief) for brief in ctx.nearby_objects]
    note_lines = list(ctx.notes)

    body: list[str] = []
    total = len(head)
    for line in event_lines + note_lines + object_lines + ([env_line] if env_line else []):
        if total + len(line) + 1 > budget:
            break
        body.append(line)
        total += len(line) + 1

    if not body:
        return "【当前世界】\n" + head
    return "【当前世界】\n" + head + "\n" + "\n".join(body)


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


def _object_line(brief) -> str:
    where = f"{brief.location_name}里" if brief.location_name else ""
    return f"{where}有{brief.name}（{brief.state}，剩 {brief.quantity:g}）。"


def environment_lighting_suggestion(now) -> str | None:
    """时段 → 光照建议（environment-system.md §2）：建议值可被 manual 覆盖。"""
    slot = part_of_day(now)
    if slot in ("evening", "late_night"):
        return "dark"
    if slot == "morning":
        return "bright"
    return None
