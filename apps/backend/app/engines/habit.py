"""V6.5-011 动态 Habit 机制（habit-system.md §6）。

候选生成走代码规则（事件计数 → 模板表），禁止 LLM 直写；
候选不自动生效，生效集 = HABIT_LIST（只读资产）+ HABIT_EXTRA_JSON（人工审核后配置，变更即审计）。
"""

import json
import logging
from collections import Counter

from app.character.asuna.habits import HABIT_LIST
from app.core.settings import get_settings
from app.models.behavior_strategy import HabitRule

logger = logging.getLogger(__name__)

HABIT_CANDIDATE_TEMPLATES: dict[str, dict] = {
    "conflict": {
        "id": "auto_conflict_cool_down",
        "domain": "relate",
        "priority": 2,
        "instruction": "冲突后先冷静一轮再回应，不在气头上争对错",
    },
    "user_care": {
        "id": "auto_care_followup",
        "domain": "relate",
        "priority": 3,
        "instruction": "关心过的事之后主动跟进一句近况",
    },
    "user_help": {
        "id": "auto_help_concrete",
        "domain": "relate",
        "priority": 3,
        "instruction": "帮忙时给具体可执行的第一步，不给空泛建议",
    },
    "praise": {
        "id": "auto_praise_recall",
        "domain": "express",
        "priority": 4,
        "instruction": "被夸时顺口把功劳带到共同经历上",
    },
}

CANDIDATE_MIN_COUNT = 3


def derive_habit_candidates(events, min_count: int = CANDIDATE_MIN_COUNT) -> list[HabitRule]:
    # 原「排除 memory_replay 派生事件」过滤已随该源值退役删除（2026-10-16）：
    # `RelationshipEventSource` 只剩 conversation / system，账本无派生事件。
    counts = Counter(event.type for event in events)
    candidates: list[HabitRule] = []
    for event_type, template in HABIT_CANDIDATE_TEMPLATES.items():
        if counts.get(event_type, 0) >= min_count:
            candidates.append(HabitRule(**template))
    return candidates


def load_effective_habits() -> list[HabitRule]:
    extras = _parse_extra_json()
    known_ids = {habit.id for habit in HABIT_LIST}
    for extra in extras:
        if extra.id in known_ids:
            raise ValueError(f"HABIT_EXTRA_JSON id 与内置习惯冲突: {extra.id}")
        known_ids.add(extra.id)
    return [*HABIT_LIST, *extras]


def _parse_extra_json() -> list[HabitRule]:
    raw = get_settings().habit_extra_json
    if not raw or raw.strip() == "[]":
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"HABIT_EXTRA_JSON 解析失败: {exc}") from exc
    if not isinstance(items, list):
        raise ValueError("HABIT_EXTRA_JSON 必须是数组")
    return [HabitRule(**item) for item in items]
