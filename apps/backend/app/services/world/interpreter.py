"""V8 World Update Interpreter（world-model.md §4 / object-system.md §5）。

确定性规则：用户消息 + 世界现状 → 世界状态迁移提案。
宁缺毋滥：模糊输入零迁移零建事件；不造事实。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.character.asuna.world import (
    EVENT_IMPORTANCE_DEFAULT,
    EVENT_TYPE_ALIASES,
    LOCATION_ALIASES,
    OBJECT_CREATION_HINTS,
    WEATHER_ALIASES,
)
from app.models.world import World, WorldEvent, WorldObject
from app.services.world.locations import location_name, resolve_location_alias

logger = logging.getLogger(__name__)

TAKE_VERBS = ("拿来", "给我拿", "拿个", "拿一下", "拿点", "帮我拿", "拿")
PUT_VERBS = ("放回", "放进", "收进", "收好", "放去")
CUT_VERBS = ("切开", "切一下", "切了", "切个", "切")
EAT_VERBS = ("吃一口", "吃一块", "尝一块", "吃点", "尝一下", "吃掉", "吃", "喝一口", "喝")
DISCARD_VERBS = ("扔了", "扔掉", "丢掉", "丢了")
BUY_VERBS = ("买个", "买一个", "买了", "买点", "买")
MOVE_PREFIXES = ("去", "回", "到")

COMPLETE_MARKERS = ("完了", "结束", "完成", "考过", "面过")
CANCEL_MARKER = "取消"

EVENT_RELATIVE_DAYS = {"明天": 1, "后天": 2}


@dataclass
class WorldUpdateResult:
    moves: list[tuple[str, str]] = field(default_factory=list)
    state_actions: list[tuple[str, str]] = field(default_factory=list)
    discards: list[str] = field(default_factory=list)
    creations: list[dict] = field(default_factory=list)
    location_move: str | None = None
    environment_updates: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    event_completions: list[str] = field(default_factory=list)
    event_cancellations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _match_entity(message: str, entities: list[WorldObject]) -> WorldObject | None:
    for obj in entities:
        if obj.name in message or any(alias in message for alias in obj.aliases):
            return obj
    return None


QUESTION_HINTS = ("什么", "吗", "呢", "？", "?", "怎么", "哪")


def _resolve_target(message: str, entities: list[WorldObject]) -> WorldObject | None:
    """先按名称匹配；无名称时若恰好只有一个活跃实体，回退到它（指代消解）。

    问句（吃什么/怎么办）不参与回退——宁缺毋滥。
    """
    obj = _match_entity(message, entities)
    if obj is not None or not entities:
        return obj
    if any(hint in message for hint in QUESTION_HINTS):
        return None
    if any(verb in message for verb in CUT_VERBS + EAT_VERBS + DISCARD_VERBS) and len(entities) == 1:
        return entities[0]
    return None


def _negated(message: str, keyword: str) -> bool:
    index = message.find(keyword)
    if index <= 0:
        return False
    window = message[max(0, index - 2) : index]
    return any(neg in window for neg in ("不", "没", "别"))


def _object_lines(message: str, entities: list[WorldObject], world: World, result: WorldUpdateResult) -> None:
    obj = _resolve_target(message, entities)
    if obj is None:
        for verb in BUY_VERBS:
            if verb in message:
                for name, category in OBJECT_CREATION_HINTS.items():
                    if name in message:
                        result.creations.append({"name": name, "category": category, "quantity": 1.0})
                        result.notes.append(f"新买了{name}")
                        return
        return

    current = world.current_location
    take_requested = any(verb in message for verb in TAKE_VERBS)
    if obj.location_id != current and take_requested:
        result.moves.append((obj.id, current))
        origin = location_name(obj.location_id) or obj.location_id
        result.notes.append(f"{obj.name}已从{origin}取出")
        return
    if take_requested:
        result.notes.append(f"{obj.name}就在这里")
        return

    if any(verb in message for verb in PUT_VERBS):
        target = resolve_location_alias(message) or current
        if target != obj.location_id:
            result.moves.append((obj.id, target))
            result.notes.append(f"{obj.name}已收进{location_name(target) or target}")
        return

    if any(verb in message for verb in DISCARD_VERBS):
        result.discards.append(obj.id)
        result.notes.append(f"{obj.name}已处理掉")
        return

    for verb in CUT_VERBS:
        if verb in message:
            result.state_actions.append((obj.id, "cut"))
            return

    for verb in EAT_VERBS:
        if verb in message:
            result.state_actions.append((obj.id, "eat"))
            return


def _location_move(message: str, world: World, result: WorldUpdateResult) -> None:
    for alias in sorted(LOCATION_ALIASES, key=len, reverse=True):
        for prefix in MOVE_PREFIXES:
            if f"{prefix}{alias}" in message:
                target = resolve_location_alias(alias)
                if target and target != world.current_location:
                    result.location_move = target
                return


def _event_lines(message: str, events: list[WorldEvent], now: datetime, result: WorldUpdateResult) -> None:
    matched_types = [
        (alias, event_type)
        for alias, event_type in EVENT_TYPE_ALIASES.items()
        if alias in message
    ]
    for alias, event_type in matched_types:
        if CANCEL_MARKER in message:
            result.event_cancellations.append(event_type)
            result.notes.append(f"{alias}已取消")
            continue
        if any(marker in message for marker in COMPLETE_MARKERS):
            result.event_completions.append(event_type)
            result.notes.append(f"{alias}完成了")
            continue
        due_at = _resolve_due(message, now)
        if due_at is None:
            continue
        result.events.append(
            {
                "type": event_type,
                "title": f"用户的{alias}",
                "importance": EVENT_IMPORTANCE_DEFAULT.get(event_type, "normal"),
                "due_at": due_at,
            }
        )
        result.notes.append(f"记下了：{alias}")


def _resolve_due(message: str, now: datetime) -> datetime | None:
    for keyword, days in EVENT_RELATIVE_DAYS.items():
        if keyword in message:
            base = (now + timedelta(days=days)).replace(hour=10, minute=0, second=0, microsecond=0)
            if "下午" in message:
                base = base.replace(hour=14)
            if "晚上" in message:
                base = base.replace(hour=19)
            return base
    if "今晚" in message or ("今天" in message and "晚上" in message):
        return now.replace(hour=20, minute=0, second=0, microsecond=0)
    return None


def _environment(message: str, result: WorldUpdateResult) -> None:
    for keyword, value in WEATHER_ALIASES.items():
        if keyword in message and not _negated(message, keyword):
            result.environment_updates["weather"] = value
            return


def interpret(
    message: str,
    world: World,
    entities: list[WorldObject],
    events: list[WorldEvent],
    now: datetime,
) -> WorldUpdateResult:
    result = WorldUpdateResult()
    try:
        _object_lines(message, entities, world, result)
        _location_move(message, world, result)
        _event_lines(message, events, now, result)
        _environment(message, result)
    except Exception:
        logger.exception("世界解释失败，本轮零迁移")
        return WorldUpdateResult(notes=result.notes)
    return result
