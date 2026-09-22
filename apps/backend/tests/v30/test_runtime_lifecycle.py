"""V3.0 评审修复回归（RT-ALL-code-review）：Run 生命周期必须无孤儿。

覆盖评审 Must Fix 清单中「取消/中断也必须关账」与「失败路径不得双写」两条，
以及 H-6 事件升级终态传播。全部零 LLM、内存 SQLite。
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from app.application.agent_runtime import controller
from app.application.agent_runtime import state as state_manager
from app.application.agent_runtime.controller import open_run, run_stage_async
from app.application.agent_runtime.loop import AgentLoop, StageContext
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    TERMINAL_ABORTED,
    RunContext,
)
from app.application.agent_runtime.profiles import ProfileSpec, get_profile
from app.repositories import loop_run_repository

NOW = datetime(2026, 9, 22, 12, 0, 0)
STAGES = ("perception", "record_handoff")


class _Boom(BaseException):
    """非 Exception 的 BaseException（模拟 KeyboardInterrupt 一类中断）。"""


def _spec(stages=STAGES, *, run_kind=RUN_KIND_EVENT_DRIVEN) -> ProfileSpec:
    return ProfileSpec(
        run_kind=run_kind,
        budget_tier="event",
        stages=tuple(stages),
        llm_capable=frozenset(),
        critical=frozenset(),
        optional_stages=frozenset(),
    )


def _blocking_registry(stages, started: asyncio.Event) -> dict:
    registry: dict[str, object] = {}
    for name in stages:

        def _make(stage=name):
            async def _run(context: StageContext):
                started.set()
                await asyncio.Event().wait()
                return {"status": "ok"}

            return _run

        registry[name] = _make()
    return registry


def _raising_registry(stages, exc: BaseException) -> dict:
    registry: dict[str, object] = {}
    for name in stages:

        def _make(stage=name):
            async def _run(context: StageContext):
                raise exc

            return _run

        registry[name] = _make()
    return registry


def _loop(run: RunContext, spec: ProfileSpec, registry: dict, user_id="u-life") -> AgentLoop:
    return AgentLoop(spec, user_id=user_id, run=run, now=NOW, registry=registry)


def _steps(run_id: str) -> list[dict]:
    row = loop_run_repository.get(run_id)
    assert row is not None
    return list(row.steps or [])


class TestCancellationClosesLedger:
    pytestmark = pytest.mark.unit

    def test_cancelled_run_is_closed_as_aborted(self, db_session_factory):
        async def _scenario() -> str:
            started = asyncio.Event()
            run = open_run("u-cancel", RUN_KIND_EVENT_DRIVEN, "schedule", "cancel", NOW)
            spec = _spec()
            loop = _loop(run, spec, _blocking_registry(spec.stages, started))
            task = asyncio.ensure_future(loop.run())
            await asyncio.wait_for(started.wait(), timeout=5.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return run.run_id

        run_id = asyncio.run(_scenario())

        row = loop_run_repository.get(run_id)
        assert row is not None
        assert row.status == TERMINAL_ABORTED
        assert row.finished_at is not None
        assert any(step.get("step") == "cancel" for step in row.steps or [])

    def test_base_exception_run_is_closed_as_aborted(self, db_session_factory):
        async def _scenario() -> str:
            run = open_run("u-boom", RUN_KIND_EVENT_DRIVEN, "schedule", "boom", NOW)
            spec = _spec()
            loop = _loop(run, spec, _raising_registry(spec.stages, _Boom("boom")))
            with pytest.raises(_Boom):
                await loop.run()
            return run.run_id

        run_id = asyncio.run(_scenario())

        row = loop_run_repository.get(run_id)
        assert row is not None
        assert row.status == TERMINAL_ABORTED
        assert row.finished_at is not None

    def test_legacy_cycle_closes_ledger_on_cancellation(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(world_enabled="false")

        async def _scenario() -> str:
            started = asyncio.Event()

            async def _blocking_step(*_args, **_kwargs):
                started.set()
                await asyncio.Event().wait()

            monkeypatch.setattr(
                controller,
                "_autonomous_stage_runner",
                lambda name, user_id, run, now: _blocking_step,
            )
            task = asyncio.ensure_future(
                controller._legacy_run_autonomous_cycle(  # pylint: disable=protected-access
                    "u-legacy", now=NOW, trigger_type="schedule", reason="cancel"
                )
            )
            await asyncio.wait_for(started.wait(), timeout=5.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            rows = loop_run_repository.list_recent(user_id="u-legacy")
            return rows[0].id

        run_id = asyncio.run(_scenario())

        row = loop_run_repository.get(run_id)
        assert row is not None
        assert row.status == TERMINAL_ABORTED
        assert row.finished_at is not None
        assert any(step.get("step") == "cancel" for step in row.steps or [])

    def test_legacy_cycle_closes_ledger_on_base_exception(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(world_enabled="false")

        async def _scenario() -> str:
            async def _boom_step(*_args, **_kwargs):
                raise _Boom("legacy")

            monkeypatch.setattr(
                controller,
                "_autonomous_stage_runner",
                lambda name, user_id, run, now: _boom_step,
            )
            with pytest.raises(_Boom):
                await controller._legacy_run_autonomous_cycle(  # pylint: disable=protected-access
                    "u-legacy-boom", now=NOW, trigger_type="schedule", reason="boom"
                )
            rows = loop_run_repository.list_recent(user_id="u-legacy-boom")
            return rows[0].id

        run_id = asyncio.run(_scenario())

        row = loop_run_repository.get(run_id)
        assert row is not None
        assert row.status == TERMINAL_ABORTED


class TestProjectionRelease:
    pytestmark = pytest.mark.unit

    def test_run_releases_projections_on_close(
        self, db_session_factory, override_settings
    ):
        override_settings(runtime_state_versioning_enabled="true")

        async def _scenario() -> RunContext:
            run = open_run("u-proj", RUN_KIND_EVENT_DRIVEN, "schedule", "proj", NOW)
            state_manager.activate(run, "u-proj")
            run.data["runtime_context"] = {"segment": "x"}
            assert "runtime_state" in run.data
            spec = _spec()
            registry = {
                name: (lambda context: _ok()) for name in spec.stages
            }
            await _loop(run, spec, registry).run()
            return run

        run = asyncio.run(_scenario())

        assert "runtime_state" not in run.data
        assert "runtime_context" not in run.data


async def _ok() -> dict:
    return {"status": "ok"}


class TestSingleStepAccounting:
    pytestmark = pytest.mark.unit

    def test_failed_stage_records_single_step(self, db_session_factory):
        async def _boom():
            raise RuntimeError("stage-failed")

        async def _scenario() -> str:
            run = open_run("u-step", RUN_KIND_EVENT_DRIVEN, "schedule", "step", NOW)
            steps: list = []
            entry = await run_stage_async(run, steps, "perception", _boom)
            assert entry["status"] == "error"
            return run.run_id, len(steps)

        run_id, in_memory = asyncio.run(_scenario())

        assert in_memory == 1
        assert len(_steps(run_id)) == 1


class TestEventPregateStatusPropagation:
    pytestmark = pytest.mark.unit

    def test_inner_aborted_propagates_to_outer_run(
        self, db_session_factory, override_settings, monkeypatch
    ):
        from app.repositories import outbox_repository

        override_settings(
            runtime_autonomous_cycle_enabled="true",
            AGENT_EVENT_ESCALATION_TYPES="action_result",
            world_enabled="false",
        )
        monkeypatch.setattr(
            controller,
            "run_autonomous_cycle",
            _stub_cycle(TERMINAL_ABORTED),
        )
        outbox_repository.insert({"user_id": "u-pregate", "world_ops": []}, "evt-rev", now=NOW)

        escalated = asyncio.run(controller.run_event_pregate(now=NOW))

        assert escalated == 0
        rows = [
            row
            for row in loop_run_repository.list_recent(user_id="u-pregate")
            if row.run_kind == RUN_KIND_EVENT_DRIVEN
        ]
        assert rows
        assert rows[0].status == TERMINAL_ABORTED
        assert rows[0].finished_at is not None

    def test_inner_done_keeps_outer_done(
        self, db_session_factory, override_settings, monkeypatch
    ):
        from app.repositories import outbox_repository

        override_settings(
            runtime_autonomous_cycle_enabled="true",
            AGENT_EVENT_ESCALATION_TYPES="action_result",
            world_enabled="false",
        )
        monkeypatch.setattr(controller, "run_autonomous_cycle", _stub_cycle("done"))
        outbox_repository.insert({"user_id": "u-pregate-ok", "world_ops": []}, "evt-rev-ok", now=NOW)

        escalated = asyncio.run(controller.run_event_pregate(now=NOW))

        assert escalated == 1
        rows = [
            row
            for row in loop_run_repository.list_recent(user_id="u-pregate-ok")
            if row.run_kind == RUN_KIND_EVENT_DRIVEN
        ]
        assert rows[0].status == "done"
        assert rows[0].steps[0]["inner_status"] == "done"


def _stub_cycle(status: str):
    async def _run(*_args, **_kwargs) -> str:
        return status

    return _run


def test_event_pregate_requires_escalation_whitelist(
    db_session_factory, override_settings
):
    override_settings(AGENT_EVENT_ESCALATION_TYPES="")

    assert asyncio.run(controller.run_event_pregate(now=NOW)) == 0


def test_autonomous_profile_stage_set_unchanged():
    """零回归护栏：本次修复不得改动 autonomous_tick Profile 的段序列。"""
    spec = get_profile(RUN_KIND_AUTONOMOUS_TICK)

    assert spec.stages == (
        "perception",
        "state_update",
        "state_snapshot",
        "goal_check",
        "goal_stack",
        "goal_supply",
        "goal_advance",
        "memory_retrieval",
        "reflection_check",
        "decision",
        "world_experience",
    )


class TestRepositoryAccessLayering:
    """H-3：域读必须经 services 门面；Run SoT 自身仓储是唯一豁免。"""

    pytestmark = pytest.mark.unit

    def _repository_imports(self, module) -> list[str]:
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
        return sorted(
            name
            for name in names
            if name.startswith("app.repositories") and name != "app.repositories"
        )

    def test_stages_do_not_read_domain_repositories(self):
        from app.application.agent_runtime.stages import act, plan, update

        for module in (plan, act, update):
            assert self._repository_imports(module) == [], module.__name__

    def test_controller_only_uses_run_scoped_repositories(self):
        from app.application.agent_runtime import controller

        allowed = {"app.repositories.loop_run_repository", "app.repositories.llm_call_repository"}

        assert set(self._repository_imports(controller)) <= allowed

    def test_domain_reads_go_through_service_facades(self):
        from app.services import goal_service, outbox_service
        from app.services.action import manager as action_manager

        for facade in (goal_service.get_goal, goal_service.get_plan, outbox_service.list_pending):
            assert callable(facade)
        assert callable(action_manager.get_record)


class TestSingleLoopDecision:
    """H-1 裁决 B：唯一循环 = Profile 阶段序列；六段方法是影子实现（未接入 run()）。"""

    pytestmark = pytest.mark.unit

    SHADOW = {"observe", "reason", "plan", "act", "reflect", "update"}

    def test_run_never_calls_shadow_stage_methods(self):
        from app.application.agent_runtime import loop as loop_module

        tree = ast.parse(Path(loop_module.__file__).read_text(encoding="utf-8"))
        run_fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
        )
        called = {
            node.func.attr
            for node in ast.walk(run_fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        assert called & self.SHADOW == set(), sorted(called & self.SHADOW)

    def test_shadow_markers_are_declared(self):
        from app.application.agent_runtime import loop as loop_module
        from app.application.agent_runtime import stages

        assert loop_module.SHADOW_STAGE_METHODS is True
        assert stages.SHADOW_STAGE_IMPLEMENTATION is True

    def test_shadow_stage_functions_are_not_exported(self):
        import app.application.agent_runtime as runtime

        assert self.SHADOW & set(runtime.__all__) == set()
