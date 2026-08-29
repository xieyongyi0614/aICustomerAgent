import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.character.asuna import PERSISTENT_GOALS
from app.main import app
from app.repositories import goal_repository
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


@pytest.fixture(scope="module")
def goal_http_server():
    server = _ServerThread(_free_port())
    server.start()
    yield server
    server.stop()


STRUCTURED = {
    "RoleMode": {
        "mode": "immersive",
        "intent": "emotional",
        "confidence": 0.9,
        "reason": "倾诉",
    },
    "TurnAnalysis": {
        "user_emotion": {"emotion": "sad", "event": "setback"},
        "behavior": {"behavior": "comfort", "reason": "先接住情绪"},
        "emotion_event": {"type": "none", "magnitude": "normal", "confidence": 0.0},
        "relationship_event": {"type": "none", "magnitude": "normal", "confidence": 0.0},
    },
    "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "闲聊"},
    "StateUpdateDecision": {"mood": "worried", "mood_reason": "用户低落", "inner_state": "担心", "current_topic": "心情"},
    "SceneActionDecision": {},
    "MemoryExtraction": {"candidates": []},
    "IntentionDecision": {
        "intention": "ask_followup",
        "confidence": 0.8,
        "reason": "想多了解用户近况",
    },
}


def _post_lines(server, content):
    with httpx.Client(base_url=server.base_url) as client:
        lines = [
            json.loads(line)
            for line in client.post(
                "/api/v1/chat/message", json={"content": content}
            ).text.splitlines()
            if line.strip()
        ]
    return lines


class TestGoalOrchestration:
    def test_first_turn_seeds_persistent_goals(
        self, goal_http_server, db_session_factory, llm_override, fake_llm
    ):
        llm_override(fake_llm(response=["怎么啦"], structured_responses=STRUCTURED))
        lines = _post_lines(goal_http_server, "我今天心情不太好")
        meta = lines[0]
        assert meta["type"] == "turn_meta"
        assert "intention" in meta
        assert meta.get("current_goal") is None
        assert lines[-1]["done"] is True

        assert wait_until(lambda: len(goal_repository.list_active("default-user")) >= 3)
        seeds = goal_repository.list_active("default-user")
        persistent = [g for g in seeds if g.horizon == "persistent"]
        assert len(persistent) == 3
        assert all(g.source == "definition" for g in persistent)
        assert any(
            g.horizon == "current" and g.type == "user_care" for g in seeds
        )

    def test_second_turn_selects_goal_and_carries_intention(
        self, goal_http_server, db_session_factory, llm_override, fake_llm
    ):
        goal_repository.seed_goals("default-user", PERSISTENT_GOALS)
        llm_override(fake_llm(response=["嗯"], structured_responses=STRUCTURED))
        lines = _post_lines(goal_http_server, "最近有点撑不住")
        meta = lines[0]
        assert meta["current_goal"] is not None
        assert meta["current_goal"]["type"] == "user_care"
        assert meta["intention"]["type"] == "ask_followup"
        assert meta["intention"]["degraded"] is False
        assert meta["intention"]["goal_id"] == meta["current_goal"]["id"]
        deltas = [line["delta"] for line in lines if "delta" in line]
        assert deltas == ["嗯"]
        assert lines[-1]["done"] is True

    def test_intention_chain_failure_degrades_and_sse_completes(
        self, goal_http_server, db_session_factory, llm_override, fake_llm
    ):
        goal_repository.seed_goals("default-user", PERSISTENT_GOALS)
        llm_override(
            fake_llm(
                response=["没事"],
                structured_responses=STRUCTURED,
                structured_errors={"IntentionDecision": RuntimeError("intention boom")},
            )
        )
        lines = _post_lines(goal_http_server, "在吗")
        meta = lines[0]
        assert meta["intention"]["type"] == "continue_topic"
        assert meta["intention"]["degraded"] is True
        deltas = [line["delta"] for line in lines if "delta" in line]
        assert deltas == ["没事"]
        assert lines[-1]["done"] is True
