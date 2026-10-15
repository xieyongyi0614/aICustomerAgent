"""前台收编 e2e：生产路径（固定 `AgentLoop`）的全轮次流契约与故障面。

原 C-2 总闸 on/off 全轮次对照（RT-ALL-code-review Must Fix 1）随「生产路径固定
`AgentLoop`」收缩为**单路径契约**：线性旧链 `_drive_foreground_linear` 与开关
字段已于 2026-10-15 物理删除。原四面安全网不再做两态对照，只锁生产路径自身：

1. 全轮次 SSE 事件序列（事件类型序列 + 逐事件键序 + delta 文本 + `done` 键集）
2. 中段 LLM 失败的错误面
3. grounding 缓冲（`buffer_reply`）行为
4. post_process 失败不阻断回复

流式事件形状：`{"type": "turn_meta", ...}` → 若干 `{"delta": "..."}` → `{"done": true, ...}`。
"""

from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.application import post_process
from app.main import app
from tests.conftest import use_auth_user


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
        # 意图必须合法，否则目标选择被跳过、`current_goal` 恒为 None（对照空转）
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


def _deltas(lines: list[dict]) -> list[str]:
    return [line["delta"] for line in lines if "delta" in line]


def _meta(lines: list[dict]) -> dict:
    return next(line for line in lines if line.get("type") == "turn_meta")


TURN_META_ORDER: tuple[str, ...] = (
    "type",
    "role_mode",
    "analysis",
    "scene_intent",
    "scene_state",
    "intention",
    "current_goal",
    "behavior",
    "mode",
    "memory_refs",
)


def _is_subsequence(observed: tuple[str, ...], contract: tuple[str, ...]) -> bool:
    """观测键序是否为契约序的子序列（允许值依赖键缺席，不允许乱序）。"""
    iterator = iter(contract)
    return all(any(name == observed_name for name in iterator) for observed_name in observed)


def _single_turn(
    server,
    override_settings,
    llm_override,
    build_llm,
    *,
    content="在吗",
    tag="e2e",
    **settings,
):
    """单轮生产路径流：独立用户 + 显式设置覆盖，返回逐行 JSON。"""
    use_auth_user(f"u-{tag}")
    override_settings(**settings)
    llm_override(build_llm())
    return _turn(server, content, f"s-{tag}")


# ---------------------------------------------------------------------------
# 1. 全轮次流契约（正常轮次）
# ---------------------------------------------------------------------------


def test_full_turn_stream_contract(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    lines = _single_turn(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(
            response=["别急", "，有我呢"], structured_responses=_structured()
        ),
        content="我今天压力很大",
        tag="contract",
        inventory_grounding_mode="off",
    )

    assert [_kind(line) for line in lines] == ["turn_meta", "delta", "delta", "done"]
    assert _deltas(lines) == ["别急", "，有我呢"]
    # `current_goal` 由 api 层「非 None 才下发」，其存在与否取决于本轮是否选中目标——
    # 属**数据依赖**，与收编路径无关。此处锁契约序：观测键序必须是契约序的**子序列**
    # （值依赖键可缺席，顺序不得漂移）。
    assert _is_subsequence(tuple(_meta(lines)), TURN_META_ORDER)


def test_foreground_run_ledger_recorded(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    """生产路径每轮必落 `loop_runs` 台账。"""
    from app.repositories import loop_run_repository

    before = len(loop_run_repository.list_recent())

    _single_turn(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(response=["好"], structured_responses=_structured()),
        tag="ledger",
        inventory_grounding_mode="off",
    )

    assert len(loop_run_repository.list_recent()) > before


# ---------------------------------------------------------------------------
# 2. 中段 LLM 失败
# ---------------------------------------------------------------------------


def test_mid_turn_llm_failure_error_face(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    exc = RuntimeError("mid-turn-llm-failure")

    lines = _single_turn(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(raise_exc=exc, structured_responses=_structured()),
        tag="llmfail",
        inventory_grounding_mode="off",
    )

    # 错误面：先 turn_meta，后错误块；无 token 下发
    assert _kind(lines[0]) == "turn_meta"
    assert _kind(lines[-1]) == "other"
    assert _deltas(lines) == []


# ---------------------------------------------------------------------------
# 3. grounding 缓冲
# ---------------------------------------------------------------------------


def test_grounding_off_streams_tokens(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    """grounding 关闭 → 不缓冲 → 逐 token 流。"""
    lines = _single_turn(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(
            response=["别急", "，有我呢"], structured_responses=_structured()
        ),
        tag="gs",
        inventory_grounding_mode="off",
    )

    assert _kind(lines[0]) == "turn_meta"
    assert _deltas(lines) == ["别急", "，有我呢"]


def test_grounding_rewrite_streams_tokens(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    """grounding=rewrite 不再缓冲：恒逐 token 流；无库存冲突时不发替换。"""
    lines = _single_turn(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(
            response=["别急", "，有我呢"], structured_responses=_structured()
        ),
        content="我今天压力很大",
        tag="gb",
        inventory_grounding_mode="rewrite",
    )

    assert _deltas(lines) == ["别急", "，有我呢"]
    assert all(line.get("type") != "reply_replace" for line in lines)


def test_grounding_rewrite_replaces_changed_reply(
    http_server, db_session_factory, llm_override, fake_llm, override_settings, monkeypatch
):
    """重写有变更：逐 token 流后补发整段 reply_replace，客户端以其为最终回复。"""

    def _rewrite(reply, content, world_ctx, mode, trace):
        return reply + "（已校准）"

    monkeypatch.setattr(
        "app.application.chat_pipeline._apply_inventory_grounding", _rewrite
    )
    lines = _single_turn(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(
            response=["别急", "，有我呢"], structured_responses=_structured()
        ),
        content="我今天压力很大",
        tag="gbr",
        inventory_grounding_mode="rewrite",
    )

    assert _deltas(lines) == ["别急", "，有我呢"]
    replaces = [
        line["text"] for line in lines if line.get("type") == "reply_replace"
    ]
    assert replaces == ["别急，有我呢（已校准）"]
    assert lines[-1].get("done") is True


# ---------------------------------------------------------------------------
# 4. post_process 失败不阻断回复
# ---------------------------------------------------------------------------


def test_post_process_failure_does_not_break_stream(
    http_server,
    db_session_factory,
    llm_override,
    fake_llm,
    override_settings,
    monkeypatch,
):
    async def _boom(_ctx):
        raise RuntimeError("post_process-step-failed")

    monkeypatch.setattr(post_process, "STEP_HANDLERS", (_boom,))

    lines = _single_turn(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(response=["别急"], structured_responses=_structured()),
        tag="ppf",
        inventory_grounding_mode="off",
    )

    # 后台步骤失败不影响已产出的回复与流终态
    assert _kind(lines[-1]) == "done"
    assert _deltas(lines) == ["别急"]
