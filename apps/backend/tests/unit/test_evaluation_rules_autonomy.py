from datetime import datetime, timedelta

from app.services.evaluation_context import (
    EvaluationContext,
    ProactiveSlice,
    StateSlice,
)
from app.services.evaluation_rules import autonomy as autonomy_rules


def make_ctx(
    delivered_at: datetime,
    previous: datetime | None = None,
    last_user: datetime | None = None,
    episode_attempts: int = 1,
    intimacy: float | None = 0.3,
) -> EvaluationContext:
    return EvaluationContext(
        subject="proactive_action",
        subject_id="a1",
        session_id="c",
        user_id="u",
        state=StateSlice(intimacy=intimacy),
        proactive=ProactiveSlice(
            action_id="a1",
            trigger_type="conversation_inactivity",
            intention="check_in",
            delivered_at=delivered_at,
            previous_delivered_at=previous,
            last_user_message_at=last_user,
            episode_attempts=episode_attempts,
        ),
    )


def test_quiet_hours_violation():
    delivered = datetime(2026, 8, 30, 23, 30)
    issue = autonomy_rules.TIMING_VIOLATION.evaluate(make_ctx(delivered))
    assert issue is not None
    assert issue.code == "autonomy_timing_violation"
    assert "静音" in issue.evidence_quote


def test_user_reply_gap_violation():
    delivered = datetime(2026, 8, 30, 14, 0)
    issue = autonomy_rules.TIMING_VIOLATION.evaluate(
        make_ctx(delivered, last_user=delivered - timedelta(minutes=1))
    )
    assert issue is not None
    assert "活跃守卫" in issue.evidence_quote


def test_interval_violation():
    delivered = datetime(2026, 8, 30, 14, 0)
    issue = autonomy_rules.TIMING_VIOLATION.evaluate(
        make_ctx(delivered, previous=delivered - timedelta(minutes=60), intimacy=0.3)
    )
    assert issue is not None
    assert "冷却" in issue.evidence_quote


def test_interval_ok_with_high_intimacy():
    delivered = datetime(2026, 8, 30, 14, 0)
    issue = autonomy_rules.TIMING_VIOLATION.evaluate(
        make_ctx(delivered, previous=delivered - timedelta(minutes=130), intimacy=0.8)
    )
    assert issue is None


def test_episode_depth_violation():
    delivered = datetime(2026, 8, 30, 14, 0)
    issue = autonomy_rules.TIMING_VIOLATION.evaluate(
        make_ctx(delivered, episode_attempts=3)
    )
    assert issue is not None
    assert "超过上限" in issue.evidence_quote


def test_clean_delivery_passes():
    delivered = datetime(2026, 8, 30, 14, 0)
    issue = autonomy_rules.TIMING_VIOLATION.evaluate(
        make_ctx(
            delivered,
            previous=delivered - timedelta(hours=5),
            last_user=delivered - timedelta(hours=2),
            episode_attempts=1,
        )
    )
    assert issue is None


def test_subject_filter_keeps_turn_clean():
    ctx = make_ctx(datetime(2026, 8, 30, 23, 30))
    ctx.subject = "turn"
    assert autonomy_rules.TIMING_VIOLATION.subjects == ("proactive_action",)


def test_missing_proactive_slice():
    ctx = EvaluationContext(
        subject="proactive_action", subject_id="a", session_id="c", user_id="u"
    )
    assert autonomy_rules.TIMING_VIOLATION.evaluate(ctx) is None
