"""RT-006 Agent Loop Core 测试：段映射 / 可选段裁决 / 驱动 / 降级 / 记账 / 边界。"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest

from app.application import agent_runtime
from app.application.agent_runtime import controller
from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime import loop as loop_module
from app.application.agent_runtime.contracts import (
    EVENT_RUN_CLOSED,
    EVENT_RUN_OPENED,
    EVENT_STAGE_COMPLETED,
    LoopStage,
)
from app.application.agent_runtime.loop import (
    OPTIONAL_PHASES,
    PHASES,
    STAGE_RUNNERS,
    STAGE_TO_PHASE,
    AgentLoop,
    StageContext,
    register_stage_runner,
    resolve_stages,
    stage_phase,
)
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    RUN_KIND_FOREGROUND_CHAT,
    RUN_KINDS,
    RunContext,
)
from app.application.agent_runtime.profiles import ProfileSpec, get_profile
from app.application.agent_runtime.stages.observe import Observation
from app.application.agent_runtime.stages.reason import Intention
from app.repositories import loop_run_repository

LOOP_PATH = Path(loop_module.__file__)
FORBIDDEN_IMPORTS = (
    "app.repositories",
    "app.chains",
    "app.prompts",
    "app.channels.feishu",
)
NOW = datetime(2026, 9, 21, 12, 0, 0)
STUB_STAGES = ("perception", "turn_decisions", "record_handoff")


@pytest.fixture(autouse=True)
def _clean_bus():
    event_bus.clear_subscribers()
    yield
    event_bus.clear_subscribers()


def _spec(
    stages=STUB_STAGES,
    *,
    run_kind=RUN_KIND_EVENT_DRIVEN,
    budget_tier="event",
    critical=(),
    optional=(),
) -> ProfileSpec:
    return ProfileSpec(
        run_kind=run_kind,
        budget_tier=budget_tier,
        stages=tuple(stages),
        llm_capable=frozenset(),
        critical=frozenset(critical),
        optional_stages=frozenset(optional),
    )


def _stub_registry(stages, *, failures=()):
    """打桩注册表：返回 (调用序, registry)。"""
    calls: list[str] = []
    registry: dict[str, object] = {}
    for name in stages:

        def _make(stage=name):
            async def _run(context: StageContext):
                calls.append(stage)
                if stage in failures:
                    raise RuntimeError(f"boom:{stage}")
                return {"status": "ok"}

            return _run

        registry[name] = _make()
    return calls, registry


def _bare_loop(spec, registry, *, run_kind=RUN_KIND_EVENT_DRIVEN, user_id="u1"):
    run = RunContext(
        run_id="r-bare",
        user_id=user_id,
        run_kind=run_kind,
        trigger_type="schedule",
        reason="bare",
        started_at=NOW,
    )
    return AgentLoop(spec, user_id=user_id, run=run, now=NOW, registry=registry)


def _open_run(run_kind=RUN_KIND_EVENT_DRIVEN, user_id="u-loop"):
    return agent_runtime.open_run(user_id, run_kind, "schedule", "rt006", NOW)


class TestStageMapping:
    pytestmark = pytest.mark.unit

    def test_stage_to_phase_covers_all_profile_stages(self):
        for run_kind in RUN_KINDS:
            for stage in get_profile(run_kind).stages:
                assert stage in STAGE_TO_PHASE, f"{run_kind} 的 {stage} 未映射六段环节"

    def test_phases_match_frozen_loop_stage_literal(self):
        assert PHASES == tuple(LoopStage.__args__)
        assert set(STAGE_TO_PHASE.values()) <= set(PHASES)

    def test_optional_phases_are_loop_stages(self):
        assert OPTIONAL_PHASES <= set(PHASES)
        assert OPTIONAL_PHASES == frozenset({"plan", "reflect"})

    def test_stage_phase_fail_closed(self):
        with pytest.raises(ValueError):
            stage_phase("rogue_stage")

    def test_registry_mirrors_controller_plain_stages(self):
        spec = get_profile(RUN_KIND_AUTONOMOUS_TICK)
        plain = {name for name in spec.stages if name not in spec.llm_capable}
        assert set(STAGE_RUNNERS) == plain
        for stage in plain:
            assert callable(controller._autonomous_stage_runner(stage, "u1", None, NOW))
        assert set(spec.llm_capable) & set(STAGE_RUNNERS) == set()

    def test_register_stage_runner_rejects_unknown_stage(self):
        with pytest.raises(ValueError):
            register_stage_runner("rogue_stage", lambda context: None)

    def test_register_stage_runner_rejects_duplicate(self):
        with pytest.raises(ValueError):
            register_stage_runner("perception", lambda context: None)

    def test_loop_raises_for_unregistered_stage(self):
        loop = _bare_loop(_spec(), {})
        with pytest.raises(ValueError):
            loop.stage_runner("perception")

    def test_snapshot_profile_includes_optional_stages(self):
        assert agent_runtime.snapshot_profile(RUN_KIND_AUTONOMOUS_TICK)[
            "optional_stages"
        ] == []
        assert agent_runtime.snapshot_profile(RUN_KIND_FOREGROUND_CHAT)[
            "optional_stages"
        ] == []


class TestResolveStages:
    pytestmark = pytest.mark.unit

    def test_empty_flag_matches_profile_stages(self):
        for run_kind in RUN_KINDS:
            spec = get_profile(run_kind)
            assert resolve_stages(spec) == spec.stages

    def test_flag_off_drops_declared_optional_stage(self):
        spec = _spec(("perception", "reflection_check"), optional=("reflection_check",))

        assert resolve_stages(spec) == ("perception",)

    def test_flag_on_keeps_declared_optional_stage(self, override_settings):
        override_settings(runtime_loop_optional_stages="plan,reflect")
        spec = _spec(("perception", "reflection_check"), optional=("reflection_check",))

        assert resolve_stages(spec) == ("perception", "reflection_check")

    def test_undeclared_stage_is_never_dropped(self, override_settings):
        spec = _spec(("perception", "reflection_check"))

        assert resolve_stages(spec) == ("perception", "reflection_check")

        override_settings(runtime_loop_optional_stages="reflect")
        assert resolve_stages(spec) == ("perception", "reflection_check")

    def test_non_optional_phase_cannot_be_dropped(self, override_settings):
        spec = _spec(("perception",), optional=("perception",))

        assert resolve_stages(spec) == ("perception",)

    def test_plan_phase_has_no_mapped_stage_yet(self):
        assert [name for name, phase in STAGE_TO_PHASE.items() if phase == "plan"] == []
        assert "plan" in OPTIONAL_PHASES

    def test_flag_tolerates_whitespace_and_empty_tokens(self, override_settings):
        override_settings(runtime_loop_optional_stages=" plan , , reflect ")
        spec = _spec(("perception", "reflection_check"), optional=("reflection_check",))

        assert resolve_stages(spec) == ("perception", "reflection_check")

    def test_loop_exposes_phase_scoped_stage_views(self):
        spec = _spec(("perception", "turn_decisions", "record_handoff"))
        loop = _bare_loop(spec, {})

        assert loop.stages == spec.stages
        assert loop.stages_in("observe") == ("perception",)
        assert loop.stages_in("reason") == ("turn_decisions",)
        assert loop.stages_in("update") == ("record_handoff",)
        assert loop.stages_in("plan") == ()
        assert loop.phase_sequence() == ("observe", "reason", "update")


class TestLoopBoundaries:
    pytestmark = pytest.mark.unit

    def test_loop_module_has_no_forbidden_imports(self):
        tree = ast.parse(LOOP_PATH.read_text(encoding="utf-8"))
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

    def test_stage_order_only_from_profiles(self):
        source = LOOP_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        stage_names = set(STAGE_TO_PHASE)
        offenders: list[list[str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List)):
                continue
            literals = [
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            if len(literals) >= 2 and all(value in stage_names for value in literals):
                offenders.append(literals)

        assert offenders == []
        assert "self.spec.stages" not in source
        assert "self.stages = resolve_stages(spec)" in source


class TestLoopDriving:
    pytestmark = pytest.mark.integration

    async def test_run_returns_done_when_all_stages_ok(self, db_session_factory):
        spec = _spec(("perception", "record_handoff"))
        calls, registry = _stub_registry(spec.stages)
        run = _open_run()
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        result = await loop.run()

        assert result.status == "done"
        assert result.run_id == run.run_id
        assert calls == ["perception", "record_handoff"]
        assert loop_run_repository.get(run.run_id).status == "done"

    async def test_run_preserves_declared_stage_order(self, db_session_factory):
        for run_kind in RUN_KINDS:
            spec = get_profile(run_kind)
            calls, registry = _stub_registry(spec.stages)
            run = _open_run(run_kind, user_id=f"u-order-{run_kind}")
            loop = AgentLoop(
                spec, user_id=run.user_id, run=run, now=NOW, registry=registry
            )

            await loop.run()

            assert calls == list(spec.stages), run_kind

    async def test_non_critical_failure_marks_degraded_and_continues(
        self, db_session_factory
    ):
        spec = _spec(("perception", "record_handoff"))
        calls, registry = _stub_registry(spec.stages, failures={"perception"})
        run = _open_run(user_id="u-degraded")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        result = await loop.run()

        assert result.status == "degraded"
        assert calls == ["perception", "record_handoff"]
        row = loop_run_repository.get(run.run_id)
        assert row.status == "degraded"
        assert [step["status"] for step in row.steps] == ["error", "ok"]

    async def test_critical_failure_aborts(self, db_session_factory):
        spec = _spec(("perception", "record_handoff"), critical=("record_handoff",))
        calls, registry = _stub_registry(spec.stages, failures={"record_handoff"})
        run = _open_run(user_id="u-aborted")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        result = await loop.run()

        assert result.status == "aborted"
        assert calls == ["perception", "record_handoff"]
        row = loop_run_repository.get(run.run_id)
        assert row.status == "aborted"
        assert [step["step"] for step in row.steps] == [
            "perception",
            "record_handoff",
            "abort",
        ]

    async def test_unregistered_stage_is_fail_closed(self, db_session_factory):
        spec = _spec(("perception", "record_handoff"))
        _, registry = _stub_registry(("perception",))
        run = _open_run(user_id="u-missing-impl")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        result = await loop.run()

        assert result.status == "aborted"
        row = loop_run_repository.get(run.run_id)
        assert [step["step"] for step in row.steps] == ["perception", "abort"]
        assert row.steps[-1]["error"] == "ValueError"

    async def test_phase_methods_run_only_their_phase(self, db_session_factory):
        spec = _spec(("perception", "record_handoff"))
        calls, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-phase")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        updated = await loop.update()
        assert set(updated) == {"record_handoff"}
        assert updated["record_handoff"]["status"] == "ok"
        assert calls == ["record_handoff"]

        assert await loop.plan() is None
        assert await loop.act() is None
        assert await loop.reflect() is None
        assert calls == ["record_handoff"]

    async def test_observe_method_delegates_to_rt007_stage(self, db_session_factory):
        """RT-007 起 `observe` 段本体由显式实现接管（RT-006 D6「各段替换为显式实现」）。"""
        spec = _spec(("perception",))
        calls, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-observe-deleg")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        observation = await loop.observe()

        assert isinstance(observation, Observation)
        assert observation.observed_at == run.started_at
        assert calls == []
        assert loop.observation is observation

    async def test_reason_method_delegates_to_rt008_stage(self, db_session_factory):
        """RT-008 起 `reason` 段本体由显式实现接管（决策管线唯一入口）。"""
        spec = _spec(
            ("turn_decisions",),
            run_kind=RUN_KIND_FOREGROUND_CHAT,
            budget_tier="foreground",
        )
        calls, registry = _stub_registry(spec.stages)
        run = _open_run(RUN_KIND_FOREGROUND_CHAT, user_id="u-reason-deleg")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        intention = await loop.reason()

        assert isinstance(intention, Intention)
        assert intention.decided_at == run.started_at
        assert calls == []
        assert loop.intention is intention

    async def test_stage_inputs_reach_the_runner(self, db_session_factory):
        seen: list[dict] = []

        async def _capture(context: StageContext):
            seen.append(dict(context.inputs))
            return {"status": "ok"}

        spec = _spec(("record_handoff",))
        run = _open_run(user_id="u-inputs")
        loop = AgentLoop(
            spec,
            user_id=run.user_id,
            run=run,
            now=NOW,
            registry={"record_handoff": _capture},
        )

        await loop.update("act-1", ["ins-1"])

        assert seen == [{"action_result": "act-1", "insights": ["ins-1"]}]

    async def test_stage_events_emitted_per_stage(self, db_session_factory, override_settings):
        spec = _spec(("perception", "record_handoff"))
        _, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-events-on")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)
        captured: list = []
        event_bus.subscribe(EVENT_STAGE_COMPLETED, captured.append)
        override_settings(runtime_event_bus_enabled="true")

        await loop.run()

        assert len(captured) == len(spec.stages)
        assert [event.payload["stage"] for event in captured] == list(spec.stages)
        assert captured[0].run_id == run.run_id
        assert captured[0].correlation_id == run.run_id

    async def test_stage_events_silent_when_flag_off(self, db_session_factory, override_settings):
        spec = _spec(("perception", "record_handoff"))
        _, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-events-off")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)
        captured: list = []
        event_bus.subscribe(EVENT_STAGE_COMPLETED, captured.append)
        override_settings(runtime_event_bus_enabled="false")

        await loop.run()

        assert captured == []

    async def test_run_emits_open_and_close_events(self, db_session_factory, override_settings):
        override_settings(runtime_event_bus_enabled="true")
        spec = _spec(("perception",))
        _, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-lifecycle")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)
        captured: list = []
        event_bus.subscribe(EVENT_RUN_OPENED, captured.append)
        event_bus.subscribe(EVENT_RUN_CLOSED, captured.append)

        result = await loop.run()

        assert [event.event_type for event in captured] == [
            EVENT_RUN_OPENED,
            EVENT_RUN_CLOSED,
        ]
        assert captured[-1].payload["status"] == result.status == "done"

    async def test_run_writes_loop_runs_only(self, db_session_factory):
        from sqlalchemy import event
        from sqlalchemy.orm import Session

        touched: list[str] = []

        def _before_flush(session, flush_context, instances):
            for obj in list(session.new) + list(session.dirty) + list(session.deleted):
                touched.append(type(obj).__tablename__)

        spec = _spec(("perception", "record_handoff"))
        _, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-writes")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)
        event.listen(Session, "before_flush", _before_flush)
        try:
            await loop.run()
        finally:
            event.remove(Session, "before_flush", _before_flush)

        assert set(touched) == {"loop_runs"}
        row = loop_run_repository.get(run.run_id)
        assert row.status == "done"
        assert [step["step"] for step in row.steps] == list(spec.stages)
        assert row.budget_state

    async def test_steps_key_set_matches_controller_accounting(self, db_session_factory):
        spec = _spec(("perception",))
        _, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-accounting")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        await loop.run()

        legacy_run = _open_run(user_id="u-accounting-legacy")
        legacy_steps: list = []
        stub = registry["perception"]
        await controller.run_stage_async(
            legacy_run,
            legacy_steps,
            "perception",
            lambda: stub(
                StageContext(
                    stage="perception",
                    phase="observe",
                    run_context=legacy_run,
                    user_id=legacy_run.user_id,
                    now=NOW,
                )
            ),
            critical=False,
        )
        recorded = loop_run_repository.get(run.run_id).steps[0]

        assert set(recorded) == set(legacy_steps[0])
        assert recorded["step"] == legacy_steps[0]["step"] == "perception"
        assert isinstance(recorded["duration_ms"], float)

    async def test_foreground_run_skips_user_write_lock(
        self, db_session_factory, monkeypatch
    ):
        def _boom(user_id):
            raise AssertionError("前台 Run 不得获取 per-user 写锁")

        monkeypatch.setattr(
            "app.application.post_process.get_user_write_lock", _boom
        )
        spec = _spec(
            ("perception",),
            run_kind=RUN_KIND_FOREGROUND_CHAT,
            budget_tier="foreground",
        )
        _, registry = _stub_registry(spec.stages)
        run = _open_run(RUN_KIND_FOREGROUND_CHAT, user_id="u-foreground")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        result = await loop.run()

        assert result.status == "done"

    async def test_background_run_takes_user_write_lock(
        self, db_session_factory, monkeypatch
    ):
        import asyncio

        acquired: list[str] = []
        real_lock = asyncio.Lock()

        def _lock(user_id):
            acquired.append(user_id)
            return real_lock

        monkeypatch.setattr("app.application.post_process.get_user_write_lock", _lock)
        spec = _spec(
            ("perception",),
            run_kind=RUN_KIND_AUTONOMOUS_TICK,
            budget_tier="background",
        )
        _, registry = _stub_registry(spec.stages)
        run = _open_run(RUN_KIND_AUTONOMOUS_TICK, user_id="u-background")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        await loop.run()

        assert acquired == ["u-background"]

    async def test_run_uses_resolved_optional_stages(self, db_session_factory, override_settings):
        override_settings(runtime_loop_optional_stages="")
        spec = _spec(
            ("perception", "reflection_check"),
            optional=("reflection_check",),
        )
        calls, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-optional")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        await loop.run()

        assert loop.stages == ("perception",)
        assert calls == ["perception"]
        row = loop_run_repository.get(run.run_id)
        assert [step["step"] for step in row.steps] == ["perception"]
        assert row.status == "done"

    async def test_session_id_reaches_events(self, db_session_factory, override_settings):
        override_settings(runtime_event_bus_enabled="true")
        spec = _spec(("perception",))
        _, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-session")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)
        captured: list = []
        event_bus.subscribe(EVENT_RUN_OPENED, captured.append)
        session = agent_runtime.build_session_context("S-loop", channel="web")

        await loop.run(session_context=session)

        assert captured[0].session_id == "S-loop"

    async def test_run_result_carries_budget_account(self, db_session_factory):
        spec = _spec(("perception",))
        _, registry = _stub_registry(spec.stages)
        run = _open_run(user_id="u-budget")
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry=registry)

        result = await loop.run()

        assert set(result.budget_account) >= {"status", "used_calls", "token_total"}
        assert result.trace_ref is None
        assert result.intention is None
