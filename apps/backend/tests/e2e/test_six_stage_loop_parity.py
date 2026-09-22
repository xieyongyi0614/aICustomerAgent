"""R-15 e2e：`runtime_six_stage_loop_enabled` 两态前台流对照。

前台在六段开关打开时仍经 `_run_phase` 驱动既有 Profile 段本体（22 步业务闭包），
只改循环形状；故 **SSE 流指纹必须与关闭时逐字段一致**。这是切默认前的安全网。

自治 tick 的真六段路径（`stages/*`）不在本文件——其步骤名形状不同，由
`tests/v30/test_agent_loop_core.py` 锁定。
"""

from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.main import app


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
def http_server():
    server = _ServerThread(_free_port())
    server.start()
    yield server
    server.stop()


def _structured():
    return {
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
        "IntentionDecision": {
            "intention": "continue_topic",
            "confidence": 0.9,
            "reason": "闲聊",
        },
    }


def _turn(server, content: str, session_id: str) -> list[dict]:
    with httpx.Client(base_url=server.base_url, timeout=60.0) as client:
        resp = client.post(
            "/api/v1/chat/message",
            json={"content": content, "session_id": session_id},
        )
    assert resp.status_code == 200, resp.text[:300]
    return [json.loads(line) for line in resp.text.strip().splitlines() if line.strip()]


def _kind(line: dict) -> str:
    if line.get("type") == "turn_meta":
        return "turn_meta"
    if "delta" in line:
        return "delta"
    if line.get("done") is True:
        return "done"
    return "other"


def _fingerprint(lines: list[dict]) -> list[tuple[str, tuple[str, ...]]]:
    return [(_kind(line), tuple(line)) for line in lines]


def _deltas(lines: list[dict]) -> list[str]:
    return [line["delta"] for line in lines if "delta" in line]


def _done_keys(lines: list[dict]) -> set[str]:
    done = next((line for line in lines if line.get("done") is True), None)
    assert done is not None
    return set(done)


def _meta(lines: list[dict]) -> dict:
    return next(line for line in lines if line.get("type") == "turn_meta")


def _both_six_modes(
    server,
    override_settings,
    llm_override,
    build_llm,
    *,
    content="在吗",
    tag="six",
    expect_done=True,
    **settings,
):
    on_user, off_user = f"u-{tag}-on", f"u-{tag}-off"

    override_settings(
        **settings,
        default_user=on_user,
        runtime_foreground_loop_enabled="true",
        runtime_six_stage_loop_enabled="true",
    )
    llm_override(build_llm())
    on = _turn(server, content, f"s-{tag}-on")

    override_settings(
        **settings,
        default_user=off_user,
        runtime_foreground_loop_enabled="true",
        runtime_six_stage_loop_enabled="false",
    )
    llm_override(build_llm())
    off = _turn(server, content, f"s-{tag}-off")

    assert _fingerprint(off) == _fingerprint(on)
    assert _deltas(off) == _deltas(on)
    if expect_done:
        assert _done_keys(off) == _done_keys(on)
        assert _meta(off)["role_mode"] == _meta(on)["role_mode"]
    return on, off


def test_six_stage_flag_off_matches_on_full_turn_stream(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    on, off = _both_six_modes(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(
            response=["别急", "，有我呢"], structured_responses=_structured()
        ),
        content="我今天压力很大",
        tag="six-parity",
        inventory_grounding_enabled="false",
        world_enabled="false",
    )

    assert [_kind(line) for line in on] == ["turn_meta", "delta", "delta", "done"]
    assert _deltas(on) == ["别急", "，有我呢"]
    assert _deltas(off) == _deltas(on)


def test_six_stage_flag_off_matches_on_mid_turn_llm_failure(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    exc = RuntimeError("llm down")

    def build():
        return fake_llm(raise_exc=exc, structured_responses=_structured())

    on, off = _both_six_modes(
        http_server,
        override_settings,
        llm_override,
        build,
        content="随便聊聊",
        tag="six-fail",
        inventory_grounding_enabled="false",
        world_enabled="false",
        expect_done=False,
    )

    assert _kind(on[0]) == "turn_meta"
    assert _fingerprint(off) == _fingerprint(on)
