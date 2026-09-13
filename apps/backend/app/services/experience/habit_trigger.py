"""V2.2.0 CHAR-005：习惯运行时触发判定与优先级合成。

纯函数：按本轮情境（关键词 / 情绪事件 / 冲突状态 / 记忆信号）对生效习惯
清单做规则匹配，0 LLM；同优先级按「更具体条件优先 + 域顺序兜底」消解
（裁决 Q4）。与 behavior_engine.match_habits 并存，不改其行为。
"""

from dataclasses import dataclass, field

from app.character.asuna.habit_triggers import HABIT_TRIGGER_SPECS
from app.models.emotion import TurnAnalysis
from app.models.style_contract import TriggeredHabit
from app.services.behavior_engine import HABIT_MAX_COUNT
from app.services.habit_runtime import load_effective_habits

DOMAIN_ORDER: dict[str, int] = {"relate": 0, "express": 1, "pace": 2}


@dataclass(frozen=True)
class HabitTriggerContext:
    analysis: TurnAnalysis = field(default_factory=TurnAnalysis)
    conflict_status: str = "none"
    user_message: str = ""
    memory_present: bool = False


def _keyword_hits(keywords: tuple[str, ...], message: str) -> int:
    return sum(1 for keyword in keywords if keyword in message)


def _match_spec(spec, context: HabitTriggerContext) -> tuple[bool, int]:
    analysis = context.analysis
    hits = _keyword_hits(spec.keywords, context.user_message)
    situation_matched = (
        analysis.user_emotion.emotion in spec.user_emotions
        or analysis.user_emotion.event in spec.user_events
        or analysis.emotion_event.type in spec.emotion_events
        or context.conflict_status in spec.conflict_statuses
        or (spec.memory_present and context.memory_present)
    )
    return hits > 0 or situation_matched, hits


def trigger_habits(context: HabitTriggerContext) -> list[TriggeredHabit]:
    ranked: list[tuple[tuple, str]] = []
    by_id = {habit.id: habit for habit in load_effective_habits()}
    for habit_id, habit in by_id.items():
        spec = HABIT_TRIGGER_SPECS.specs.get(habit_id)
        if spec is None:
            continue
        matched, hits = _match_spec(spec, context)
        if not matched:
            continue
        order_key = (
            habit.priority,
            -hits,
            DOMAIN_ORDER.get(habit.domain, len(DOMAIN_ORDER)),
            habit_id,
        )
        ranked.append((order_key, habit_id))
    ranked.sort(key=lambda item: item[0])
    return [
        TriggeredHabit(
            rule_id=habit_id,
            priority=by_id[habit_id].priority,
            instruction=by_id[habit_id].instruction,
        )
        for _, habit_id in ranked[:HABIT_MAX_COUNT]
    ]
