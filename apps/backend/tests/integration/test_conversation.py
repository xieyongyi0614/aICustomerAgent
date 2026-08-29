import pytest

from app.repositories import conversation_repository as repo
from app.services import conversation_service as svc


def test_context_across_turns(db_session_factory):
    svc.save_turn("s1", "我在学 LangGraph", "很棒")
    svc.save_turn("s1", "今天刚学 Runnable", "继续")
    window = svc.load_window("s1")
    assert [m.content for m in window] == ["我在学 LangGraph", "很棒", "今天刚学 Runnable", "继续"]


def test_session_isolation(db_session_factory):
    svc.save_turn("a", "hello", "hi")
    svc.save_turn("b", "world", "yo")
    window_a = svc.load_window("a")
    assert [m.content for m in window_a] == ["hello", "hi"]


def test_window_limit(db_session_factory):
    for i in range(23):
        svc.save_turn("s3", f"q{i}", f"a{i}")
    window = svc.load_window("s3", max_messages=20)
    assert len(window) == 20
    assert window[0].content == "q13"
    assert window[-1].content == "a22"


def test_char_budget_drops_oldest(db_session_factory):
    long_msg = "x" * 9000
    svc.save_turn("s4", long_msg, "reply")
    svc.save_turn("s4", "second", "ok")
    window = svc.load_window("s4", max_chars=8000)
    total = sum(len(m.content) for m in window)
    assert total <= 8000
    assert window[0].content != long_msg


def test_save_turn_writes_two_rows(db_session_factory):
    svc.save_turn("s5", "u", "a")
    assert repo.count_messages("s5") == 2


def test_illegal_role_rejected(db_session_factory):
    with pytest.raises(ValueError):
        repo.save_message("s6", "bot", "bad")
    assert repo.count_messages("s6") == 0


def test_get_or_create_idempotent(db_session_factory):
    first = svc.ensure_conversation("s7", "u1")
    second = svc.ensure_conversation("s7", "u1")
    assert first.id == second.id == "s7"
