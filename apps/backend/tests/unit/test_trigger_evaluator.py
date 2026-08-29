"""V7-004：conversation_inactivity 触发判定（testing.md Case 1~3）。"""

from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.services.trigger_evaluator import SessionTail, evaluate_inactivity

NOW = datetime(2026, 8, 30, 14, 0)
CONFIG = get_settings()


def test_case1_idle_beyond_threshold_triggers():
    tail = SessionTail(
        last_message_at=NOW - timedelta(minutes=35),
        last_message_role="human",
        last_user_message_at=NOW - timedelta(minutes=35),
        last_user_message_id="42",
    )
    signal = evaluate_inactivity(tail, "u1", now=NOW, config=CONFIG)
    assert signal is not None
    assert signal.type == "conversation_inactivity"
    assert signal.dedupe_key == "inactivity:u1:42"
    assert signal.context["idle_minutes"] == 35.0


def test_case1_below_threshold_no_signal():
    tail = SessionTail(
        last_message_at=NOW - timedelta(minutes=10),
        last_message_role="human",
        last_user_message_at=NOW - timedelta(minutes=10),
        last_user_message_id="42",
    )
    assert evaluate_inactivity(tail, "u1", now=NOW, config=CONFIG) is None


def test_case2_user_just_replied_no_signal():
    tail = SessionTail(
        last_message_at=NOW - timedelta(seconds=30),
        last_message_role="human",
        last_user_message_at=NOW - timedelta(seconds=30),
        last_user_message_id="42",
    )
    assert evaluate_inactivity(tail, "u1", now=NOW, config=CONFIG) is None


def test_case3_empty_session_no_signal():
    assert evaluate_inactivity(SessionTail(), "u1", now=NOW, config=CONFIG) is None


def test_episode_limit_blocks_signal():
    tail = SessionTail(
        last_message_at=NOW - timedelta(minutes=35),
        last_message_role="human",
        last_user_message_at=NOW - timedelta(minutes=35),
        last_user_message_id="42",
    )
    signal = evaluate_inactivity(tail, "u1", episode_attempts=2, now=NOW, config=CONFIG)
    assert signal is None


def test_seen_dedupe_key_blocks_signal():
    tail = SessionTail(
        last_message_at=NOW - timedelta(minutes=35),
        last_message_role="human",
        last_user_message_at=NOW - timedelta(minutes=35),
        last_user_message_id="42",
    )
    signal = evaluate_inactivity(
        tail, "u1", seen_keys={"inactivity:u1:42"}, now=NOW, config=CONFIG
    )
    assert signal is None


def test_ai_last_message_still_triggers_for_cooldown_layer():
    tail = SessionTail(
        last_message_at=NOW - timedelta(minutes=35),
        last_message_role="ai",
        last_user_message_at=NOW - timedelta(minutes=60),
        last_user_message_id="40",
    )
    signal = evaluate_inactivity(tail, "u1", now=NOW, config=CONFIG)
    assert signal is not None
    assert signal.context["last_role"] == "ai"


def test_new_episode_resets_dedupe():
    tail = SessionTail(
        last_message_at=NOW - timedelta(minutes=35),
        last_message_role="human",
        last_user_message_at=NOW - timedelta(minutes=35),
        last_user_message_id="43",
    )
    signal = evaluate_inactivity(
        tail, "u1", seen_keys={"inactivity:u1:42"}, now=NOW, config=CONFIG
    )
    assert signal is not None
    assert signal.dedupe_key == "inactivity:u1:43"
