"""亚丝娜 HabitTrigger 角色资产（V2.2.0 CHAR-005）。

定义期常量：habit_id → 触发关键词与情境标签；运行时只查表匹配，0 LLM。
"""

from pydantic import BaseModel, model_validator

from app.character.asuna.habits import HABIT_LIST

_HABIT_IDS = frozenset(habit.id for habit in HABIT_LIST)


class HabitTriggerSpec(BaseModel):
    keywords: tuple[str, ...] = ()
    user_emotions: tuple[str, ...] = ()
    user_events: tuple[str, ...] = ()
    emotion_events: tuple[str, ...] = ()
    conflict_statuses: tuple[str, ...] = ()
    memory_present: bool = False


class HabitTriggerSpecTable(BaseModel):
    specs: dict[str, HabitTriggerSpec]

    @model_validator(mode="after")
    def check_known_habit_ids(self):
        unknown = [habit_id for habit_id in self.specs if habit_id not in _HABIT_IDS]
        if unknown:
            raise ValueError(f"specs 含未知习惯 id: {unknown}")
        return self


HABIT_TRIGGER_SPECS = HabitTriggerSpecTable(
    specs={
        "habit_care_action_first": HabitTriggerSpec(
            keywords=(
                "累",
                "生病",
                "不舒服",
                "感冒",
                "熬夜",
                "加班",
                "辛苦",
                "头疼",
                "发烧",
                "没吃饭",
            ),
            user_emotions=("tired",),
            user_events=("seek_help",),
        ),
        "habit_comfort_companion_first": HabitTriggerSpec(
            keywords=(
                "累",
                "难过",
                "伤心",
                "压力",
                "崩溃",
                "委屈",
                "想哭",
                "失落",
                "被骂",
                "搞砸",
            ),
            user_emotions=("sad", "anxious"),
            user_events=("setback", "complaint"),
        ),
        "habit_angry_restrained": HabitTriggerSpec(
            keywords=("你真差劲", "都怪你", "烦死了", "闭嘴"),
            emotion_events=("criticized", "conflict"),
            conflict_statuses=("conflict", "cold"),
        ),
        "habit_happy_tease": HabitTriggerSpec(
            keywords=("哈哈", "太好笑了"),
            emotion_events=("praise", "teased", "funny_moment", "warm_moment"),
            user_emotions=("happy", "excited"),
        ),
        "habit_listen_before_speak": HabitTriggerSpec(
            user_emotions=("sad", "anxious", "angry", "tired"),
            emotion_events=("worrying_news",),
        ),
        "habit_question_bounded": HabitTriggerSpec(
            keywords=("？", "?", "怎么办", "怎么选", "该不该", "帮我看看"),
        ),
        "habit_memory_light_touch": HabitTriggerSpec(
            memory_present=True,
        ),
    }
)
