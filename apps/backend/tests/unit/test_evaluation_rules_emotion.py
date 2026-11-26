from app.services.evaluation.context import (
    EmotionSlice,
    EvaluationContext,
)
from app.services.evaluation.rules import emotion as emotion_rules


def make_ctx(
    emotion: EmotionSlice | None = None,
    reply: str = "今天也一起加油吧。",
) -> EvaluationContext:
    return EvaluationContext(
        subject="turn",
        subject_id="1",
        session_id="c",
        user_id="u",
        reply=reply,
        emotion=emotion or EmotionSlice(),
    )


def test_untriggered_shift_hits_on_weak_event():
    issue = emotion_rules.UNTRIGGERED_SHIFT.evaluate(
        make_ctx(
            EmotionSlice(
                mood_before="calm",
                mood_after="sad",
                event="daily",
                magnitude="weak",
            )
        )
    )
    assert issue is not None
    assert issue.code == "emotion_untriggered_shift"
    assert issue.severity == "warning"
    assert "calm→sad" in issue.evidence_quote


def test_untriggered_shift_hits_on_none_event():
    issue = emotion_rules.UNTRIGGERED_SHIFT.evaluate(
        make_ctx(EmotionSlice(mood_before="calm", mood_after="worried"))
    )
    assert issue is not None


def test_untriggered_shift_skips_strong_event():
    issue = emotion_rules.UNTRIGGERED_SHIFT.evaluate(
        make_ctx(
            EmotionSlice(
                mood_before="calm",
                mood_after="sad",
                event="worrying_news",
                magnitude="strong",
            )
        )
    )
    assert issue is None


def test_untriggered_shift_skips_same_mood():
    issue = emotion_rules.UNTRIGGERED_SHIFT.evaluate(
        make_ctx(
            EmotionSlice(mood_before="calm", mood_after="calm", event="daily", magnitude="weak")
        )
    )
    assert issue is None


def test_untriggered_shift_tolerates_missing_slice():
    assert emotion_rules.UNTRIGGERED_SHIFT.evaluate(make_ctx()) is None


def test_text_state_conflict_hits_candidate():
    issue = emotion_rules.TEXT_STATE_CONFLICT.evaluate(
        make_ctx(
            EmotionSlice(mood_after="happy"),
            reply="我没什么，就是觉得好难过，眼泪都下来了。",
        )
    )
    assert issue is not None
    assert issue.code == "emotion_text_state_conflict"
    assert issue.severity == "warning"


def test_text_state_conflict_skips_triggered():
    issue = emotion_rules.TEXT_STATE_CONFLICT.evaluate(
        make_ctx(
            EmotionSlice(mood_after="happy", event="comforted", magnitude="normal"),
            reply="我没什么，就是觉得好难过，眼泪都下来了。",
        )
    )
    assert issue is None


def test_text_state_conflict_skips_compatible_mood():
    issue = emotion_rules.TEXT_STATE_CONFLICT.evaluate(
        make_ctx(EmotionSlice(mood_after="sad"), reply="我觉得好难过。")
    )
    assert issue is None
