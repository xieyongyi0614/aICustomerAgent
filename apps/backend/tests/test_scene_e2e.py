import asyncio
import time

from app.repositories import scene_state_repository
from app.services import agent_service
from app.services.trace_collector import get_trace_collector


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
        "MemoryDecision": {
            "should_save": False,
            "memory": None,
            "memory_type": "preference",
            "importance": 0.0,
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


async def test_pending_action_persists_across_turns(db_session_factory, fake_llm):
    session_id = "s-e2e-1"
    llm = fake_llm(
        response=["好，我去切。"],
        structured_responses=_structured(
            "request_action",
            action_decision={
                "location": None,
                "current_activity": None,
                "current_action": "切西瓜",
                "new_pending_action": "切西瓜",
                "pending_action_done": False,
                "pending_action_cancel": False,
            },
        ),
    )
    events = await _run(llm, session_id, "给我切一块西瓜")
    meta = events[0]
    assert meta["kind"] == "turn_meta"
    assert meta["scene_intent"].intent == "request_action"

    state = await _await_scene(session_id, lambda s: s.pending_action is not None)
    assert state.pending_action.action == "切西瓜"
    assert state.pending_action.status == "pending"
    assert state.current_action == "切西瓜"


async def test_continue_scene_keeps_pending_and_trace_has_scene_steps(
    db_session_factory, fake_llm
):
    session_id = "s-e2e-2"
    first = fake_llm(
        response=["好，我去切。"],
        structured_responses=_structured(
            "request_action",
            action_decision={
                "location": None,
                "current_activity": None,
                "current_action": "切西瓜",
                "new_pending_action": "切西瓜",
                "pending_action_done": False,
                "pending_action_cancel": False,
            },
        ),
    )
    await _run(first, session_id, "给我切一块西瓜")
    await _await_scene(session_id, lambda s: s.pending_action is not None)

    second = fake_llm(
        response=["*把切好的西瓜拿回来。*", "给你。"],
        structured_responses=_structured("continue_scene"),
    )
    events = await _run(second, session_id, "好的")
    turn_id = events[-1]["turn_id"]
    meta = events[0]
    assert meta["scene_intent"].intent == "continue_scene"
    assert meta["scene_state"].pending_action.action == "切西瓜"

    state = await _await_scene(session_id, lambda s: s.pending_action is not None)
    assert state.pending_action.action == "切西瓜"

    def _refreshed():
        return get_trace_collector().get(turn_id)

    deadline = time.time() + 3.0
    while time.time() < deadline and (
        _refreshed() is None or not _refreshed().is_complete
    ):
        await asyncio.sleep(0.02)
    session = _refreshed()
    assert session is not None
    names = {s.name for s in session.steps}
    assert {"scene_intent", "scene_resolver", "scene_update"} <= names


async def test_interrupt_cancels_pending_through_pipeline(db_session_factory, fake_llm):
    session_id = "s-e2e-3"
    first = fake_llm(
        response=["好，我去切。"],
        structured_responses=_structured(
            "request_action",
            action_decision={
                "location": None,
                "current_activity": None,
                "current_action": None,
                "new_pending_action": "切西瓜",
                "pending_action_done": False,
                "pending_action_cancel": False,
            },
        ),
    )
    await _run(first, session_id, "给我切一块西瓜")
    await _await_scene(session_id, lambda s: s.pending_action is not None)

    second = fake_llm(
        response=["嗯，好的，那不切了。"],
        structured_responses=_structured("interrupt"),
    )
    events = await _run(second, session_id, "算了，不用了")
    meta = events[0]
    assert meta["scene_intent"].intent == "interrupt"
    assert meta["scene_state"].pending_action.status == "cancelled"

    state = await _await_scene(
        session_id,
        lambda s: s.pending_action is not None
        and s.pending_action.status == "cancelled",
    )
    assert state.pending_action.status == "cancelled"
