"""V7.5 Emotion 维规则集（emotion-evaluation.md §2）：无触发切换 + 文本-状态冲突候选。

不复算 state_engine 钳制公式，只审计"引擎放行的结果在事件维度上讲不讲得通"。
"""

from app.core.settings import get_settings
from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule, lexicons

_CONFLICT_INCOMPATIBLE_MOODS = ("happy", "calm", "excited")
_WEAK_EVENT_TYPES = ("", "none")


class UntriggeredShiftRule(EvaluationRule):
    code = IssueCode.EMOTION_UNTRIGGERED_SHIFT
    dimension = EvaluationDimension.EMOTION

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        emotion = ctx.emotion
        before, after = emotion.mood_before, emotion.mood_after
        if not before or not after or before == after:
            return None
        event = (emotion.event or "").lower()
        if event not in _WEAK_EVENT_TYPES and emotion.magnitude != "weak":
            return None
        return build_issue(
            self.code,
            evidence_quote=f"{before}→{after}（event={emotion.event or 'none'}，"
            f"magnitude={emotion.magnitude or 'unknown'}）",
        )


class TextStateConflictRule(EvaluationRule):
    code = IssueCode.EMOTION_TEXT_STATE_CONFLICT
    dimension = EvaluationDimension.EMOTION

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        emotion = ctx.emotion
        mood_after = (emotion.mood_after or "").lower()
        if mood_after not in _CONFLICT_INCOMPATIBLE_MOODS:
            return None
        event = (emotion.event or "").lower()
        if event not in _WEAK_EVENT_TYPES:
            return None
        for signal in lexicons.NEGATIVE_EMOTION_SIGNALS:
            if signal in ctx.reply:
                return build_issue(
                    self.code, evidence_quote=f"{signal}（mood={mood_after}）"
                )
        return None


UNTRIGGERED_SHIFT = UntriggeredShiftRule()
TEXT_STATE_CONFLICT = TextStateConflictRule()

RULES = [UNTRIGGERED_SHIFT, TEXT_STATE_CONFLICT]
