"""V7-006：AutonomyEngine + Executor（testing.md Case 8~10）。

时间注入 + FakeLLM 全确定；validate 提供消息/动作断言。
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.application.chat_pipeline import active_generations
from app.application.post_process import reset_user_write_locks
from app.models.autonomy import ProactiveAction
from app.repositories import conversation_repository, proactive_repository
from app.services.conversation import service as conversation_service
from app.services.autonomy import executor as proactive_executor
from app.services.observability.collector import TurnTraceSession

NOW = datetime(2026, 8, 30, 14, 0)


def _action(session_id: str = "s1", **overrides) -> ProactiveAction:
    payload = {
        "id": uuid.uuid4().hex,
        "user_id": "default-user",
        "session_id": session_id,
        "trigger_type": "conversation_inactivity",
        "dedupe_key": f"inactivity:default-user:{uuid.uuid4().hex}",
        "goal_id": None,
        "intention": "check_in",
        "reason": "闲置关心",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return ProactiveAction(**payload)


@pytest.fixture(autouse=True)
def _clean_state():
    reset_user_write_locks()
    autonomy_engine.reset_episode("default-user")
    yield
    active_generations.clear()
    reset_user_write_locks()


def _seed_session(db_session_factory, user_id="default-user", session_id="s1"):
    conversation_repository.get_or_create_conversation(session_id, user_id)
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧")
    return session_id


def test_case9_generate_and_deliver(db_session_factory, fake_llm):
    _seed_session(db_session_factory)
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    action = _action()
    assert proactive_repository.enqueue(action) is True
    active = proactive_repository.get_active("default-user", now=NOW)
    trace = TurnTraceSession()
    delivered = asyncio_run(
        proactive_executor.execute(active, llm=llm, trace=trace, now=NOW)
    )
    assert delivered is not None and delivered.status == "delivered"
    assert delivered.message_id is not None
    assert delivered.payload_text == "忙完了吗？记得喝口水。"
    messages = conversation_service.load_window("s1", max_messages=5)
    assert messages[-1].content == "忙完了吗？记得喝口水。"
    assert [s.name for s in trace.steps][-1] == "proactive_deliver"


def test_case10_generating_marker_rolls_back_to_candidate(
    db_session_factory, fake_llm
):
    _seed_session(db_session_factory)
    llm = fake_llm(response=["嗯"])
    action = _action()
    proactive_repository.enqueue(action)
    active = proactive_repository.get_active("default-user", now=NOW)
    active_generations["default-user"] = True
    result = asyncio_run(proactive_executor.execute(active, llm=llm, now=NOW))
    assert result is not None and result.status == "candidate"
    messages = conversation_service.load_window("s1", max_messages=5)
    assert messages[-1].role == "ai"
    assert messages[-1].content == "好的，去吧"


def test_case12_llm_failure_retries_then_terminal(db_session_factory, fake_llm):
    _seed_session(db_session_factory)
    llm = fake_llm(response=["   "])
    action = _action()
    proactive_repository.enqueue(action)
    active = proactive_repository.get_active("default-user", now=NOW)
    result = asyncio_run(proactive_executor.execute(active, llm=llm, now=NOW))
    assert result is not None and result.status == "failed"
    assert result.attempt == 1
    assert result.next_retry_at is not None

    due = proactive_repository.get_active("default-user", now=NOW + timedelta(hours=1))
    retried = asyncio_run(proactive_executor.execute(due, llm=llm, now=NOW + timedelta(hours=1)))
    assert retried is not None and retried.status == "failed"
    assert retried.attempt == 2
    assert retried.next_retry_at is None

    from app.core.settings import get_settings

    assert get_settings().autonomy_max_retries == 2


def test_case12_goal_vanished_discards_via_retry_path(db_session_factory, fake_llm):
    _seed_session(db_session_factory)
    llm = fake_llm(response=["嗯"])
    action = _action(goal_id="missing-goal")
    proactive_repository.enqueue(action)
    active = proactive_repository.get_active("default-user", now=NOW)
    result = asyncio_run(proactive_executor.execute(active, llm=llm, now=NOW))
    assert result is not None and result.status == "failed"


def test_case11_user_message_resets_pending(db_session_factory, fake_llm):
    _seed_session(db_session_factory)
    action = _action()
    proactive_repository.enqueue(action)
    proactive_repository.transition(action.id, "approved", now=NOW)
    conversation_service.save_turn("s1", "我回来了", "欢迎回来")
    conversation_service.reset_proactive_on_user_message("default-user")
    assert proactive_repository.get_by_id(action.id).status == "discarded"
    assert proactive_repository.has_non_terminal("default-user") is False


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
