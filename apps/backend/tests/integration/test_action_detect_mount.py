"""V9-002 H-A1 检出挂载集成测试：turn_meta 条件增键与开关守门。"""

import json

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.main import app


def _structured():
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "ok"},
        "TurnAnalysis": {
            "user_emotion": {"emotion": "neutral", "event": "daily"},
            "behavior": {"behavior": "normal_reply", "reason": ""},
        },
    }


@pytest_asyncio.fixture
async def asgi_client(llm_override, fake_llm):
    llm_override(fake_llm(response=["好的"], structured_responses=_structured()))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _turn_meta(lines: list) -> dict:
    payloads = [json.loads(line) if isinstance(line, str) else line for line in lines]
    for item in payloads:
        if item.get("type") == "turn_meta":
            return item
    raise AssertionError("turn_meta 未找到")


@pytest.mark.asyncio
async def test_action_off_no_action_intent_key(asgi_client):
    resp = await asgi_client.post("/api/v1/chat/message", json={"content": "今天心情不错"})
    lines = [line for line in resp.text.splitlines() if line.strip()]
    meta = _turn_meta(lines)
    assert "action_intent" not in meta


@pytest.mark.asyncio
async def test_action_on_detects_intent_in_turn_meta(asgi_client, override_settings):
    override_settings(action_enabled=True)
    resp = await asgi_client.post("/api/v1/chat/message", json={"content": "明天早上8点提醒我开会"})
    lines = [line for line in resp.text.splitlines() if line.strip()]
    meta = _turn_meta(lines)
    assert meta["action_intent"]["action_type"] == "create_reminder"
    assert meta["action_intent"]["confidence"] == "confident"


@pytest.mark.asyncio
async def test_action_on_non_action_message_no_key(asgi_client, override_settings):
    override_settings(action_enabled=True)
    resp = await asgi_client.post("/api/v1/chat/message", json={"content": "今天心情不错"})
    lines = [line for line in resp.text.splitlines() if line.strip()]
    meta = _turn_meta(lines)
    assert "action_intent" not in meta
