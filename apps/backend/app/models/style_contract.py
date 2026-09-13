"""V2.2.0 Character Experience 层模型（CHAR-001）。

纯值对象：StyleContract 及其子结构，作为 Experience Layer 四路信号
（Emotion / Personality / Relationship / Habit）的统一汇流点。
不落表（审计随 runtime_traces）、无 IO、无 LLM、不依赖任何域服务。
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

AddressingTerm = Literal["respectful", "name", "affectionate", "intimate"]
AddressingTone = Literal["polite", "natural", "warm", "affectionate"]
AddressingInitiative = Literal["passive", "responsive", "proactive", "devoted"]
EmotionExpressiveness = Literal["restrained", "natural", "open"]

ExpressionChannel = Literal["action", "verbal", "balanced"]
ExpressionIntensity = Literal["subtle", "natural", "rich"]

ADDRESSING_TERM_LABELS: dict[str, str] = {
    "respectful": "敬称",
    "name": "名字",
    "affectionate": "昵称",
    "intimate": "专属称呼",
}

ADDRESSING_TONE_LABELS: dict[str, str] = {
    "polite": "客气体贴",
    "natural": "自然",
    "warm": "亲昵",
    "affectionate": "带撒娇",
}

ADDRESSING_INITIATIVE_LABELS: dict[str, str] = {
    "passive": "被动，只接话",
    "responsive": "正常响应",
    "proactive": "主动关心",
    "devoted": "主动惦记",
}

ADDRESSING_EXPRESSIVENESS_LABELS: dict[str, str] = {
    "restrained": "克制",
    "natural": "自然",
    "open": "放开",
}

EXPRESSION_CHANNEL_LABELS: dict[str, str] = {
    "action": "偏动作表达",
    "verbal": "偏语言表达",
    "balanced": "动作与语言平衡",
}

EXPRESSION_INTENSITY_LABELS: dict[str, str] = {
    "subtle": "淡淡地流露",
    "natural": "自然地流露",
    "rich": "浓烈地流露",
}

PERSONALITY_AXIS_KEYS = ("assertiveness", "warmth", "curiosity", "patience")

PERSONALITY_AXIS_HIGH_LABELS: dict[str, str] = {
    "assertiveness": "有主见，敢直接给建议",
    "warmth": "关心外显",
    "curiosity": "好奇，会追问",
    "patience": "先倾听再说",
}

PERSONALITY_AXIS_LOW_LABELS: dict[str, str] = {
    "assertiveness": "不抢话，少替对方拿主意",
    "warmth": "关心收敛在内",
    "curiosity": "不追问",
    "patience": "直入话题",
}

_PERSONALITY_NEUTRAL_BAND = (0.3, 0.7)


class Addressing(BaseModel):
    term: AddressingTerm = "name"
    tone: AddressingTone = "natural"
    initiative: AddressingInitiative = "responsive"
    emotion_expressiveness: EmotionExpressiveness = "natural"

    def prompt_lines(self) -> list[str]:
        lines = []
        if self.term != "name":
            lines.append(f"称呼：{ADDRESSING_TERM_LABELS[self.term]}")
        if self.tone != "natural":
            lines.append(f"语气：{ADDRESSING_TONE_LABELS[self.tone]}")
        if self.initiative != "responsive":
            lines.append(f"主动程度：{ADDRESSING_INITIATIVE_LABELS[self.initiative]}")
        if self.emotion_expressiveness != "natural":
            lines.append(
                f"情绪表达：{ADDRESSING_EXPRESSIVENESS_LABELS[self.emotion_expressiveness]}"
            )
        return lines


class EmotionExpression(BaseModel):
    channel_bias: ExpressionChannel = "balanced"
    tone_directive: str = Field(default="", max_length=30)
    expression_intensity: ExpressionIntensity = "natural"

    def prompt_lines(self) -> list[str]:
        lines = []
        if self.channel_bias != "balanced":
            lines.append(f"表达通道：{EXPRESSION_CHANNEL_LABELS[self.channel_bias]}")
        if self.tone_directive:
            lines.append(f"语气：{self.tone_directive}")
        if self.expression_intensity != "natural":
            lines.append(
                f"情绪强度：{EXPRESSION_INTENSITY_LABELS[self.expression_intensity]}"
            )
        return lines


class PersonalityModulation(BaseModel):
    assertiveness: float = Field(default=0.3, ge=0.0, le=1.0)
    warmth: float = Field(default=0.8, ge=0.0, le=1.0)
    curiosity: float = Field(default=0.6, ge=0.0, le=1.0)
    patience: float = Field(default=0.7, ge=0.0, le=1.0)
    baseline: dict[str, float] = {}
    bound: dict[str, float] = {}

    @model_validator(mode="after")
    def check_axis_metadata(self):
        for meta_name in ("baseline", "bound"):
            meta = getattr(self, meta_name)
            unknown = [key for key in meta if key not in PERSONALITY_AXIS_KEYS]
            if unknown:
                raise ValueError(f"{meta_name} 含未知人格轴: {unknown}")
            out_of_range = {
                key: value for key, value in meta.items() if not 0.0 <= value <= 1.0
            }
            if out_of_range:
                raise ValueError(f"{meta_name} 轴值越界: {out_of_range}")
        return self

    def axis_value(self, axis: str) -> float:
        return getattr(self, axis)

    def prompt_lines(self) -> list[str]:
        low, high = _PERSONALITY_NEUTRAL_BAND
        parts = []
        for axis in PERSONALITY_AXIS_KEYS:
            value = self.axis_value(axis)
            if value < low:
                parts.append(PERSONALITY_AXIS_LOW_LABELS[axis])
            elif value > high:
                parts.append(PERSONALITY_AXIS_HIGH_LABELS[axis])
        if not parts:
            return []
        return ["人格基调：" + "、".join(parts)]


class TriggeredHabit(BaseModel):
    rule_id: str = ""
    priority: int = Field(default=3, ge=1, le=5)
    instruction: str = Field(default="", max_length=40)


class StyleContract(BaseModel):
    addressing: Addressing = Addressing()
    emotion_constraint: EmotionExpression = EmotionExpression()
    personality_modulation: PersonalityModulation = PersonalityModulation()
    habits: list[TriggeredHabit] = []
    forbidden: list[str] = []
    principles: list[str] = []
    style_hint: str = ""

    def prompt_lines(self) -> list[str]:
        lines: list[str] = []
        if self.addressing != Addressing():
            lines.extend(self.addressing.prompt_lines())
        if self.emotion_constraint != EmotionExpression():
            lines.extend(self.emotion_constraint.prompt_lines())
        if self.personality_modulation != PersonalityModulation():
            lines.extend(self.personality_modulation.prompt_lines())
        for habit in self.habits:
            lines.append(f"习惯：{habit.instruction}")
        for item in self.forbidden:
            lines.append(f"禁止：{item}")
        for item in self.principles:
            lines.append(f"原则：{item}")
        return lines

    def build_style_hint(self) -> str:
        parts: list[str] = []
        emotion = self.emotion_constraint
        if emotion.tone_directive:
            parts.append(emotion.tone_directive)
        elif emotion.expression_intensity != "natural":
            parts.append(EXPRESSION_INTENSITY_LABELS[emotion.expression_intensity])
        if self.addressing.tone != "natural":
            parts.append(ADDRESSING_TONE_LABELS[self.addressing.tone])
        if self.addressing.term != "name":
            parts.append(ADDRESSING_TERM_LABELS[self.addressing.term])
        if self.addressing.initiative != "responsive":
            parts.append(ADDRESSING_INITIATIVE_LABELS[self.addressing.initiative])
        if self.habits:
            parts.append(self.habits[0].instruction)
        return "、".join(parts) if parts else "自然"
