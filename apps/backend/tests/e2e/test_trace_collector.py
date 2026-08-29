import asyncio
import time

import pytest

from app.core.settings import get_settings
from app.main import app
from app.services import agent_service
from app.services import trace_collector as tc_module
from app.services.trace_collector import TraceCollector, TurnTraceSession, get_trace_collector
from tests.conftest import wait_until


def _structured(**overrides):
    payload = {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "achievement"},
            "behavior": {"behavior": "celebrate", "reason": "用户达成成就"},
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "好消息",
            "inner_state": "开心",
            "current_topic": "项目上线",
        },
    }
    payload.update(overrides)
    return payload


async def _run_turn(llm, content="我今天把项目上线了"):
    events = []
    async for event in agent_service.stream_chat(
        f"s-trace-{id(llm)}", "default-user", content, llm=llm
    ):
        events.append(event)
    return events


def _step(session, name):
    return next(s for s in session.steps if s.name == name)


async def _await_until(predicate, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_full_turn_records_all_steps_and_completes(db_session_factory, fake_llm):
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm)

    done = events[-1]
    assert done["kind"] == "done"
    turn_id = done["turn_id"]

    collector = get_trace_collector()
    assert await _await_until(
        lambda: (lambda s: s is not None and s.is_complete)(collector.get(turn_id))
    )
    session = collector.get(turn_id)
    assert session is not None
    names = {s.name for s in session.steps}
    expected = {
        "context_builder",
        "role_router",
        "turn_analyzer",
        "memory_retrieval",
        "prompt_builder",
        "llm",
        "state_update",
        "memory_extractor",
    }
    assert expected <= names, names

    llm_step = _step(session, "llm")
    assert llm_step.status == "ok"
    assert llm_step.first_token_ms is not None and llm_step.first_token_ms >= 0

    meta_event = events[0]
    assert meta_event["kind"] == "turn_meta"
    snapshot = session.snapshot()
    assert snapshot["role_mode"] == meta_event["role_mode"].model_dump()
    assert snapshot["analysis"] == meta_event["analysis"].model_dump()
    assert snapshot["status"] == "complete"

    assert wait_until(lambda: collector.get(turn_id).is_complete)


@pytest.mark.asyncio
async def test_degraded_paths_marked_in_steps(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured(),
        structured_errors={
            "RoleMode": RuntimeError("router boom"),
            "TurnAnalysis": RuntimeError("analyzer boom"),
            "StateUpdateDecision": RuntimeError("updater boom"),
        },
    )
    events = await _run_turn(llm)
    turn_id = events[-1]["turn_id"]

    def _refreshed():
        return get_trace_collector().get(turn_id)

    assert await _await_until(
        lambda: _refreshed() is not None
        and "state_update" in {x.name for x in _refreshed().steps}
    )
    statuses = {x.name: x.status for x in _refreshed().steps}
    assert statuses["role_router"] == "degraded"
    assert statuses["turn_analyzer"] == "degraded"
    assert statuses["state_update"] == "degraded"


def test_snapshot_shape_and_pending_status():
    session = get_trace_collector().begin_trace()
    assert session.turn_id is None
    session.record("llm", 12.3456, first_token_ms=1.23456)
    snapshot = session.snapshot()
    assert snapshot["status"] == "pending"
    assert snapshot["steps"][0] == {
        "name": "llm",
        "status": "ok",
        "durationMs": 12.35,
        "firstTokenMs": 1.23,
        "error": None,
    }


def test_lru_evicts_oldest_turn_beyond_capacity(monkeypatch):
    collector = get_trace_collector()
    collector._finished.clear()

    sessions = [collector.begin_trace() for _ in range(3)]
    for i, session in enumerate(sessions[:2]):
        collector.attach(session, f"t-{i}")

    monkeypatch.setattr(get_settings(), "trace_capacity", 1)
    collector.attach(sessions[2], "t-2")

    assert collector.get("t-0") is None
    assert collector.get("t-1") is None
    assert collector.get("t-2") is not None


def test_unknown_turn_returns_none():
    assert get_trace_collector().get("no-such-turn") is None


@pytest.mark.asyncio
async def test_debug_trace_endpoint_unknown_404_then_snapshot(
    db_session_factory, fake_llm
):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/v1/debug/turns/no-such/trace")
        assert missing.status_code == 404

        llm = fake_llm(response=["好耶"], structured_responses=_structured())
        events = await _run_turn(llm)
        turn_id = events[-1]["turn_id"]

        resp = await client.get(f"/api/v1/debug/turns/{turn_id}/trace")
        assert resp.status_code == 200
        body = resp.json()
        assert body["turn_id"] == turn_id
        assert body["status"] in ("pending", "complete")

        deadline = time.time() + 3.0
        while time.time() < deadline:
            body = (await client.get(f"/api/v1/debug/turns/{turn_id}/trace")).json()
            if body["status"] == "complete":
                break
            await asyncio.sleep(0.05)
        assert body["status"] == "complete"
        names = {step["name"] for step in body["steps"]}
        assert {"llm", "state_update", "memory_extractor"} <= names


def test_trace_has_request_id_and_usage_accumulation():
    session = TurnTraceSession()
    assert len(session.request_id) == 32
    session.add_token_usage({"input_tokens": 10, "output_tokens": 5})
    session.add_token_usage({"input_tokens": 7, "output_tokens": 3})
    assert session.token_usage == {"input_tokens": 17, "output_tokens": 8}
    snapshot = session.snapshot()
    assert snapshot["request_id"] == session.request_id
    assert snapshot["token_usage"] == {"input_tokens": 17, "output_tokens": 8}


def test_pending_trace_queryable_by_turn_id_after_attach():
    collector = TraceCollector()
    session = collector.begin_trace()
    session.turn_id = "turn-pending"
    collector._pending[session._pending_key] = session
    assert collector.get("turn-pending") is session
