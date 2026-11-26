"""RT-004 Runtime Context Manager 测试：装配 / 冻结 / 裁剪 / 降级 / 等价。"""

from __future__ import annotations

import asyncio
import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_runtime import context as context_module
from app.application.agent_runtime import state as state_manager
from app.application.agent_runtime.contracts import RuntimeInput, SessionContext
from app.models.agent_state import AgentStateSnapshot

NOW = datetime(2026, 9, 21, 12, 0, 0)
CONTEXT_PATH = Path(context_module.__file__)
FORBIDDEN_IMPORTS = ("app.chains", "app.prompts", "app.channels.feishu", "llm_gateway")
FORBIDDEN_WRITE_TOKENS = ("session.add", ".commit(", "INSERT ", "UPDATE ", "DELETE ")
_DEFAULT = object()


def _session():
    return SessionContext(
        session_id="s-ctx",
        channel="web",
        external_user_id="ou-1",
        user_id="u-ctx",
        thread_id="t-1",
    )


def _text_input(text: str = "hi"):
    return RuntimeInput(
        kind="channel_message",
        source="web",
        payload={"text": text},
        received_at=NOW.replace(tzinfo=timezone.utc),
    )


def _conversation():
    return SimpleNamespace(
        memories=["m"],
        insights=["i"],
        shared_experiences=["s"],
        relationship_patterns=["p"],
    )


class _ExplodingConversation:
    insights: tuple = ()
    shared_experiences: tuple = ()
    relationship_patterns: tuple = ()

    @property
    def memories(self):
        raise RuntimeError("memory projection failed")


def _install(monkeypatch, *, conversation=None, world=_DEFAULT, fail=()):
    conversation = _conversation() if conversation is None else conversation
    world_value = SimpleNamespace(scene="park") if world is _DEFAULT else world

    async def _build(_session_id, _user_id, current_input, **kwargs):
        if "user" in fail:
            raise RuntimeError("user down")
        if not current_input:
            raise ValueError("current_input 必填")
        return conversation

    def _world(_user_id, _session_id=None, _trace=None):
        if "world" in fail:
            raise RuntimeError("world down")
        return world_value

    def _snap(_user_id, _character_id="asuna", _now=None):
        if "character" in fail:
            raise RuntimeError("state down")
        return AgentStateSnapshot(snapshot_version=4)

    def _ver(domain, _user_id, _character_id="asuna", _now=None):
        return state_manager.StateVersion(domain, 1, "ledger", NOW, NOW)

    monkeypatch.setattr(context_module.context_builder, "build", _build)
    monkeypatch.setattr(context_module.world_engine, "build_context", _world)
    monkeypatch.setattr(context_module.state_manager, "snapshot", _snap)
    monkeypatch.setattr(context_module.state_manager, "version", _ver)
    return {"snapshot": _snap, "world": _world}


async def test_assemble_builds_four_segments(monkeypatch):
    _install(monkeypatch)

    result = await context_module.assemble(_session(), _text_input())

    assert result.user is not None
    assert result.memory is not None
    assert result.character is not None
    assert result.world is not None
    assert result.budget.used_chars > 0


async def test_memory_segment_reuses_conversation_state(monkeypatch):
    _install(monkeypatch, conversation=_conversation())

    result = await context_module.assemble(_session(), _text_input())

    assert result.memory.memories == ("m",)
    assert result.memory.insights == ("i",)
    assert result.memory.shared_experiences == ("s",)
    assert result.memory.relationship_patterns == ("p",)


async def test_freeze_returns_identical_context(monkeypatch, override_settings):
    override_settings(runtime_context_freeze_enabled="true")
    _install(monkeypatch)
    run = SimpleNamespace(data={}, started_at=NOW)

    first = await context_module.assemble(_session(), _text_input(), run=run)
    second = await context_module.assemble(_session(), _text_input(), run=run)

    assert first is second
    assert context_module.context_digest(first) == context_module.context_digest(second)
    assert run.data["runtime_context"] is first


async def test_freeze_off_rebuilds_context(monkeypatch, override_settings):
    override_settings(runtime_context_freeze_enabled="false")
    _install(monkeypatch)
    run = SimpleNamespace(data={}, started_at=NOW)

    first = await context_module.assemble(_session(), _text_input(), run=run)
    second = await context_module.assemble(_session(), _text_input(), run=run)

    assert first is not second
    assert "runtime_context" not in run.data
    assert first.time_point == second.time_point


async def test_budget_trims_world_then_memory_only(monkeypatch, override_settings):
    override_settings(context_total_char_budget=1)
    _install(monkeypatch)

    result = await context_module.assemble(_session(), _text_input())

    assert result.budget.dropped_segments == ("world", "memory")
    assert result.budget.truncated is True
    assert result.character is not None
    assert result.user is not None
    assert result.world is None
    assert result.memory is None


@pytest.mark.parametrize("segment", ["user", "character", "world", "memory"])
async def test_segment_failure_degrades_without_raise(monkeypatch, segment):
    conversation = _ExplodingConversation() if segment == "memory" else None
    fail = () if segment == "memory" else (segment,)
    _install(monkeypatch, conversation=conversation, fail=fail)

    result = await context_module.assemble(_session(), _text_input())

    assert segment in {degradation.segment for degradation in result.degradations}


async def test_missing_user_text_degrades_user_segment(monkeypatch):
    _install(monkeypatch)

    result = await context_module.assemble(_session(), None)

    assert "user" in {degradation.segment for degradation in result.degradations}
    assert result.character is not None


async def test_world_disabled_yields_none_world_segment(monkeypatch):
    _install(monkeypatch, world=None)

    result = await context_module.assemble(_session(), _text_input())

    assert result.world is not None
    assert result.world.payload is None
    assert "world" not in {degradation.segment for degradation in result.degradations}


async def test_blocking_calls_are_offloaded(monkeypatch):
    handles = _install(monkeypatch)
    calls: list = []
    real = asyncio.to_thread

    async def _spy(func, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _spy)

    await context_module.assemble(_session(), _text_input())

    assert handles["snapshot"] in calls
    assert handles["world"] in calls


def test_context_module_performs_no_writes_and_no_llm():
    source = CONTEXT_PATH.read_text(encoding="utf-8")
    assert not any(token in source for token in FORBIDDEN_WRITE_TOKENS)


def test_context_module_has_no_forbidden_imports():
    tree = ast.parse(CONTEXT_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = [
        name
        for name in imported
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_IMPORTS
        )
    ]
    assert offenders == []


class TestIdentityResolution:
    """H-4：装配主体身份解析——Run 优先、其次会话载体，绝不以 session_id 冒充。"""

    pytestmark = pytest.mark.unit

    def _capture(self, monkeypatch) -> list:
        captured: list = []

        async def _build(session_id, user_id, current_input, **kwargs):
            captured.append(("build", session_id, user_id))
            return _conversation()

        def _world(user_id, session_id=None, _trace=None):
            captured.append(("world", session_id, user_id))
            return SimpleNamespace(scene="park")

        def _snap(user_id, _character_id="asuna", _now=None):
            captured.append(("snap", None, user_id))
            return AgentStateSnapshot(snapshot_version=4)

        def _ver(domain, _user_id, _character_id="asuna", _now=None):
            return state_manager.StateVersion(domain, 1, "ledger", NOW, NOW)

        monkeypatch.setattr(context_module.context_builder, "build", _build)
        monkeypatch.setattr(context_module.world_engine, "build_context", _world)
        monkeypatch.setattr(context_module.state_manager, "snapshot", _snap)
        monkeypatch.setattr(context_module.state_manager, "version", _ver)
        return captured

    async def test_run_user_id_wins_over_session_id(self, monkeypatch):
        captured = self._capture(monkeypatch)

        await context_module.assemble(
            _session(), _text_input(), run=SimpleNamespace(user_id="u-run")
        )

        assert captured, "装配未发生"
        assert all(user_id == "u-run" for _kind, _session_id, user_id in captured)
        # 会话 id 与主体 id 必须分离传递，不得互相冒充
        build_calls = [entry for entry in captured if entry[0] == "build"]
        assert build_calls[0][1] == "s-ctx"
        assert build_calls[0][2] == "u-run"

    async def test_session_context_user_id_used_without_run(self, monkeypatch):
        captured = self._capture(monkeypatch)

        await context_module.assemble(_session(), _text_input())

        assert all(user_id == "u-ctx" for _kind, _session_id, user_id in captured)

    async def test_unknown_identity_degrades_instead_of_using_session_id(
        self, monkeypatch
    ):
        self._capture(monkeypatch)
        anonymous = SessionContext(session_id="s-only")

        result = await context_module.assemble(anonymous, _text_input())

        assert result.user is None
        assert result.character is None
        assert result.world is None
        assert [d.segment for d in result.degradations] == ["user"]
        assert result.degradations[0].error == "unknown_user"
