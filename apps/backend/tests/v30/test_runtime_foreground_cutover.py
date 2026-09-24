"""RT-015 前台循环收编：流式契约冻结 + 唯一路径 + 收尾委派 + 入口收敛登记。

覆盖 `turn_meta` 键集与顺序、`done` 字段、每轮 1 行 `loop_runs`、开关关闭时的
等价性、`agent_service.stream_chat` 调用点登记完整性、段序列唯一声明处，以及
`logical_clock.unbind` / `reset_run_state` / `close_run` 收尾委派循环。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.application.agent_runtime.models import RUN_KIND_FOREGROUND_CHAT
from app.core.settings import get_settings
from app.repositories import loop_run_repository
from app.services import agent_service

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent.parent
ENTRY_DOC = REPO / "docs" / "version" / "v3.0.0" / "entry-convergence.md"

USER_ID = "default-user"

TURN_META_ORDER: tuple[str, ...] = (
    "kind",
    "role_mode",
    "analysis",
    "scene_intent",
    "scene_state",
    "intention",
    "current_goal",
    "behavior",
    "mode",
)
DONE_KEYS = frozenset({"kind", "session_id", "turn_id", "request_id"})
CALL_PATTERN = re.compile(r"agent_service\.stream_chat\s*\(")


def _llm(fake_llm):
    return fake_llm(
        response=["嗯"],
        structured_responses={
            "RoleMode": {
                "mode": "default",
                "intent": "casual",
                "confidence": 0.9,
                "reason": "hi",
            },
            "TurnAnalysis": {
                "user_emotion": {"emotion": "sad", "event": "setback"},
                "behavior": {"behavior": "comfort", "reason": "测试"},
            },
        },
    )


async def _events(session_id: str, content: str, llm) -> list[dict]:
    events: list[dict] = []
    async for event in agent_service.stream_chat(session_id, USER_ID, content, llm=llm):
        events.append(event)
    return events


OPTIONAL_TRAILING_KEYS: tuple[str, ...] = ("action_intent", "memory_refs")


def _core_keys(meta: dict) -> list[str]:
    return [name for name in meta if name not in OPTIONAL_TRAILING_KEYS]


def _trailing_keys(meta: dict) -> list[str]:
    return [name for name in meta if name in OPTIONAL_TRAILING_KEYS]


class TestStreamingContract:
    """收编前基线 = 收编后必须逐字段一致（RT-015 AC1 / AC4 / AC7）。"""

    pytestmark = pytest.mark.integration

    async def test_turn_meta_keys_and_order_unchanged(
        self, db_session_factory, fake_llm
    ):
        events = await _events("s-v30-meta", "我今天压力很大", _llm(fake_llm))

        meta = events[0]
        assert meta["kind"] == "turn_meta"
        assert _core_keys(meta) == list(TURN_META_ORDER)
        assert _trailing_keys(meta) == [
            name for name in OPTIONAL_TRAILING_KEYS if name in meta
        ]

    async def test_done_event_unchanged(self, db_session_factory, fake_llm):
        events = await _events("s-v30-done", "在吗", _llm(fake_llm))

        done = events[-1]
        assert done["kind"] == "done"
        assert set(done) == DONE_KEYS
        assert done["session_id"] == "s-v30-done"
        assert str(done["turn_id"]).isdigit()
        assert done["request_id"]
        assert all(event["kind"] == "token" for event in events[1:-1])

    async def test_run_metadata_written(self, db_session_factory, fake_llm):
        before = len(loop_run_repository.list_recent(USER_ID, limit=200))

        await _events("s-v30-runs", "在吗", _llm(fake_llm))

        runs = loop_run_repository.list_recent(USER_ID, limit=200)
        assert len(runs) == before + 1
        assert runs[0].run_kind == RUN_KIND_FOREGROUND_CHAT
        assert runs[0].status in {"done", "degraded"}

    async def test_flags_off_means_legacy_context_assembly(
        self, db_session_factory, fake_llm
    ):
        settings = get_settings()
        assert settings.runtime_context_freeze_enabled is False
        assert settings.runtime_state_versioning_enabled is False

        events = await _events("s-v30-flags", "在吗", _llm(fake_llm))

        assert _core_keys(events[0]) == list(TURN_META_ORDER)
        assert events[-1]["kind"] == "done"


class TestSingleLoopPath:
    """RT-015 AC2：段序列只来自 `profiles.py`，`chat_pipeline` 不得手写阶段序列。"""

    pytestmark = pytest.mark.unit

    def test_single_loop_path(self):
        source = (BACKEND / "app" / "application" / "chat_pipeline.py").read_text(
            encoding="utf-8"
        )
        assert "AgentLoop" in source
        assert "runtime_profiles.get_profile" in source
        assert "_foreground_registry" in source
        assert "run_stage_async" not in source
        for forbidden in (
            "open_foreground_run(user_id)",
            'for stage in (',
            "stages = [",
        ):
            assert forbidden not in source

    def test_foreground_stages_come_from_profile(self):
        from app.application.agent_runtime.profiles import get_profile

        spec = get_profile(RUN_KIND_FOREGROUND_CHAT)
        assert spec.stages == (
            "perception",
            "context_assembly",
            "turn_decisions",
            "mode_stabilize",
            "scene_resolve",
            "behavior_resolve",
            "action_planning",
            "reply_generation",
            "record_handoff",
        )
        source = (BACKEND / "app" / "application" / "chat_pipeline.py").read_text(
            encoding="utf-8"
        )
        for name in spec.stages:
            assert f'"{name}"' in source


class TestCleanupDelegatedToLoop:
    """RT-015 AC：收尾逻辑由循环统一执行，前台驱动不重复 close。"""

    pytestmark = pytest.mark.integration

    async def test_cleanup_delegated_to_loop(
        self, db_session_factory, fake_llm, monkeypatch
    ):
        from app.application import agent_state_assembler, logical_clock
        from app.application.agent_runtime import controller as runtime_controller

        unbind_calls: list = []
        reset_calls: list = []
        close_calls: list = []

        original_unbind = logical_clock.unbind
        original_reset = agent_state_assembler.reset_run_state
        original_close = runtime_controller.close_run

        def _unbind(token):
            unbind_calls.append(token)
            return original_unbind(token)

        def _reset(run_ctx):
            reset_calls.append(run_ctx)
            return original_reset(run_ctx)

        def _close(run_ctx, status, steps, **kwargs):
            close_calls.append((run_ctx, status))
            return original_close(run_ctx, status, steps, **kwargs)

        monkeypatch.setattr(logical_clock, "unbind", _unbind)
        monkeypatch.setattr(agent_state_assembler, "reset_run_state", _reset)
        monkeypatch.setattr(runtime_controller, "close_run", _close)

        await _events("s-v30-cleanup", "在吗", _llm(fake_llm))

        assert len(unbind_calls) == 1
        assert len(reset_calls) == 1
        assert len(close_calls) == 1


class TestEntryConvergence:
    """RT-015 AC6：生产调用点必须登记在案，不得静默保留双入口。"""

    pytestmark = pytest.mark.unit

    def test_agent_service_call_sites_registered(self):
        doc = ENTRY_DOC.read_text(encoding="utf-8")
        found: list[str] = []
        unregistered: list[str] = []
        for path in sorted((BACKEND / "app").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not CALL_PATTERN.search(line):
                    continue
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"'):
                    continue
                rel = path.relative_to(BACKEND).as_posix()
                found.append(f"{rel}:{lineno}")
                if rel not in doc:
                    unregistered.append(f"{rel}:{lineno}")

        assert found, "未找到 agent_service.stream_chat 调用点，登记守卫本身失效"
        assert not unregistered, f"未登记的生产调用点：{unregistered}"

    def test_entry_convergence_doc_is_present(self):
        doc = ENTRY_DOC.read_text(encoding="utf-8")

        assert "stream_chat" in doc
        assert "保留" in doc
        assert "收编本体" in doc or "AgentLoop" in doc


class TestForegroundKillSwitch:
    """C-2：前台收编总闸——关闭时回退线性旧链（零 Run 台账），流式协议不变。"""

    pytestmark = pytest.mark.unit

    async def test_flag_off_creates_no_run_ledger(
        self, db_session_factory, fake_llm, override_settings
    ):
        override_settings(runtime_foreground_loop_enabled="false")
        before = len(loop_run_repository.list_recent())

        events = await _events("s-kill-off", "在吗", _llm(fake_llm))

        assert events[-1]["kind"] == "done"
        assert len(loop_run_repository.list_recent()) == before

    async def test_flag_on_records_run_ledger(
        self, db_session_factory, fake_llm, override_settings
    ):
        override_settings(runtime_foreground_loop_enabled="true")

        await _events("s-kill-on", "在吗", _llm(fake_llm))

        rows = [
            row
            for row in loop_run_repository.list_recent()
            if row.run_kind == RUN_KIND_FOREGROUND_CHAT
        ]
        assert rows, "开启总闸时应落 foreground_chat 台账"
        assert rows[0].status in {"done", "degraded"}

    async def test_flag_off_keeps_streaming_contract(
        self, db_session_factory, fake_llm, override_settings
    ):
        override_settings(runtime_foreground_loop_enabled="true")
        on_events = await _events("s-kill-contract-on", "在吗", _llm(fake_llm))

        override_settings(runtime_foreground_loop_enabled="false")
        off_events = await _events("s-kill-contract-off", "在吗", _llm(fake_llm))

        on_meta = next(e for e in on_events if e["kind"] == "turn_meta")
        off_meta = next(e for e in off_events if e["kind"] == "turn_meta")
        assert _core_keys(off_meta) == _core_keys(on_meta)
        assert _core_keys(off_meta) == list(TURN_META_ORDER)
        assert _trailing_keys(off_meta) == [name for name in OPTIONAL_TRAILING_KEYS if name in off_meta]
        assert _trailing_keys(on_meta) == [name for name in OPTIONAL_TRAILING_KEYS if name in on_meta]

        on_done = next(e for e in on_events if e["kind"] == "done")
        off_done = next(e for e in off_events if e["kind"] == "done")
        assert set(off_done) == set(on_done) == DONE_KEYS
        assert off_done["session_id"] == "s-kill-contract-off"

    async def test_linear_chain_uses_profile_stage_order(self):
        from app.application import chat_pipeline
        from app.application.agent_runtime import profiles

        spec = profiles.get_profile(RUN_KIND_FOREGROUND_CHAT)
        order: list[str] = []

        async def _recorder(name):
            async def _run(_ctx):
                order.append(name)

            return _run

        runners = {name: await _recorder(name) for name in spec.stages}
        await chat_pipeline._drive_foreground_linear(  # pylint: disable=protected-access
            spec, runners
        )

        assert order == list(spec.stages)
