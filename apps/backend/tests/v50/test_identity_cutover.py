"""IDENT-001~008 身份收口专项测试（v5.0.0 §14 / ADR 13）。

口径：
- 产品端点（chat / history / governance / ledger / proactive）无 Bearer token 一律 401；
- token 是唯一身份源：数据落在 token 解出的 user_id 名下，跨用户不可见；
- 全新用户（无 users 行、无任何域数据）首轮对话可完整走通（冷启动空态口径）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_api
from app.main import app
from tests.conftest import FakeLLM

pytestmark = pytest.mark.unit

OWNER = "email-cutover-owner"
STRANGER = "email-cutover-stranger"

_PRODUCT_ENDPOINTS = [
    ("post", "/api/v1/chat/message", {"json": {"content": "你好"}}),
    ("get", "/api/v1/conversations/latest", None),
    ("get", "/api/v1/memories", None),
    ("get", "/api/v1/life/export", None),
    ("delete", "/api/v1/life/data", {"params": {"confirm": "true"}}),
    ("get", "/api/v1/ledger/summary", None),
    ("get", "/api/v1/proactive/pending", None),
    ("get", "/api/v1/llm/profiles", None),
]


@pytest.fixture
def real_auth():
    """移除 conftest 的 require_user override，走真实 token 解析。"""
    app.dependency_overrides.pop(auth_api.require_user, None)
    yield


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_api.issue_token(user_id, 'device-cutover')}"}


def _structured():
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "chat"},
            "behavior": {"behavior": "chat", "reason": "闲聊"},
        },
        "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "ok"},
        "IntentionDecision": {
            "intention": "chat",
            "confidence": 0.9,
            "reason": "ok",
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "日常",
            "inner_state": "平静",
            "current_topic": "问候",
        },
    }


@pytest.mark.parametrize("method,path,kwargs", _PRODUCT_ENDPOINTS)
def test_product_endpoints_require_token(real_auth, method, path, kwargs):
    client = TestClient(app)
    response = getattr(client, method)(path, **(kwargs or {}))
    assert response.status_code == 401


_DEBUG_ENDPOINTS = [
    ("get", "/api/v1/state", None),
    ("get", "/api/v1/debug/world", None),
    ("get", "/api/v1/debug/tools", None),
    ("get", "/api/v1/debug/memory/dbg-cutover/attribution", None),
    ("get", "/api/v1/debug/traces", None),
    ("get", "/api/v1/debug/relationship/state", None),
    ("get", "/api/v1/debug/plans", None),
    ("get", "/api/v1/debug/actions", None),
    ("get", "/api/v1/debug/action-execution/actions", None),
]


@pytest.mark.parametrize("method,path,kwargs", _DEBUG_ENDPOINTS)
def test_debug_surface_requires_token(real_auth, method, path, kwargs):
    """默认用户概念退役后，调试面身份同样来自 token（不再回落魔法默认值）。"""
    client = TestClient(app)
    response = getattr(client, method)(path, **(kwargs or {}))
    assert response.status_code == 401


def test_chat_uses_token_identity(real_auth, llm_override):
    llm_override(FakeLLM(response="嗯，我在。", structured_responses=_structured()))
    client = TestClient(app)
    with client.stream(
        "post",
        "/api/v1/chat/message",
        json={"content": "你好"},
        headers=_headers(OWNER),
    ) as response:
        assert response.status_code == 200
        session_id = response.headers["x-session-id"]
        body = b"".join(response.iter_bytes()).decode("utf-8")
    assert '"done": true' in body

    history = client.get("/api/v1/conversations/latest", headers=_headers(OWNER))
    assert history.status_code == 200
    assert history.json()["conversation_id"] == session_id

    stranger = client.get("/api/v1/conversations/latest", headers=_headers(STRANGER))
    assert stranger.status_code == 404


def test_history_messages_rejects_foreign_conversation(real_auth, llm_override):
    llm_override(FakeLLM(response="嗯，我在。", structured_responses=_structured()))
    client = TestClient(app)
    with client.stream(
        "post",
        "/api/v1/chat/message",
        json={"content": "你好"},
        headers=_headers(OWNER),
    ) as response:
        assert response.status_code == 200
        session_id = response.headers["x-session-id"]

    foreign = client.get(
        f"/api/v1/conversations/{session_id}/messages", headers=_headers(STRANGER)
    )
    assert foreign.status_code == 404
    own = client.get(
        f"/api/v1/conversations/{session_id}/messages", headers=_headers(OWNER)
    )
    assert own.status_code == 200
    assert own.json()["conversation_id"] == session_id


def test_ledger_scope_follows_token(real_auth):
    client = TestClient(app)
    created = client.post(
        "/api/v1/ledger/entries",
        json={"amount_minor": 1250, "direction": "expense", "merchant": "测试"},
        headers=_headers(OWNER),
    )
    assert created.status_code == 200

    own = client.get("/api/v1/ledger/summary", headers=_headers(OWNER))
    assert own.status_code == 200
    assert own.json()["expense_minor"] == 1250

    stranger = client.get("/api/v1/ledger/summary", headers=_headers(STRANGER))
    assert stranger.status_code == 200
    assert stranger.json()["expense_minor"] == 0


def test_life_export_scoped_to_token(real_auth):
    from app.services.governance import DomainHandlers, register_domain
    from app.services.governance import core as registry_mod

    store: dict[str, list[str]] = {OWNER: ["own-1"], STRANGER: ["stray-1"]}

    def _export(user_id: str):
        return {"items": list(store.get(user_id, []))}

    def _delete(user_id: str) -> int:
        rows = store.pop(user_id, [])
        return len(rows)

    register_domain(DomainHandlers(name="cutover-sample", export=_export, delete=_delete))
    try:
        client = TestClient(app)
        bundle = client.get("/api/v1/life/export", headers=_headers(OWNER))
        assert bundle.status_code == 200
        payload = bundle.json()
        assert payload["user_id"] == OWNER
        assert payload["domains"]["cutover-sample"]["items"] == ["own-1"]

        stranger = client.get("/api/v1/life/export", headers=_headers(STRANGER))
        assert stranger.status_code == 200
        assert stranger.json()["domains"]["cutover-sample"]["items"] == ["stray-1"]
    finally:
        registry_mod.reset_registry()


def test_fresh_user_cold_start_chat(db_session_factory):
    import asyncio

    from app.services import agent_service

    llm = FakeLLM(response="晚安。", structured_responses=_structured())

    async def _turn(user_id: str, session_id: str) -> list[dict]:
        events = []
        async for event in agent_service.stream_chat(
            session_id, user_id, "我准备睡了", llm=llm
        ):
            events.append(event)
        return events

    first = asyncio.run(_turn(OWNER, "s-cutover-cold-1"))
    kinds = [event.get("kind") for event in first]
    assert "turn_meta" in kinds
    assert "done" in kinds

    second = asyncio.run(_turn(OWNER, "s-cutover-cold-2"))
    assert any(event.get("kind") == "done" for event in second)
