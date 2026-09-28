"""C-2 补充 e2e（RT-ALL-code-review Must Fix 1）：前台收编总闸 on/off 的全轮次流对照与故障注入。

总闸 = `RUNTIME_FOREGROUND_LOOP_ENABLED`：

- **on**（默认）：前台链经 `open_foreground_run` + `AgentLoop`（落 `loop_runs` 台账、发运行时事件）。
- **off**：`chat_pipeline._drive_foreground_linear`（线性旧链：同一段序列与段本体，零台账 / 零事件 / 零冻结）。

两态必须在以下四面**逐字段一致**——这是「方案 A 真收编」的前置安全网（见
`docs/version/v3.0.0/architecture.md` 附 D-1 与 `reviews/RT-ALL-remediation.md` R-12）：

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


def _fingerprint(lines: list[dict]) -> list[tuple[str, tuple[str, ...]]]:
    """录制流指纹：事件类型序列 + 逐事件键序（不含易变值）。"""
    return [(_kind(line), tuple(line)) for line in lines]


def _deltas(lines: list[dict]) -> list[str]:
    return [line["delta"] for line in lines if "delta" in line]


def _done_keys(lines: list[dict]) -> set[str]:
    done = next((line for line in lines if line.get("done") is True), None)
    assert done is not None, "流未以 done 收尾"
    return set(done)


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


def _assert_parity(on: list[dict], off: list[dict], *, expect_done: bool = True) -> None:
    """两态的全轮次流必须逐字段一致。"""
    assert _fingerprint(off) == _fingerprint(on)
    assert _deltas(off) == _deltas(on)
    if expect_done:
        assert _done_keys(off) == _done_keys(on)
    # turn_meta 的稳定子集（值与开关无关）
    assert _meta(off)["role_mode"] == _meta(on)["role_mode"]
    assert _meta(off)["mode"] == _meta(on)["mode"]


def _both_modes(
    server,
    override_settings,
    llm_override,
    build_llm,
    *,
    content="在吗",
    tag="parity",
    expect_done=True,
    **settings,
):
    """同一输入在总闸 on / off 两态各跑一轮，返回 (on_lines, off_lines)。

    两态用**各自独立的用户**（`use_auth_user`），否则同一用户的跨轮状态（如本轮是否选中目标）
    会让 `current_goal` 这类「按值决定是否下发」的字段产生与开关无关的差异——
    那是数据依赖，不是收编差异。
    """
    on_user, off_user = f"u-{tag}-on", f"u-{tag}-off"

    use_auth_user(on_user)
    override_settings(**settings, runtime_foreground_loop_enabled="true")
    llm_override(build_llm())
    on = _turn(server, content, f"s-{tag}-on")

    use_auth_user(off_user)
    override_settings(**settings, runtime_foreground_loop_enabled="false")
    llm_override(build_llm())
    off = _turn(server, content, f"s-{tag}-off")

    _assert_parity(on, off, expect_done=expect_done)
    return on, off


# ---------------------------------------------------------------------------
# 1. 全轮次流对照（正常轮次）
# ---------------------------------------------------------------------------


def test_full_turn_stream_parity(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    on, off = _both_modes(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(
            response=["别急", "，有我呢"], structured_responses=_structured()
        ),
        content="我今天压力很大",
        tag="parity",
        inventory_grounding_mode="off",
    )

    assert [_kind(line) for line in on] == ["turn_meta", "delta", "delta", "done"]
    assert _deltas(off) == ["别急", "，有我呢"]
    # `current_goal` 由 api 层「非 None 才下发」，其存在与否取决于本轮是否选中目标——
    # 属**数据依赖**，与总闸无关；两态必须一致（fingerprint 整体比对已覆盖）。
    # 此处补一条契约序断言：观测键序必须是契约序的**子序列**（值依赖键可缺席，顺序不得漂移）。
    assert _is_subsequence(tuple(_meta(on)), TURN_META_ORDER)
    assert _is_subsequence(tuple(_meta(off)), TURN_META_ORDER)


def test_flag_off_skips_run_ledger_but_on_records_it(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    """两态的**唯一**预期差异：台账。"""
    from app.repositories import loop_run_repository

    override_settings(
        inventory_grounding_mode="off",
        runtime_foreground_loop_enabled="true",
    )
    llm_override(fake_llm(response=["好"], structured_responses=_structured()))
    before = len(loop_run_repository.list_recent())
    _turn(http_server, "在吗", "s-ledger-on")
    after_on = len(loop_run_repository.list_recent())
    assert after_on > before

    override_settings(runtime_foreground_loop_enabled="false")
    llm_override(fake_llm(response=["好"], structured_responses=_structured()))
    _turn(http_server, "在吗", "s-ledger-off")
    assert len(loop_run_repository.list_recent()) == after_on


# ---------------------------------------------------------------------------
# 2. 中段 LLM 失败
# ---------------------------------------------------------------------------


def test_mid_turn_llm_failure_parity(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    exc = RuntimeError("mid-turn-llm-failure")

    on, off = _both_modes(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(raise_exc=exc, structured_responses=_structured()),
        content="在吗",
        tag="llmfail",
        expect_done=False,
        inventory_grounding_mode="off",
    )

    # 失败面：先 turn_meta，后错误块；无 token 下发；两态一致
    assert _kind(on[0]) == "turn_meta"
    assert _kind(on[-1]) == "other"
    assert _deltas(on) == []


# ---------------------------------------------------------------------------
# 3. grounding 缓冲
# ---------------------------------------------------------------------------


def test_grounding_streamed_parity(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    """grounding 关闭 → 不缓冲 → 逐 token 流；两态一致。"""
    on, off = _both_modes(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(
            response=["别急", "，有我呢"], structured_responses=_structured()
        ),
        content="在吗",
        tag="gs",
        inventory_grounding_mode="off",
    )

    # 逐 token 流（非聚合）
    assert _kind(on[0]) == "turn_meta"
    assert _deltas(on) == ["别急", "，有我呢"]


def test_grounding_rewrite_streams_tokens(
    http_server, db_session_factory, llm_override, fake_llm, override_settings
):
    """grounding=rewrite 不再缓冲：恒逐 token 流；无库存冲突时不发替换。"""
    on, off = _both_modes(
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

    assert _deltas(on) == ["别急", "，有我呢"]
    assert all(line.get("type") != "reply_replace" for line in on)
    assert all(line.get("type") != "reply_replace" for line in off)


def test_grounding_rewrite_replaces_changed_reply(
    http_server, db_session_factory, llm_override, fake_llm, override_settings, monkeypatch
):
    """重写有变更：逐 token 流后补发整段 reply_replace，客户端以其为最终回复。"""

    def _rewrite(reply, content, world_ctx, mode, trace):
        return reply + "（已校准）"

    monkeypatch.setattr(
        "app.application.chat_pipeline._apply_inventory_grounding", _rewrite
    )
    on, off = _both_modes(
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

    assert _deltas(on) == ["别急", "，有我呢"]
    replaces = [
        line["text"] for line in on if line.get("type") == "reply_replace"
    ]
    assert replaces == ["别急，有我呢（已校准）"]
    assert on[-1].get("done") is True


# ---------------------------------------------------------------------------
# 4. post_process 失败不阻断回复
# ---------------------------------------------------------------------------


def test_post_process_failure_parity(
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

    on, off = _both_modes(
        http_server,
        override_settings,
        llm_override,
        lambda: fake_llm(response=["别急"], structured_responses=_structured()),
        content="在吗",
        tag="ppf",
        inventory_grounding_mode="off",
    )

    # 后台步骤失败不影响已产出的回复与流终态
    assert _kind(on[-1]) == "done"
    assert _deltas(on) == ["别急"]
