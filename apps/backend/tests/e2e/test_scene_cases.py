import asyncio
import time

import pytest

from app.application import post_process
from app.repositories import scene_state_repository
from app.application import chat_pipeline as agent_service
@pytest.fixture(autouse=True)
def _no_ledger_confirmation(monkeypatch):
    """本文件测 V3 场景连续性；PLA-010 账本确认挂接复用同一 pending_action 槽位，
    会顶掉场景 pending（时序竞态），在此关掉该步保持被测语义单一。"""
    handlers = tuple(
        h for h in post_process.STEP_HANDLERS if h.__name__ != "run_ledger_confirmation"
    )
    monkeypatch.setattr(post_process, "STEP_HANDLERS", handlers)


def _structured(intent="continue_scene", action_decision=None):
    return {
        "RoleMode": {
            "mode": "immersive",
            "intent": "roleplay",
            "confidence": 0.9,
            "reason": "rp",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "daily"},
            "behavior": {"behavior": "normal_reply", "reason": ""},
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "",
            "inner_state": "",
            "current_topic": "",
        },
        "SceneIntentResult": {"intent": intent, "confidence": 0.9, "reason": "x"},
        "SceneActionDecision": action_decision
        or {
            "location": None,
            "current_activity": None,
            "current_action": None,
            "new_pending_action": None,
            "pending_action_done": False,
            "pending_action_cancel": False,
        },
    }


def _new_pending(action):
    return {
        "location": None,
        "current_activity": None,
        "current_action": None,
        "new_pending_action": action,
        "pending_action_done": False,
        "pending_action_cancel": False,
    }


def _prompt_text(llm):
    chunks = []
    for messages in llm.seen_messages:
        for message in messages:
            chunks.append(str(getattr(message, "content", message)))
    return "".join(chunks)


async def _run(llm, session_id, content):
    events = []
    async for event in agent_service.stream_chat(session_id, "u", content, llm=llm):
        events.append(event)
    return events


async def _await_scene(session_id, predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = scene_state_repository.get_scene_state(session_id)
        if predicate(state):
            return state
        await asyncio.sleep(0.02)
    return scene_state_repository.get_scene_state(session_id)


async def test_case1_action_continuity(db_session_factory, fake_llm):
    session_id = "s-c1"
    first = fake_llm(
        response=["好，我去切。"],
        structured_responses=_structured("request_action", _new_pending("切西瓜")),
    )
    await _run(first, session_id, "给我切一块西瓜")
    await _await_scene(session_id, lambda s: s.pending_action is not None)

    second = fake_llm(
        response=["*把切好的西瓜拿回来。*", "给你。"],
        structured_responses=_structured("continue_scene"),
    )
    events = await _run(second, session_id, "好的")
    meta = events[0]
    assert meta["scene_intent"].intent == "continue_scene"
    assert meta["scene_state"].pending_action.action == "切西瓜"
    assert "先完成待完成动作" in _prompt_text(second)

    state = await _await_scene(session_id, lambda s: s.pending_action is not None)
    assert state.pending_action.action == "切西瓜"


async def test_case2_user_correction(db_session_factory, fake_llm):
    session_id = "s-c2"
    first = fake_llm(
        response=["好，我去切。"],
        structured_responses=_structured("request_action", _new_pending("切西瓜")),
    )
    await _run(first, session_id, "给我切一块西瓜")
    await _await_scene(session_id, lambda s: s.pending_action is not None)

    second = fake_llm(
        response=["啊，抱歉，我这就拿给你。"],
        structured_responses=_structured("correct_scene"),
    )
    events = await _run(second, session_id, "你还没拿给我呢")
    meta = events[0]
    assert meta["scene_intent"].intent == "correct_scene"
    assert "必须先执行" in _prompt_text(second)

    state = await _await_scene(session_id, lambda s: s.pending_action is not None)
    assert state.pending_action.status == "pending"


async def test_case4_topic_switch(db_session_factory, fake_llm):
    session_id = "s-c4"
    first = fake_llm(
        response=["好，我去切。"],
        structured_responses=_structured("request_action", _new_pending("切西瓜")),
    )
    await _run(first, session_id, "给我切一块西瓜")
    await _await_scene(session_id, lambda s: s.pending_action is not None)

    second = fake_llm(
        response=["今天吗？还挺开心的。"],
        structured_responses=_structured("chat"),
    )
    events = await _run(second, session_id, "你今天开心吗")
    meta = events[0]
    assert meta["scene_intent"].intent == "chat"
    prompt = _prompt_text(second)
    assert "必须先执行" not in prompt
    assert "先完成待完成动作" not in prompt

    state = await _await_scene(session_id, lambda s: s.pending_action is not None)
    assert state.pending_action.action == "切西瓜"


async def test_case5_consecutive_actions_supersede(db_session_factory, fake_llm):
    session_id = "s-c5"
    first = fake_llm(
        response=["好，我去拿。"],
        structured_responses=_structured("request_action", _new_pending("拿水")),
    )
    await _run(first, session_id, "给我拿瓶水")
    await _await_scene(session_id, lambda s: s.pending_action is not None)

    second = fake_llm(
        response=["好，再拿苹果。"],
        structured_responses=_structured("request_action", _new_pending("拿苹果")),
    )
    await _run(second, session_id, "再拿个苹果过来")
    state = await _await_scene(
        session_id,
        lambda s: s.pending_action is not None
        and s.pending_action.action == "拿苹果",
    )
    assert state.pending_action.action == "拿苹果"


async def test_case6_no_user_action_snatching(db_session_factory, fake_llm):
    llm = fake_llm(response=["我今天很开心。"], structured_responses=_structured())
    await _run(llm, "s-c6", "随便聊聊")
    prompt = _prompt_text(llm)
    assert "不替用户行动" in prompt
    assert "禁止“你接过”" in prompt


async def test_case7_reply_length_bounds(db_session_factory, fake_llm):
    llm = fake_llm(response=["嗯，好。"], structured_responses=_structured())
    await _run(llm, "s-c7", "你好")
    prompt = _prompt_text(llm)
    assert "0~2 个角色动作" in prompt
    assert "0~2 句角色台词" in prompt


async def test_case3_user_cancel(db_session_factory, fake_llm):
    session_id = "s-c3"
    first = fake_llm(
        response=["好，我去切。"],
        structured_responses=_structured("request_action", _new_pending("切西瓜")),
    )
    await _run(first, session_id, "给我切一块西瓜")
    await _await_scene(session_id, lambda s: s.pending_action is not None)

    second = fake_llm(
        response=["嗯，好的，那不切了。"],
        structured_responses=_structured("interrupt"),
    )
    events = await _run(second, session_id, "算了，不用了")
    assert events[0]["scene_state"].pending_action.status == "cancelled"
    state = await _await_scene(
        session_id,
        lambda s: s.pending_action is not None
        and s.pending_action.status == "cancelled",
    )
    assert state.pending_action.status == "cancelled"
