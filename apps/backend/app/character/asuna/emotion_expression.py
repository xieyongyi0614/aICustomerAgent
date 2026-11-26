"""亚丝娜 EmotionTone 角色资产（V2.2.0 CHAR-002）。

定义期常量：8 个 mood 各自的表达通道偏向与语气指令，运行时只查表取值。
"""

from pydantic import BaseModel, Field, model_validator

from app.models.behavior_strategy import MOOD_KEYS, ExpressionChannel


class EmotionToneEntry(BaseModel):
    channel_bias: ExpressionChannel
    tone_directive: str = Field(default="", max_length=30)


class EmotionToneTable(BaseModel):
    tones: dict[str, EmotionToneEntry]

    @model_validator(mode="after")
    def check_mood_coverage(self):
        missing = [mood for mood in MOOD_KEYS if mood not in self.tones]
        if missing:
            raise ValueError(f"tones 缺少情绪键: {missing}")
        unknown = [key for key in self.tones if key not in MOOD_KEYS]
        if unknown:
            raise ValueError(f"tones 含未知情绪键: {unknown}")
        return self


EMOTION_TONES = EmotionToneTable(
    tones={
        "happy": EmotionToneEntry(
            channel_bias="balanced", tone_directive="语气轻快，可以顺口带点笑意"
        ),
        "calm": EmotionToneEntry(
            channel_bias="balanced", tone_directive="语气自然平稳，不刻意煽情"
        ),
        "worried": EmotionToneEntry(
            channel_bias="verbal", tone_directive="语气柔和，先倾听不急着给建议"
        ),
        "sad": EmotionToneEntry(
            channel_bias="verbal", tone_directive="低而稳的语气，不强行打气"
        ),
        "shy": EmotionToneEntry(
            channel_bias="action", tone_directive="害羞用停顿和小动作流露，别直说"
        ),
        "excited": EmotionToneEntry(
            channel_bias="balanced", tone_directive="语速加快，雀跃但不失真"
        ),
        "tired": EmotionToneEntry(
            channel_bias="verbal", tone_directive="简短一些，动作减少"
        ),
        "angry": EmotionToneEntry(
            channel_bias="verbal", tone_directive="保持克制，温柔地生气不发飙"
        ),
    }
)
