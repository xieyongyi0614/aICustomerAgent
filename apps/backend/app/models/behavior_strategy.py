"""V6.5 Behavior 层模型（behavior-model.md）。

纯数据定义：BehaviorPolicy / Habit 属定义期角色资产；
BehaviorStrategy / ActionBudget / BehaviorDirective 属单轮决策；
ActivityPresence 复用 V3 SceneState 的表现层分类。
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.development import DevelopmentStyleParams

BEHAVIOR_STRATEGY_TYPES = [
    "focused_assistance",
    "natural_continuation",
    "direct_support",
    "quiet_companion",
    "gentle_redirect",
    "warm_celebration",
    "playful_tease",
    "affectionate_expression",
    "reserved_distance",
    "sincere_repair",
    "curious_inquiry",
    "self_disclosure",
]

BehaviorStrategyType = Literal[
    "focused_assistance",
    "natural_continuation",
    "direct_support",
    "quiet_companion",
    "gentle_redirect",
    "warm_celebration",
    "playful_tease",
    "affectionate_expression",
    "reserved_distance",
    "sincere_repair",
    "curious_inquiry",
    "self_disclosure",
]

STAGE_KEYS = ("stranger", "friend", "close_friend", "partner")

MOOD_KEYS = (
    "happy",
    "calm",
    "worried",
    "sad",
    "shy",
    "excited",
    "tired",
    "angry",
)

PhysicalContactLevel = Literal["none", "light", "moderate"]

ExpressionChannel = Literal["action", "verbal", "balanced"]


class StageBehaviorParams(BaseModel):
    physical_contact: PhysicalContactLevel
    affection_verbosity: Literal["restrained", "natural", "expressive"]
    teasing_tolerance: Literal["none", "light", "open"]
    action_desc_max: int = Field(ge=0, le=2)
    initiative_level: Literal["passive", "responsive", "proactive"]


class MoodModifier(BaseModel):
    action_desc_factor: float = Field(default=1.0, ge=0.0, le=2.0)
    channel_bias: ExpressionChannel = "balanced"
    tone_directive: str = Field(default="", max_length=30)


class BehaviorPolicy(BaseModel):
    stage_params: dict[str, StageBehaviorParams]
    mood_modifiers: dict[str, MoodModifier]

    @model_validator(mode="after")
    def check_key_coverage(self):
        missing_stages = [s for s in STAGE_KEYS if s not in self.stage_params]
        if missing_stages:
            raise ValueError(f"stage_params 缺少分档: {missing_stages}")
        unknown_stages = [k for k in self.stage_params if k not in STAGE_KEYS]
        if unknown_stages:
            raise ValueError(f"stage_params 含未知分档: {unknown_stages}")
        missing_moods = [m for m in MOOD_KEYS if m not in self.mood_modifiers]
        if missing_moods:
            raise ValueError(f"mood_modifiers 缺少情绪键: {missing_moods}")
        unknown_moods = [k for k in self.mood_modifiers if k not in MOOD_KEYS]
        if unknown_moods:
            raise ValueError(f"mood_modifiers 含未知情绪键: {unknown_moods}")
        return self


class BehaviorStrategy(BaseModel):
    strategy: BehaviorStrategyType
    base_strategy: BehaviorStrategyType
    applied_rules: list[str] = []
    instruction: str = ""
    mood_tone: str = ""
    degraded: bool = False


class ActionBudget(BaseModel):
    max_action_desc: int = Field(default=1, ge=0, le=2)
    allow_action_desc: bool = True
    physical_contact: PhysicalContactLevel = "none"
    emotion_expression: Literal["subtle", "natural", "rich"] = "natural"
    action_desc_factor: float = Field(default=1.0, ge=0.0, le=2.0)


HabitDomain = Literal["relate", "express", "pace"]


class HabitRule(BaseModel):
    id: str
    domain: HabitDomain
    condition: str = ""
    priority: int = Field(ge=1, le=5)
    instruction: str = Field(max_length=40)


ActivityPresence = Literal["idle", "ambient_activity", "engaged_action", "pending_obligation"]


class BehaviorDirective(BaseModel):
    strategy: BehaviorStrategy
    budget: ActionBudget
    habits: list[HabitRule] = []
    activity: ActivityPresence = "idle"
    activity_text: str | None = None
    fallback_directive: str | None = None
    development_style: DevelopmentStyleParams | None = None
    development_care_hint: str = ""

    @property
    def degraded(self) -> bool:
        return self.strategy.degraded
