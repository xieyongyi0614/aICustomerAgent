"""V9-002 ActionIntentDetector 单测（planner.md §1）。"""

from datetime import datetime

import pytest

from app.services.action.detector import detect_action_intent

NOW = datetime(2026, 9, 3, 14, 0, 0)


@pytest.fixture
def action_on(override_settings):
    override_settings()
    yield


def test_detector_gate_off_returns_none(override_settings):
    override_settings(action_detector_enabled=False)
    assert detect_action_intent("提醒我开会", now=NOW) is None


def test_no_action_message(action_on):
    assert detect_action_intent("今天心情不错", now=NOW) is None


def test_create_reminder_confident(action_on):
    intent = detect_action_intent("明天早上8点提醒我开会", now=NOW)
    assert intent is not None
    assert intent.action_type == "create_reminder"
    assert intent.confidence == "confident"
    assert intent.params["content"] == "开会"
    assert datetime.fromisoformat(intent.params["due_at"]) == datetime(2026, 9, 4, 8, 0)


def test_create_reminder_ambiguous_without_due(action_on):
    intent = detect_action_intent("提醒我开会", now=NOW)
    assert intent is not None
    assert intent.confidence == "ambiguous"
    assert "due_at" in intent.missing_params


def test_question_guard(action_on):
    assert detect_action_intent("你能提醒我吗", now=NOW) is None


def test_narration_guard(action_on):
    assert detect_action_intent("我昨天提醒过你要早睡", now=NOW) is None


def test_remember_fact(action_on):
    intent = detect_action_intent("记住我生日是7月30日", now=NOW)
    assert intent is not None
    assert intent.action_type == "remember_fact"
    assert intent.confidence == "confident"
    assert "7月30日" in intent.params["fact"]


def test_create_object(action_on):
    intent = detect_action_intent("帮我买牛奶", now=NOW)
    assert intent is not None
    assert intent.action_type == "create_object"
    assert intent.params["object"] == "牛奶"


def test_move_object(action_on):
    intent = detect_action_intent("把牛奶放到冰箱里", now=NOW)
    assert intent is not None
    assert intent.action_type == "move_object"
    assert intent.params["object"] == "牛奶"
    assert "冰箱" in intent.params["location"]


def test_query_environment(action_on):
    intent = detect_action_intent("今天天气怎么样", now=NOW)
    assert intent is not None
    assert intent.action_type == "query_environment"
    assert intent.confidence == "confident"


def test_query_search(action_on):
    intent = detect_action_intent("帮我搜一下亚丝娜是谁", now=NOW)
    assert intent is not None
    assert intent.action_type == "query_search"
    assert intent.params["query"] == "亚丝娜是谁"


def test_single_intent_priority(action_on):
    intent = detect_action_intent("帮我买牛奶并且提醒我喝", now=NOW)
    assert intent is not None
    assert intent.action_type == "create_reminder"


def test_dedupe_key_stable(action_on):
    a = detect_action_intent("明天早上8点提醒我开会", now=NOW)
    b = detect_action_intent("明天早上8点提醒我开会", now=NOW)
    assert a.dedupe_key == b.dedupe_key


def test_ledger_spend_phrase_records(action_on):
    """消费动词 + 金额的组合判定要覆盖「花费 X 买 Y」这类日常说法。"""
    intent = detect_action_intent("今天花费10块钱买鸡蛋", now=NOW)
    assert intent is not None
    assert intent.action_type == "record_ledger_entry"


def test_ledger_buy_with_amount_records(action_on):
    intent = detect_action_intent("早上买了豆浆10块", now=NOW)
    assert intent is not None
    assert intent.action_type == "record_ledger_entry"


def test_ledger_buy_without_amount_is_not_recording(action_on):
    assert detect_action_intent("帮我买牛奶", now=NOW).action_type == "create_object"
