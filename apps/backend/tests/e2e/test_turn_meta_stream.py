import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from app.main import app
from app.repositories import conversation_repository as repo
from tests.conftest import wait_until


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _ServerThread:
    def __init__(self, port):
        self.port = port
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
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
def meta_http_server():
    server = _ServerThread(_free_port())
    server.start()
    yield server
    server.stop()


def _structured(role_mode=None, turn_analysis=None):
    payload = {}
    if role_mode is not None:
        payload["RoleMode"] = role_mode
    if turn_analysis is not None:
        payload["TurnAnalysis"] = turn_analysis
    return payload


IMMERSIVE_ROLE_MODE = {
    "mode": "immersive",
    "intent": "emotional",
    "confidence": 0.9,
    "reason": "情绪倾诉",
}

COMFORT_ANALYSIS = {
    "user_emotion": {"emotion": "sad", "event": "setback"},
    "behavior": {"behavior": "comfort", "reason": "先接住情绪"},
}


def test_stream_emits_turn_meta_before_first_delta_and_done_carries_turn_id(
    meta_http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    override_settings(inventory_grounding_enabled=False)
    llm_override(
        fake_llm(
            response=["别急", "，有我呢"],
            structured_responses=_structured(IMMERSIVE_ROLE_MODE, COMFORT_ANALYSIS),
        )
    )
    with httpx.Client(base_url=meta_http_server.base_url) as client:
        first = client.post("/api/v1/chat/message", json={"content": "我今天压力很大"})
        assert first.status_code == 200
        session_id = first.headers.get("x-session-id")
        with client.stream(
            "POST",
            "/api/v1/chat/message",
            json={"content": "我今天压力很大", "session_id": session_id},
        ) as resp:
            assert resp.status_code == 200
            lines = [json.loads(line) for line in resp.iter_lines() if line.strip()]

    assert lines[0]["type"] == "turn_meta"
    meta = lines[0]
    assert meta["role_mode"] == IMMERSIVE_ROLE_MODE
    assert meta["mode"]["effective"] == "immersive"
    assert meta["mode"]["switched"] is True
    assert meta["analysis"]["user_emotion"] == COMFORT_ANALYSIS["user_emotion"]
    assert meta["analysis"]["behavior"] == COMFORT_ANALYSIS["behavior"]
    assert meta["analysis"]["emotion_event"]["type"] == "none"
    assert meta["analysis"]["relationship_event"]["type"] == "none"

    deltas = [line["delta"] for line in lines if "delta" in line]
    assert deltas == ["别急", "，有我呢"]

    final = lines[-1]
    assert final["done"] is True
    assert final["session_id"] == session_id
    assert isinstance(final["turn_id"], str) and final["turn_id"].isdigit()

    container: list = []

    def _fetch():
        with repo.SessionLocal() as session:
            row = session.execute(
                select(repo.Message).where(repo.Message.id == int(final["turn_id"]))
            ).scalar_one_or_none()
            container.append(row)
            return row is not None

    assert wait_until(_fetch)
    ai_row = container[-1]
    assert ai_row.role == "ai"
    assert ai_row.content == "".join(deltas)


def test_turn_meta_reflects_low_confidence_degradation(
    meta_http_server, db_session_factory, llm_override, fake_llm
):
    low_confidence = {
        "mode": "immersive",
        "intent": "roleplay",
        "confidence": 0.1,
        "reason": "拿不准",
    }
    llm_override(fake_llm(response=["嗯"], structured_responses=_structured(low_confidence)))
    with httpx.Client(base_url=meta_http_server.base_url) as client:
        lines = [
            json.loads(line)
            for line in client.post(
                "/api/v1/chat/message", json={"content": "扮演一个角色给我看"}
            ).text.splitlines()
            if line.strip()
        ]

    meta = lines[0]
    assert meta["type"] == "turn_meta"
    assert meta["role_mode"]["mode"] == "default"
    assert meta["role_mode"]["confidence"] == 0.1
    assert meta["role_mode"]["intent"] == "roleplay"
    assert meta["mode"]["effective"] == "default"
    assert meta["mode"]["switched"] is False


def test_turn_meta_uses_default_analysis_when_analyzer_fails(
    meta_http_server, db_session_factory, llm_override, fake_llm
):
    llm_override(
        fake_llm(
            response=["嗯"],
            structured_responses=_structured(IMMERSIVE_ROLE_MODE),
            structured_errors={"TurnAnalysis": RuntimeError("analysis boom")},
        )
    )
    with httpx.Client(base_url=meta_http_server.base_url) as client:
        lines = [
            json.loads(line)
            for line in client.post(
                "/api/v1/chat/message", json={"content": "在吗"}
            ).text.splitlines()
            if line.strip()
        ]

    meta = lines[0]
    assert meta["analysis"]["user_emotion"] == {"emotion": "neutral", "event": "daily"}
    assert meta["analysis"]["behavior"] == {"behavior": "normal_reply", "reason": ""}
