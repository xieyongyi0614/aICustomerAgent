"""V2.2.0 CHAR-002：情绪 → 表达约束的确定性映射。

只读 character_state 与 state_engine 的情绪/衰减结果做翻译；
不修改 update_emotion / apply_emotion_decay 的任何数学。
"""

from app.character.asuna.emotion_expression import EMOTION_TONES
from app.models.character_state import CharacterState
from app.models.style_contract import EmotionExpression, ExpressionIntensity

SUBTLE_INTENSITY_MAX = 0.3
NATURAL_INTENSITY_MAX = 0.6


def expression_intensity_tier(intensity: float) -> ExpressionIntensity:
    if intensity <= SUBTLE_INTENSITY_MAX:
        return "subtle"
    if intensity <= NATURAL_INTENSITY_MAX:
        return "natural"
    return "rich"


def build_emotion_expression(
    character_state: CharacterState, intensity_boost: float = 0.0
) -> EmotionExpression:
    entry = EMOTION_TONES.tones[character_state.mood]
    effective_intensity = min(
        max(character_state.intensity + intensity_boost, 0.0), 1.0
    )
    return EmotionExpression(
        channel_bias=entry.channel_bias,
        tone_directive=entry.tone_directive,
        expression_intensity=expression_intensity_tier(effective_intensity),
    )


def describe_transition(before: CharacterState, after: CharacterState) -> str:
    if before.mood == after.mood:
        if before.intensity == after.intensity:
            return ""
        return (
            f"{after.mood}"
            f"（{before.intensity:.2f}→{after.intensity:.2f}）"
        )
    return (
        f"{before.mood} → {after.mood}"
        f"（{before.intensity:.2f}→{after.intensity:.2f}）"
    )
