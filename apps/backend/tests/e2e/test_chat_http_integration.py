import json
import socket
import threading
import time

import httpx
import openai
import pytest
import uvicorn

from app.repositories import memory_repository, summary_repository
from app.main import app

from tests.conftest import wait_until


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

    def start(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def http_server():
    server = _ServerThread(_free_port())
    server.start()
    yield server
    server.stop()


def _parse_stream(text):
    return [json.loads(line) for line in text.strip().splitlines()]


_LEGACY_TYPE_MAP = {
    "preference": "user_preference",
    "fact": "user_fact",
    "goal": "user_fact",
    "experience": "important_event",
    "relationship": "relationship_event",
}
def _structured_responses(**memory):
    base = {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
    }
    candidates = []
    if memory.get("should_save") and memory.get("memory"):
        candidates = [
            {
                "action": "save",
                "type": _LEGACY_TYPE_MAP.get(memory.get("memory_type", "preference"), "user_preference"),
                "content": memory.get("memory"),
                "importance": memory.get("importance", 0.0),
                "confidence": 0.9,
                "source": "user_stated",
            }
        ]
    base["MemoryExtraction"] = {"candidates": candidates}
    return base


def test_http_health(http_server):
    with httpx.Client(base_url=http_server.base_url) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_http_chat_streams_chunks_incrementally(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    override_settings(inventory_grounding_enabled=False)
    llm_override(fake_llm(
        response=["你好", "呀"],
        structured_responses=_structured_responses(),
    ))
    with httpx.Client(base_url=http_server.base_url) as client:
        with client.stream(
            "POST", "/api/v1/chat/message", json={"content": "在吗"}
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers.get("x-session-new") == "true"
            session_id = resp.headers.get("x-session-id")
            chunks = []
            for line in resp.iter_lines():
                if line.strip():
                    chunks.append(json.loads(line))
    deltas = [line["delta"] for line in chunks if "delta" in line]
    assert deltas == ["你好", "呀"]
    assert chunks[-1]["done"] is True
    assert chunks[-1]["session_id"] == session_id


def test_http_chat_llm_status_error_streams_provider_detail(
    http_server, db_session_factory, llm_override, fake_llm
):
    quota_message = "调用失败：Token 额度不足。欢迎反馈模型使用case（https://longcat.chat/platform/feedback）获取更多额度"
    response = httpx.Response(
        402,
        request=httpx.Request("POST", "https://api.longcat.chat/openai/v1/chat/completions"),
        json={
            "error": {
                "code": "too_many_requests",
                "message": quota_message,
                "type": "rate_limit_error",
            }
        },
    )
    exc = openai.APIStatusError(
        "Error code: 402", response=response, body=response.json()
    )
    llm_override(fake_llm(raise_exc=exc, structured_responses=_structured_responses()))
    with httpx.Client(base_url=http_server.base_url) as client:
        resp = client.post("/api/v1/chat/message", json={"content": "在吗"})
    chunks = _parse_stream(resp.text)
    assert chunks[0]["type"] == "turn_meta"
    assert chunks[0]["role_mode"]["mode"] == "default"
    assert chunks[0]["analysis"]["behavior"]["behavior"] == "normal_reply"
    assert chunks[1:] == [
        {
            "detail": "LLM 调用失败",
            "error": {
                "status": 402,
                "code": "too_many_requests",
                "message": quota_message,
            },
        }
    ]


def test_http_memory_roundtrip(http_server, db_session_factory, llm_override, fake_llm):
    llm_override(fake_llm(
        response=["好的"],
        structured_responses=_structured_responses(
            should_save=True,
            memory="用户喜欢寿司",
            memory_type="preference",
            importance=0.8,
        ),
    ))
    with httpx.Client(base_url=http_server.base_url) as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我喜欢寿司"})
        session_id = resp.headers.get("x-session-id")
    assert resp.status_code == 200
    assert wait_until(
        lambda: any(
            m.content == "用户喜欢寿司"
            for m in memory_repository.list_by_user("default-user")
        )
    )

    second_llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured_responses(),
    )
    llm_override(second_llm)
    with httpx.Client(base_url=http_server.base_url) as client:
        client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "content": "晚上想吃寿司"},
        )
    assert wait_until(lambda: any("用户喜欢寿司" in str(m) for m in second_llm.seen_messages))


def test_http_summary_trigger(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    override_settings(summary_threshold=4)
    llm_override(fake_llm(
        response=["嗯嗯"],
        structured_responses=_structured_responses(),
    ))
    session_id = None
    with httpx.Client(base_url=http_server.base_url) as client:
        for i in range(2):
            body = {"content": f"第{i}轮"}
            if session_id:
                body["session_id"] = session_id
            resp = client.post("/api/v1/chat/message", json=body)
            session_id = resp.headers.get("x-session-id")
    assert wait_until(lambda: summary_repository.get_summary(session_id) is not None)


def test_http_full_lifecycle(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    override_settings(summary_threshold=4)
    llm_override(fake_llm(
        response=["好的"],
        structured_responses=_structured_responses(
            should_save=True,
            memory="用户喜欢寿司",
            memory_type="preference",
            importance=0.8,
        ),
    ))
    with httpx.Client(base_url=http_server.base_url) as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我喜欢寿司"})
        session_id = resp.headers.get("x-session-id")
        assert resp.status_code == 200
        assert wait_until(
            lambda: any(
                m.content == "用户喜欢寿司"
                for m in memory_repository.list_by_user("default-user")
            )
        )

        second_llm = fake_llm(
            response=["嗯嗯"],
            structured_responses=_structured_responses(),
        )
        llm_override(second_llm)
        resp = client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "content": "晚上想吃寿司"},
        )
        assert resp.status_code == 200
        assert wait_until(lambda: any("用户喜欢寿司" in str(m) for m in second_llm.seen_messages))

        third_llm = fake_llm(
            response=["嗯嗯"],
            structured_responses=_structured_responses(),
        )
        llm_override(third_llm)
        resp = client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "content": "继续聊两句"},
        )
        assert resp.status_code == 200
        assert wait_until(
            lambda: summary_repository.get_summary(session_id) is not None
        )


def test_http_state_updates_after_chat(
    http_server, db_session_factory, llm_override, fake_llm
):
    from app.repositories import character_state_repository

    llm_override(fake_llm(
        response=["好耶"],
        structured_responses={
            "RoleMode": {
                "mode": "default",
                "intent": "casual",
                "confidence": 0.9,
                "reason": "hi",
            },
            "TurnAnalysis": {
                "user_emotion": {"emotion": "happy", "event": "achievement"},
                "behavior": {"behavior": "celebrate", "reason": "用户达成成就"},
                "emotion_event": {
                    "type": "praise",
                    "magnitude": "normal",
                    "confidence": 0.9,
                    "cause": "用户达成成就",
                },
            },
            "StateUpdateDecision": {
                "mood": "happy",
                "mood_reason": "用户带来好消息",
                "inner_state": "开心",
                "current_topic": "项目上线",
            },
            "MemoryExtraction": {"candidates": []},
        },
    ))
    with httpx.Client(base_url=http_server.base_url) as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我今天终于把项目上线了"})
        assert resp.status_code == 200

    assert wait_until(
        lambda: character_state_repository.get_state("default-user").mood == "happy"
    )
    state = character_state_repository.get_state("default-user")
    assert state.current_topic == "项目上线"
