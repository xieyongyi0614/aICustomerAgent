import httpx
import openai
import pytest

from app.channels.feishu import adapter
from app.channels.feishu.adapter import FALLBACK_TEXTS, TurnOutcome, reset_feishu_adapter
from app.channels.feishu.identity import FEISHU_CHANNEL
from app.core.settings import get_settings
from app.services import agent_service, channel_identity_service
from app.services.agent_service import EmptyLLMResponseError

EXPECTED_ERROR_KINDS = ("llm_error", "empty_response", "pipeline_error", "identity_error", "overloaded")


@pytest.fixture(autouse=True)
def _reset_adapter_state():
    reset_feishu_adapter()
    yield
    reset_feishu_adapter()


@pytest.fixture(autouse=True)
def _stub_identity(monkeypatch):
    from app.services.channel_identity_service import ResolvedIdentity

    def _resolve(channel, external_id, **kwargs):
        return ResolvedIdentity(
            channel=channel,
            external_id=external_id,
            internal_user_id=f"{channel}:{external_id}",
            session_id=f"{channel}:{external_id}",
            created=True,
        )

    monkeypatch.setattr(channel_identity_service, "resolve", _resolve)


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    monkeypatch.setattr(adapter.llm_factory, "get_llm", lambda profile_id=None: object())


def _inbound(text="你好", open_id="ou_u1", reply_ref="om_1", metadata=None):
    from datetime import datetime, timezone

    from app.channels.base import InboundMessage

    return InboundMessage(
        channel="feishu",
        external_user_id=open_id,
        text=text,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reply_ref=reply_ref,
        metadata=metadata or {},
    )


def _stream_factory(events=None, exc=None, delay=0.0):
    import asyncio

    calls = []

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        calls.append({"session_id": session_id, "user_id": user_id, "content": content})
        if delay:
            await asyncio.sleep(delay)
        if exc is not None:
            raise exc
        for event in events or []:
            yield event

    _stream.calls = calls
    return _stream


def _mount_stream(monkeypatch, **kwargs):
    stream = _stream_factory(**kwargs)
    monkeypatch.setattr(agent_service, "stream_chat", stream)
    return stream


def _api_status_error():
    request = httpx.Request("POST", "https://example.invalid/v1/chat")
    response = httpx.Response(500, request=request)
    return openai.APIStatusError("upstream boom", response=response, body=None)


@pytest.mark.asyncio
async def test_accumulates_tokens_into_outbound_text(monkeypatch):
    _mount_stream(
        monkeypatch,
        events=[
            {"kind": "turn_meta", "role_mode": {"mode": "default"}},
            {"kind": "token", "text": "你"},
            {"kind": "token", "text": "好"},
            {"kind": "token", "text": "呀"},
            {"kind": "done", "session_id": "feishu:ou_u1", "turn_id": "t-1"},
        ],
    )
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.outbound_text == "你好呀"
    assert outcome.error_kind is None
    assert outcome.turn_id == "t-1"
    assert outcome.source_message_ref == "om_1"
    assert outcome.user_id == "feishu:ou_u1"


@pytest.mark.asyncio
async def test_turn_meta_never_leaks_into_outbound_text(monkeypatch):
    meta = {
        "role_mode": {"mode": "immersive"},
        "scene_state": {"location": "kitchen"},
        "behavior": {"behavior": "cook"},
        "action_intent": {"intent": "cook"},
        "analysis": {"emotion": "happy"},
    }
    events = [{"kind": "turn_meta", **meta}, {"kind": "token", "text": "回复"}, {"kind": "done", "turn_id": "t"}]
    _mount_stream(monkeypatch, events=events)
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.outbound_text == "回复"
    for key in ("role_mode", "scene_state", "behavior", "action_intent", "analysis", "turn_meta"):
        assert key not in (outcome.outbound_text or "")


@pytest.mark.asyncio
async def test_unknown_event_kind_ignored(monkeypatch):
    _mount_stream(
        monkeypatch,
        events=[
            {"kind": "future_event", "payload": {"x": 1}},
            {"kind": "token", "text": "ok"},
            {"kind": "done", "turn_id": "t"},
        ],
    )
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.outbound_text == "ok"


@pytest.mark.asyncio
async def test_empty_accumulation_becomes_fallback(monkeypatch):
    _mount_stream(monkeypatch, events=[{"kind": "done", "turn_id": "t"}])
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "empty_response"
    assert outcome.outbound_text == FALLBACK_TEXTS["empty_response"]
    assert outcome.outbound_text.strip()


@pytest.mark.asyncio
async def test_whitespace_only_accumulation_becomes_fallback(monkeypatch):
    _mount_stream(
        monkeypatch,
        events=[
            {"kind": "token", "text": "  "},
            {"kind": "token", "text": "\n"},
            {"kind": "done", "turn_id": "t"},
        ],
    )
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "empty_response"


@pytest.mark.asyncio
async def test_empty_llm_response_error_mapped(monkeypatch):
    _mount_stream(monkeypatch, exc=EmptyLLMResponseError("empty"))
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "empty_response"
    assert outcome.outbound_text == FALLBACK_TEXTS["empty_response"]


@pytest.mark.asyncio
async def test_api_status_error_mapped_without_leaking_details(monkeypatch):
    _mount_stream(monkeypatch, exc=_api_status_error())
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "llm_error"
    assert outcome.outbound_text == FALLBACK_TEXTS["llm_error"]
    assert "500" not in outcome.outbound_text
    assert "APIStatusError" not in outcome.outbound_text


@pytest.mark.asyncio
async def test_generic_exception_mapped(monkeypatch):
    _mount_stream(monkeypatch, exc=ValueError("boom"))
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "pipeline_error"
    assert outcome.outbound_text == FALLBACK_TEXTS["pipeline_error"]
    assert "boom" not in outcome.outbound_text


@pytest.mark.asyncio
async def test_stream_without_done_is_incomplete_but_sent(monkeypatch):
    _mount_stream(monkeypatch, events=[{"kind": "token", "text": "半"}])
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "incomplete"
    assert outcome.outbound_text == "半"


@pytest.mark.asyncio
async def test_stream_without_done_and_no_tokens_is_empty_response(monkeypatch):
    _mount_stream(monkeypatch, events=[])
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "empty_response"


@pytest.mark.asyncio
async def test_identity_failure_short_circuits_pipeline(monkeypatch):
    def _raise(channel, external_id, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(channel_identity_service, "resolve", _raise)
    stream = _mount_stream(monkeypatch, events=[{"kind": "token", "text": "x"}])
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "identity_error"
    assert stream.calls == []


@pytest.mark.asyncio
async def test_pipeline_receives_identity_and_content(monkeypatch):
    stream = _mount_stream(monkeypatch, events=[{"kind": "token", "text": "好"}, {"kind": "done", "turn_id": "t"}])
    await adapter.handle_inbound_message(_inbound(text="在吗", open_id="ou_pass"))
    assert stream.calls == [
        {"session_id": "feishu:ou_pass", "user_id": "feishu:ou_pass", "content": "在吗"}
    ]


@pytest.mark.asyncio
async def test_overload_rejects_without_pipeline(monkeypatch, override_settings):
    import asyncio

    override_settings(feishu_merge_window_ms=0, feishu_session_queue_limit=1)
    release = asyncio.Event()
    calls = []

    async def _blocking(session_id, user_id, content, llm=None, trace=None):
        calls.append(content)
        await release.wait()
        yield {"kind": "token", "text": "x"}
        yield {"kind": "done", "turn_id": "t"}

    monkeypatch.setattr(agent_service, "stream_chat", _blocking)
    delivered = []

    async def _record(outcome):
        delivered.append(outcome)

    monkeypatch.setattr(adapter.delivery, "deliver_reply", _record)

    await adapter.ingest_inbound_message(_inbound(text="first"))
    await asyncio.sleep(0.05)
    await adapter.ingest_inbound_message(_inbound(text="second"))

    assert [outcome.error_kind for outcome in delivered] == ["overloaded"]
    assert delivered[0].outbound_text == FALLBACK_TEXTS["overloaded"]
    assert calls == ["first"]

    release.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_slot_released_after_pipeline_exception(monkeypatch):
    _mount_stream(monkeypatch, exc=ValueError("boom"))
    first = await adapter.handle_inbound_message(_inbound())
    assert first.error_kind == "pipeline_error"
    _mount_stream(monkeypatch, events=[{"kind": "token", "text": "恢复"}, {"kind": "done", "turn_id": "t2"}])
    second = await adapter.handle_inbound_message(_inbound())
    assert second.outbound_text == "恢复"


def test_fallback_text_table_complete_and_human():
    for kind in EXPECTED_ERROR_KINDS:
        text = FALLBACK_TEXTS[kind]
        assert text.strip()
        for banned in ("{", "}", "Traceback", "Error", "Exception"):
            assert banned not in text, (kind, banned)


def test_turn_outcome_is_frozen():
    outcome = TurnOutcome(session_id="s", user_id="u", outbound_text="x")
    with pytest.raises(Exception):
        outcome.outbound_text = "y"
