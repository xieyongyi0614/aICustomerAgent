"""会话历史 REST 契约：GET /conversations/{id}/messages 与 /conversations/latest。

移动端进页面恢复上次会话依赖这两个端点（无专用会话列表端点，D3 端上投影）。
user_id 自 v5.0.0 §14 起由 token 解析（测试内经 conftest override 注入 owner 身份）。
"""

from fastapi.testclient import TestClient

from app.main import app
from app.services.conversation import service as svc
from tests.conftest import TEST_USER_ID


def test_messages_returns_recent_turn(db_session_factory):
    svc.ensure_conversation("s-hist-1", TEST_USER_ID)
    svc.save_turn("s-hist-1", "我今天好累", "先坐下来歇会儿")

    with TestClient(app) as client:
        resp = client.get("/api/v1/conversations/s-hist-1/messages")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "s-hist-1"
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("human", "我今天好累"),
        ("ai", "先坐下来歇会儿"),
    ]


def test_messages_unknown_conversation_404(db_session_factory):
    with TestClient(app) as client:
        resp = client.get("/api/v1/conversations/s-ghost/messages")

    assert resp.status_code == 404


def test_latest_returns_conversation_with_messages(db_session_factory):
    svc.ensure_conversation("s-hist-latest", TEST_USER_ID)
    svc.save_turn("s-hist-latest", "在吗", "在的")

    with TestClient(app) as client:
        resp = client.get("/api/v1/conversations/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "s-hist-latest"
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("human", "在吗"),
        ("ai", "在的"),
    ]


def test_latest_unknown_user_404(db_session_factory):
    with TestClient(app) as client:
        resp = client.get("/api/v1/conversations/latest")

    assert resp.status_code == 404
