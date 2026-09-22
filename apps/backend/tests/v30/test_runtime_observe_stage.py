"""RT-007 Perception Layer（Observe 段）测试：归一 / 只读 / 零 LLM / 降级 / 事件。"""

from __future__ import annotations

import ast
import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application import world_engine
from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime import state as state_manager
from app.application.agent_runtime.contracts import (
    EVENT_OBSERVATION_RECORDED,
    RuntimeInput,
)
from app.application.agent_runtime.models import TRIGGER_TYPES
from app.application.agent_runtime.session import build_session_context
from app.application.agent_runtime.stages import observe as observe_module
from app.application.agent_runtime.stages.observe import (
    FACT_SET_CHARACTER,
    FACT_SET_MEMORY,
    FACT_SET_WORLD,
    CharacterStateFact,
    MemorySignalFact,
    Observation,
    UserInputFact,
    WorldFact,
    observation_dedupe_key,
    observe,
)
from app.channels.base import ChannelIdentity
from app.models.agent_state import AgentStateSnapshot

OBSERVE_PATH = Path(observe_module.__file__)
FORBIDDEN_IMPORTS = (
    "app.repositories",
    "app.chains",
    "app.prompts",
    "app.services.memory2",
    "app.application.agent_runtime.llm_gateway",
    "app.channels.feishu",
)
FORBIDDEN_WRITE_TOKENS = ("session.add", ".commit(", "INSERT ", "UPDATE ", "DELETE ")

SESSION_ID = "S-observe"
USER_ID = "u-observe"
OBSERVED_AT = datetime(2026, 9, 21, 12, 0, 0)


@pytest.fixture(autouse=True)
def _clean_bus():
    event_bus.clear_subscribers()
    yield
    event_bus.clear_subscribers()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _runtime_input(
    kind: str = "channel_message",
    *,
    text: str = "在吗",
    source: str = "web",
    identity: ChannelIdentity | None = None,
    thread_id: str | None = None,
    **payload,
) -> RuntimeInput:
    body: dict = dict(payload)
    if text:
        body["text"] = text
    return RuntimeInput(
        kind=kind,
        source=source,
        payload=body,
        received_at=_now(),
        channel_identity=identity,
        thread_id=thread_id,
    )


def _session(**overrides):
    return build_session_context(
        SESSION_ID,
        channel="web",
        external_user_id="u-ext",
        user_id=USER_ID,
        thread_id="th-1",
        run_id="r-observe",
        now=OBSERVED_AT,
        **overrides,
    )


def _runtime_context(*, world_payload=None, memories=None):
    return SimpleNamespace(
        world=None if world_payload is None else WorldFact(payload=world_payload),
        memory=None if memories is None else SimpleNamespace(memories=tuple(memories)),
    )


def _frozen_state(*, mood="happy", energy=0.42, relationship=None, version=7):
    return SimpleNamespace(
        snapshot=AgentStateSnapshot(
            mood=mood,
            energy=energy,
            relationship=dict(relationship or {"stage": "friend"}),
            snapshot_version=version,
        ),
        snapshot_version=version,
    )


def _stubs(*, world_payload=None, memories=()):
    """无外部读取的段入参（让纯逻辑用例不依赖任何域读取）。"""
    return {
        "runtime_context": _runtime_context(
            world_payload=world_payload if world_payload is not None else {},
            memories=memories,
        ),
        "runtime_state": _frozen_state(),
    }


def _memory(content: str, importance: float = 0.6):
    return SimpleNamespace(content=content, importance=importance)


class TestObservationShape:
    pytestmark = pytest.mark.unit

    def test_four_trigger_kinds_share_schema(self):
        stubs = _stubs()
        observations = [
            observe(_runtime_input(kind), _session(), **stubs)
            for kind in TRIGGER_TYPES
        ]

        assert {item.kind for item in observations} == set(TRIGGER_TYPES)
        assert all(isinstance(item, Observation) for item in observations)
        field_names = {
            tuple(f.name for f in dataclasses.fields(item)) for item in observations
        }
        assert field_names == {tuple(f.name for f in dataclasses.fields(Observation))}
        baseline = [
            (item.user_input, item.world, item.memory, item.character, item.degradations)
            for item in observations
        ]
        assert baseline[1:] == baseline[:-1]

    def test_user_input_fact_from_payload(self):
        identity = ChannelIdentity("feishu", "ou_x")

        item = observe(
            _runtime_input(identity=identity, thread_id="th-feishu"),
            _session(),
            **_stubs(),
        )

        assert item.user_input == UserInputFact(
            text="在吗",
            channel="feishu",
            external_user_id="ou_x",
            thread_id="th-feishu",
        )
        assert item.degradations == ()

    def test_absent_text_is_not_a_degradation(self):
        item = observe(
            _runtime_input("schedule", text="", source="life_loop"), _session()
        )

        assert item.user_input is None
        assert item.degradations == ()

    def test_source_falls_back_to_session_channel(self):
        item = observe(None, _session(), **_stubs())

        assert item.source == "web"
        assert item.kind == "channel_message"

    def test_observed_at_aligns_to_session_start(self):
        item = observe(_runtime_input(), _session(), **_stubs())

        assert item.observed_at == OBSERVED_AT

    def test_dedupe_key_is_deterministic(self):
        first = _runtime_input()
        second = _runtime_input()

        assert observation_dedupe_key("channel_message", "web", first) == (
            observation_dedupe_key("channel_message", "web", second)
        )
        assert observation_dedupe_key("channel_message", "web", first) != (
            observation_dedupe_key("schedule", "web", first)
        )
        assert observation_dedupe_key("channel_message", "web", first) != (
            observation_dedupe_key("channel_message", "feishu", first)
        )

    def test_dedupe_key_prefers_explicit_key_and_hashes_basis(self):
        keyed = _runtime_input(dedupe_key="evt-1")

        assert observation_dedupe_key("world_event", "world", keyed) == (
            observation_dedupe_key(
                "world_event", "world", _runtime_input(dedupe_key="evt-1")
            )
        )
        assert observation_dedupe_key("channel_message", "web", _runtime_input()) != (
            observation_dedupe_key("channel_message", "web", keyed)
        )
        assert "在吗" not in observation_dedupe_key(
            "channel_message", "web", _runtime_input()
        )


class TestFactSetSources:
    pytestmark = pytest.mark.unit

    def test_world_fact_prefers_runtime_context(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            world_engine,
            "collect_facts",
            lambda user_id, provider=None: (calls.append(user_id), {"location": "家"})[1],
        )
        context = _runtime_context(world_payload={"location": "学校"})
        frozen = _frozen_state()

        with_context = observe(
            _runtime_input(), _session(), runtime_context=context, runtime_state=frozen
        )
        assert with_context.world == WorldFact(payload={"location": "学校"})
        assert calls == []

        without_context = observe(
            _runtime_input(), _session(), runtime_state=frozen
        )
        assert without_context.world == WorldFact(payload={"location": "家"})
        # H-4：世界读面用真实主体身份，不得以 session_id 冒充 user_id
        assert calls == [USER_ID]

    def test_world_fact_without_identity_stays_empty(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            world_engine,
            "collect_facts",
            lambda user_id, provider=None: calls.append(user_id),
        )

        item = observe(_runtime_input(), None)

        assert item.world == WorldFact(payload=None)
        assert calls == []

    def test_memory_signal_projects_recall_result(self):
        item = observe(
            _runtime_input(),
            _session(),
            **_stubs(memories=[_memory("喜欢雨天"), _memory("在写小说"), _memory("养了猫")]),
        )

        assert item.memory == MemorySignalFact(
            count=3, topics=("喜欢雨天", "在写小说", "养了猫")
        )

    def test_memory_signal_never_calls_retriever(self, monkeypatch):
        import app.services.memory2.retriever as retriever

        calls: list = []
        monkeypatch.setattr(
            retriever, "retrieve", lambda *args, **kwargs: calls.append(args) or []
        )

        observe(_runtime_input(), _session(), **_stubs(memories=[_memory("喜欢雨天")]))

        assert calls == []

    def test_memory_topic_is_bounded(self):
        item = observe(
            _runtime_input(), _session(), **_stubs(memories=[_memory("x" * 200)])
        )

        assert item.memory.topics == ("x" * observe_module.MEMORY_TOPIC_MAX_CHARS,)

    def test_memory_signal_absent_without_runtime_context(self):
        item = observe(_runtime_input(), _session())

        assert item.memory is None

    def test_state_fact_from_frozen_runtime_state(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("传入冻结态时不得再取快照")

        monkeypatch.setattr(state_manager, "snapshot", _boom)

        item = observe(
            _runtime_input(), _session(), runtime_state=_frozen_state(version=7)
        )

        assert item.character == CharacterStateFact(
            mood="happy",
            energy=0.42,
            relationship={"stage": "friend"},
            snapshot_version=7,
        )

    def test_state_fact_absent_without_identity(self):
        item = observe(_runtime_input(), None)

        assert item.character is None
        assert item.degradations == ()


class TestDegradation:
    pytestmark = pytest.mark.unit

    def test_world_failure_degrades_without_raise(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("world down")

        monkeypatch.setattr(world_engine, "collect_facts", _boom)

        item = observe(_runtime_input(), _session(), runtime_state=_frozen_state())

        assert item.world is None
        assert item.degraded_fact_sets() == (FACT_SET_WORLD,)
        assert item.degradations[0].error == "RuntimeError"

    def test_character_failure_degrades_without_raise(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("state down")

        monkeypatch.setattr(state_manager, "snapshot", _boom)

        item = observe(
            _runtime_input(), _session(), runtime_context=_runtime_context(world_payload={})
        )

        assert item.character is None
        assert item.degraded_fact_sets() == (FACT_SET_CHARACTER,)

    def test_memory_failure_degrades_without_raise(self):
        class _Exploding:
            @property
            def memories(self):
                raise RuntimeError("memory down")

        item = observe(
            _runtime_input(),
            _session(),
            runtime_context=SimpleNamespace(world=None, memory=_Exploding()),
            runtime_state=_frozen_state(),
        )

        assert item.memory is None
        assert item.degraded_fact_sets() == (FACT_SET_MEMORY,)

    def test_all_fact_sets_failing_still_yields_observation(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr(world_engine, "collect_facts", _boom)
        monkeypatch.setattr(state_manager, "snapshot", _boom)

        item = observe(_runtime_input(), _session())

        assert isinstance(item, Observation)
        assert item.user_input is not None
        assert set(item.degraded_fact_sets()) == {FACT_SET_WORLD, FACT_SET_CHARACTER}
        assert item.present_fact_sets() == ("user_input",)

    def test_trace_records_degradation(self):
        from app.services.trace_collector import TurnTraceSession

        class _Exploding:
            @property
            def memories(self):
                raise RuntimeError("memory down")

        trace = TurnTraceSession()

        observe(
            _runtime_input(),
            _session(),
            runtime_context=SimpleNamespace(world=None, memory=_Exploding()),
            runtime_state=_frozen_state(),
            trace=trace,
        )

        step = trace.steps[-1]
        assert step.name == observe_module.TRACE_STAGE
        assert step.status == "degraded"
        assert step.extra["degraded_fact_sets"] == [FACT_SET_MEMORY]


class TestEventEmission:
    pytestmark = pytest.mark.unit

    def test_observation_recorded_event_emitted(self, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_OBSERVATION_RECORDED, captured.append)
        override_settings(runtime_event_bus_enabled="true")

        item = observe(_runtime_input(), _session(), **_stubs())

        assert len(captured) == 1
        assert captured[0].run_id == "r-observe"
        assert captured[0].session_id == SESSION_ID
        assert captured[0].payload["kind"] == item.kind
        assert captured[0].payload["dedupe_key"] == item.dedupe_key
        assert captured[0].payload["fact_sets"] == [
            "user_input",
            "world",
            "memory",
            "character",
        ]

    def test_event_silent_when_flag_off(self, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_OBSERVATION_RECORDED, captured.append)
        override_settings(runtime_event_bus_enabled="false")

        observe(_runtime_input(), _session(), **_stubs())

        assert captured == []

    def test_event_uses_explicit_run_id(self, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_OBSERVATION_RECORDED, captured.append)
        override_settings(runtime_event_bus_enabled="true")

        observe(_runtime_input(), _session(), run_id="r-explicit", **_stubs())

        assert captured[0].run_id == "r-explicit"


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_observe_module_has_no_forbidden_imports(self):
        tree = ast.parse(OBSERVE_PATH.read_text(encoding="utf-8"))
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

    def test_observe_module_performs_no_writes(self):
        source = OBSERVE_PATH.read_text(encoding="utf-8")
        assert not any(token in source for token in FORBIDDEN_WRITE_TOKENS)

    def test_observation_is_frozen(self):
        item = observe(_runtime_input(), _session(), **_stubs())

        with pytest.raises(dataclasses.FrozenInstanceError):
            item.kind = "schedule"


class TestIntegration:
    pytestmark = pytest.mark.integration

    def test_observe_changes_no_table_rows(self, db_session_factory):
        from app.core.db import Base

        def _counts():
            with db_session_factory() as session:
                return {
                    table.name: session.query(table).count()
                    for table in Base.metadata.sorted_tables
                }

        before = _counts()

        observe(_runtime_input(), _session(), runtime_context=_runtime_context(memories=[]))

        assert _counts() == before

    def test_observe_with_real_world_collect_facts(self, db_session_factory):
        item = observe(_runtime_input(), _session())

        assert isinstance(item, Observation)
        assert item.world is not None
        assert item.degradations == ()

    def test_state_fact_reads_snapshot_without_frozen_state(self, db_session_factory):
        item = observe(_runtime_input(), _session())

        assert item.character is not None
        assert isinstance(item.character.snapshot_version, int)

    async def test_loop_observe_method_returns_observation(self, db_session_factory):
        from app.application import agent_runtime
        from app.application.agent_runtime.loop import AgentLoop
        from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
        from app.application.agent_runtime.profiles import get_profile

        run = agent_runtime.open_run(
            SESSION_ID, RUN_KIND_AUTONOMOUS_TICK, "schedule", "rt007", OBSERVED_AT
        )
        loop = AgentLoop(
            get_profile(RUN_KIND_AUTONOMOUS_TICK),
            user_id=SESSION_ID,
            run=run,
            now=OBSERVED_AT,
            registry={},
        )

        observation = await loop.observe()

        assert isinstance(observation, Observation)
        assert observation.observed_at == run.started_at
        assert observation.kind == "channel_message"
