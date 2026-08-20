import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.core import llm_factory
from app.main import app
from app.repositories import memory_repository, summary_repository


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _ServerThread:
    def __init__(self, port):
        self.port = port
        self.config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, exc_type, exc, tb):
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture
def base_url(db_session_factory):
    with _ServerThread(_free_port()) as url:
        yield url


def _parse_stream(text):
    return [json.loads(line) for line in text.strip().splitlines()]


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _structured_responses(**memory):
    base = {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
    }
    base["MemoryDecision"] = {
        "should_save": memory.get("should_save", False),
        "memory": memory.get("memory"),
        "memory_type": memory.get("memory_type", "preference"),
        "importance": memory.get("importance", 0.0),
    }
    return base


def test_http_health(base_url):
    with httpx.Client(base_url=base_url) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_http_chat_stream_over_network(base_url, db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["你好", "呀"],
            structured_responses=_structured_responses(),
        )
    )
    with httpx.Client(base_url=base_url) as client:
        resp = client.post(
            "/api/v1/chat/message",
            json={"content": "在吗"},
        )
    assert resp.status_code == 200
    assert resp.headers.get("x-session-new") == "true"
    session_id = resp.headers.get("x-session-id")
    lines = _parse_stream(resp.text)
    deltas = "".join(line.get("delta", "") for line in lines if "delta" in line)
    assert deltas == "你好呀"
    assert lines[-1]["done"] is True
    assert lines[-1]["session_id"] == session_id


def test_http_memory_roundtrip(base_url, db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["好的"],
            structured_responses=_structured_responses(
                should_save=True,
                memory="用户喜欢寿司",
                memory_type="preference",
                importance=0.8,
            ),
        )
    )
    with httpx.Client(base_url=base_url) as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我喜欢寿司"})
        session_id = resp.headers.get("x-session-id")
    assert resp.status_code == 200
    assert _wait_until(
        lambda: any(
            m.memory == "用户喜欢寿司"
            for m in memory_repository.list_by_user("default-user")
        )
    )

    llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured_responses(),
    )
    llm_factory.set_llm(llm)
    with httpx.Client(base_url=base_url) as client:
        client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "content": "晚上想吃寿司"},
        )
    assert _wait_until(lambda: any("用户喜欢寿司" in str(m) for m in llm.seen_messages))


def test_http_summary_trigger_over_network(
    base_url, db_session_factory, fake_llm, override_settings
):
    override_settings(summary_threshold=4)
    llm_factory.set_llm(
        fake_llm(
            response=["嗯嗯"],
            structured_responses=_structured_responses(),
        )
    )
    session_id = None
    with httpx.Client(base_url=base_url) as client:
        for i in range(2):
            body = {"content": f"第{i}轮"}
            if session_id:
                body["session_id"] = session_id
            resp = client.post("/api/v1/chat/message", json=body)
            session_id = resp.headers.get("x-session-id")
    assert _wait_until(lambda: summary_repository.get_summary(session_id) is not None)


def test_http_full_lifecycle(base_url, db_session_factory, fake_llm, override_settings):
    override_settings(summary_threshold=4)
    first_llm = fake_llm(
        response=["好的"],
        structured_responses=_structured_responses(
            should_save=True,
            memory="用户喜欢寿司",
            memory_type="preference",
            importance=0.8,
        ),
    )
    llm_factory.set_llm(first_llm)
    with httpx.Client(base_url=base_url) as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我喜欢寿司"})
        session_id = resp.headers.get("x-session-id")
        assert resp.status_code == 200
        assert _wait_until(
            lambda: any(
                m.memory == "用户喜欢寿司"
                for m in memory_repository.list_by_user("default-user")
            )
        )

        second_llm = fake_llm(
            response=["嗯嗯"],
            structured_responses=_structured_responses(),
        )
        llm_factory.set_llm(second_llm)
        resp = client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "content": "晚上想吃寿司"},
        )
        assert resp.status_code == 200
        assert any("用户喜欢寿司" in str(m) for m in second_llm.seen_messages)

        third_llm = fake_llm(
            response=["嗯嗯"],
            structured_responses=_structured_responses(),
        )
        llm_factory.set_llm(third_llm)
        resp = client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "content": "继续聊两句"},
        )
        assert resp.status_code == 200
        assert _wait_until(
            lambda: summary_repository.get_summary(session_id) is not None
        )
