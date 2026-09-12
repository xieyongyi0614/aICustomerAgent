"""未启用零路径（FEISHU-006 §12.4）：FEISHU_ENABLED=false → 四类计数全 0 + Web 路径不受影响。"""

from httpx import ASGITransport, AsyncClient

import pytest

from app.channels.feishu import client as feishu_client
from app.channels.feishu import events
from app.channels.feishu import delivery
from app.channels.feishu import adapter
from app.core.db import ChannelIdentityRow, Conversation
from app.main import app
from app.services import agent_service


@pytest.fixture(autouse=True)
def _reset_state(override_settings):
    override_settings(feishu_enabled=False)
    events.reset_event_state()
    delivery.reset_delivery_state()
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()
    yield
    events.reset_event_state()
    delivery.reset_delivery_state()
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()


@pytest.mark.asyncio
async def test_disabled_webhook_404_and_all_counters_zero(
    override_settings, monkeypatch, db_session_factory
):
    stream_calls = []

    async def _stream(*args, **kwargs):
        stream_calls.append(1)
        yield {"kind": "token", "text": "x"}

    monkeypatch.setattr(agent_service, "stream_chat", _stream)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/feishu/events",
            content=b'{"header": {"token": "x"}, "event": {}}',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 404

    assert feishu_client._transport is None
    assert feishu_client.token_view().has_token is False
    assert stream_calls == []
    with db_session_factory() as session:
        assert session.query(ChannelIdentityRow).count() == 0
        assert session.query(Conversation).count() == 0


@pytest.mark.asyncio
async def test_disabled_web_chat_still_works(
    override_settings, monkeypatch, db_session_factory, llm_override, fake_llm
):
    llm_override(
        fake_llm(
            response=["你好"],
            structured_responses={
                "RoleMode": {
                    "mode": "default",
                    "intent": "casual",
                    "confidence": 0.9,
                    "reason": "hi",
                },
                "MemoryExtraction": {"candidates": []},
            },
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/message", json={"content": "在吗"}
        )
    assert response.status_code == 200
    assert feishu_client._transport is None


def test_disabled_settings_load_without_error(override_settings):
    override_settings(feishu_enabled=False)
    from app.core.settings import get_settings

    settings = get_settings()
    assert settings.feishu_enabled is False
