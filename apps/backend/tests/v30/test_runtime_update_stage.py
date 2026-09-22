"""RT-012 Update / Feedback Stage 测试：路由 / 写面 / 前台不阻塞 / 隔离。"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime.contracts import (
    EVENT_MEMORY_UPDATED,
    EVENT_RELATIONSHIP_UPDATED,
    EVENT_STATE_VERSION_BUMPED,
)
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    RUN_KIND_FOREGROUND_CHAT,
    RunContext,
)
from app.application.agent_runtime.profiles import ProfileSpec, get_profile
from app.application.agent_runtime.session import build_session_context
from app.application.agent_runtime.stages import update as update_module
from app.application.agent_runtime.stages.update import (
    ROUTE_MEMORY,
    ROUTE_OUTBOX,
    ROUTE_POST_PROCESS,
    ROUTE_RELATIONSHIP,
    TARGET_MEMORY,
    TARGET_RELATIONSHIP,
    TARGET_STATE,
    Feedback,
    FeedbackItem,
    PostProcessHandoff,
    routes_for,
    update,
)

UPDATE_PATH = Path(update_module.__file__)
FORBIDDEN_IMPORTS = (
    "app.chains",
    "app.prompts",
    "app.channels.feishu",
    "app.services.development",
    "app.services.action.executor",
)
FORBIDDEN_WRITE_TOKENS = (
    "session.add",
    ".commit(",
    "world_engine",
    "outbox_consumer",
    "deferred_world_op",
    "InsightRow",
    "RelationshipStateRow",
)

NOW = datetime(2026, 9, 21, 12, 0, 0)
USER_ID = "u-update"
SESSION_ID = "S-update"


@pytest.fixture(autouse=True)
def _clean_bus():
    event_bus.clear_subscribers()
    yield
    event_bus.clear_subscribers()


def _run(run_kind=RUN_KIND_AUTONOMOUS_TICK, user_id=USER_ID):
    return RunContext(
        run_id="r-update",
        user_id=user_id,
        run_kind=run_kind,
        trigger_type="schedule",
        reason="rt012",
        started_at=NOW,
    )


def _session(**overrides):
    return build_session_context(SESSION_ID, channel="web", now=NOW, **overrides)


def _spec(run_kind=RUN_KIND_AUTONOMOUS_TICK, budget_tier="background"):
    return ProfileSpec(
        run_kind=run_kind,
        budget_tier=budget_tier,
        stages=("perception",),
        llm_capable=frozenset(),
        critical=frozenset(),
        optional_stages=frozenset(),
    )


def _action_outcome(action_id="a-1"):
    return SimpleNamespace(
        action_id=action_id,
        action_type="create_reminder",
        source="autonomy",
        executed=True,
    )


def _record(record_id="a-1"):
    from app.models.action import ActionRecord

    return ActionRecord(
        id=record_id,
        user_id=USER_ID,
        session_id=SESSION_ID,
        action_type="create_reminder",
        status="succeeded",
        attempt=1,
        params={"content": "喝水"},
        created_at=NOW,
        updated_at=NOW,
    )


def _stub_record(monkeypatch, record=None):
    from app.repositories import action_repository

    monkeypatch.setattr(
        action_repository,
        "get_record",
        lambda record_id: record if record is not None else _record(record_id),
    )


def _stub_ingest(monkeypatch, *, row=None, raises=None):
    calls: list = []
    from app.services.memory2 import ingest

    def _ingest_from_action_record(record, character_id="asuna", trace=None):
        calls.append({"record_id": record.id, "character_id": character_id})
        if raises is not None:
            raise raises
        return row

    monkeypatch.setattr(ingest, "ingest_from_action_record", _ingest_from_action_record)
    return calls


def _stub_post_process(monkeypatch, *, raises=None, delay=0.0):
    calls: list = []
    from app.application import post_process

    def _schedule_post_process(**kwargs):
        calls.append(kwargs)
        if raises is not None:
            raise raises

        async def _slow():
            if delay:
                await asyncio.sleep(delay)

        return asyncio.get_event_loop().create_task(_slow())

    monkeypatch.setattr(post_process, "schedule_post_process", _schedule_post_process)
    return calls


def _handoff():
    return PostProcessHandoff(
        session_id=SESSION_ID,
        user_id=USER_ID,
        user_input="在吗",
        ai_reply="在的",
        state=SimpleNamespace(user_id=USER_ID),
        analysis=SimpleNamespace(),
    )


def _run_update(*, action_outcome=None, spec=None, run=None, handoff=None, trace=None):
    return asyncio.run(
        update(
            action_outcome=action_outcome,
            reflect_outcome=None,
            context=None,
            session_context=_session(),
            spec=spec or _spec(),
            handoff=handoff,
            run=run or _run(),
            now=NOW,
            trace=trace,
        )
    )


class TestRoutes:
    pytestmark = pytest.mark.unit

    def test_foreground_only_hands_off(self):
        routes = routes_for(get_profile(RUN_KIND_FOREGROUND_CHAT), _action_outcome())

        assert routes == (ROUTE_POST_PROCESS,)

    def test_background_routes_depend_on_action_outcome(self):
        assert routes_for(_spec(), None) == (ROUTE_POST_PROCESS,)
        assert routes_for(_spec(), _action_outcome()) == (
            ROUTE_POST_PROCESS,
            ROUTE_MEMORY,
            ROUTE_RELATIONSHIP,
            ROUTE_OUTBOX,
        )

    def test_routes_are_deterministic_and_exclude_development(self):
        first = routes_for(_spec(), _action_outcome())
        second = routes_for(_spec(), _action_outcome())

        assert first == second
        joined = " ".join(first)
        assert "development" not in joined
        assert "personality" not in joined
        assert "evolution" not in joined

    def test_event_driven_profile_uses_background_routes(self):
        assert routes_for(get_profile(RUN_KIND_EVENT_DRIVEN), _action_outcome()) == (
            ROUTE_POST_PROCESS,
            ROUTE_MEMORY,
            ROUTE_RELATIONSHIP,
            ROUTE_OUTBOX,
        )


class TestForeground:
    pytestmark = pytest.mark.unit

    def test_foreground_hands_off_without_waiting(self, monkeypatch):
        calls = _stub_post_process(monkeypatch)
        ingest_calls = _stub_ingest(monkeypatch)

        outcome = _run_update(
            action_outcome=_action_outcome(),
            spec=_spec(RUN_KIND_FOREGROUND_CHAT, "foreground"),
            handoff=_handoff(),
        )

        assert isinstance(outcome, Feedback)
        assert outcome.handed_off is True
        assert len(calls) == 1
        assert calls[0]["session_id"] == SESSION_ID
        assert ingest_calls == []
        assert [item.target for item in outcome.items] == [TARGET_STATE]

    def test_foreground_without_handoff_inputs_is_not_applied(self, monkeypatch):
        calls = _stub_post_process(monkeypatch)
        run = _run(RUN_KIND_FOREGROUND_CHAT)

        outcome = _run_update(
            action_outcome=_action_outcome(),
            spec=_spec(RUN_KIND_FOREGROUND_CHAT, "foreground"),
            run=run,
        )

        assert calls == []
        assert outcome.handed_off is False
        assert outcome.items[0].applied is False
        assert outcome.items[0].detail["reason"] == "handoff_inputs_absent"

    def test_handoff_returns_before_background_completes(self, monkeypatch):
        _stub_post_process(monkeypatch, delay=0.3)

        started = time.perf_counter()
        outcome = _run_update(
            action_outcome=_action_outcome(),
            spec=_spec(RUN_KIND_FOREGROUND_CHAT, "foreground"),
            handoff=_handoff(),
        )
        elapsed = time.perf_counter() - started

        assert outcome.handed_off is True
        assert elapsed < 0.2, "前台交接不得等待后台任务完成"


class TestBackground:
    pytestmark = pytest.mark.unit

    def test_background_applies_sync_channels(self, monkeypatch):
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        ingest_calls = _stub_ingest(monkeypatch, row=SimpleNamespace(id="mc-1"))

        outcome = _run_update(action_outcome=_action_outcome())

        assert len(ingest_calls) == 1
        assert ingest_calls[0]["record_id"] == "a-1"
        applied = {item.target: item for item in outcome.items if item.applied}
        assert applied[TARGET_MEMORY].detail["candidate_id"] == "mc-1"
        relationship_item = next(
            i for i in outcome.items if i.channel == ROUTE_RELATIONSHIP
        )
        assert relationship_item.applied is False
        assert relationship_item.detail["handled_by"] == "act.integrate_result"

    def test_relationship_route_is_acknowledged_not_reapplied(self, monkeypatch):
        """关系信号已由 Act 的 `integrate_result` 投递；本段只登记路由，不重投。"""
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)
        run = _run()

        outcome = _run_update(action_outcome=_action_outcome(), run=run)

        relationship_item = next(
            i for i in outcome.items if i.channel == ROUTE_RELATIONSHIP
        )
        assert relationship_item.target == TARGET_RELATIONSHIP
        assert relationship_item.detail["handled_by"] == "act.integrate_result"
        assert run.degraded is False

    def test_world_write_goes_through_outbox(self, monkeypatch):
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)
        run = _run()

        outcome = _run_update(action_outcome=_action_outcome(), run=run)

        world_items = [item for item in outcome.items if item.channel == ROUTE_OUTBOX]
        assert len(world_items) == 1
        assert world_items[0].target == "world"
        assert world_items[0].detail["handled_by"] == "act.integrate_result"
        assert world_items[0].applied is False
        assert run.degraded is False

    def test_missing_action_record_marks_channel_not_applied(self, monkeypatch):
        from app.repositories import action_repository

        monkeypatch.setattr(action_repository, "get_record", lambda record_id: None)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)
        run = _run()

        outcome = _run_update(action_outcome=_action_outcome(), run=run)

        memory_item = next(i for i in outcome.items if i.channel == ROUTE_MEMORY)
        assert memory_item.applied is False
        assert memory_item.detail["error"] == "record_not_found"
        assert run.degraded is True


class TestIsolation:
    pytestmark = pytest.mark.unit

    def test_channel_failure_is_isolated(self, monkeypatch):
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch, raises=RuntimeError("memory down"))
        run = _run()

        outcome = _run_update(action_outcome=_action_outcome(), run=run)

        memory_item = next(i for i in outcome.items if i.channel == ROUTE_MEMORY)
        relationship_item = next(
            i for i in outcome.items if i.channel == ROUTE_RELATIONSHIP
        )
        assert memory_item.applied is False
        assert memory_item.detail["error"] == "RuntimeError"
        assert relationship_item.applied is False
        assert relationship_item.detail["handled_by"] == "act.integrate_result"
        assert run.degraded is True

    def test_handoff_failure_is_isolated(self, monkeypatch):
        _stub_post_process(monkeypatch, raises=RuntimeError("handoff down"))
        run = _run(RUN_KIND_FOREGROUND_CHAT)

        outcome = _run_update(
            action_outcome=_action_outcome(),
            spec=_spec(RUN_KIND_FOREGROUND_CHAT, "foreground"),
            handoff=_handoff(),
            run=run,
        )

        assert outcome.handed_off is False
        assert outcome.items[0].detail["error"] == "RuntimeError"
        assert run.degraded is True


class TestEvents:
    pytestmark = pytest.mark.unit

    def test_events_emitted_per_target(self, monkeypatch, override_settings):
        captured: list = []
        for event_type in (
            EVENT_MEMORY_UPDATED,
            EVENT_RELATIONSHIP_UPDATED,
            EVENT_STATE_VERSION_BUMPED,
        ):
            event_bus.subscribe(event_type, captured.append)
        override_settings(runtime_event_bus_enabled="true")
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)

        outcome = _run_update(action_outcome=_action_outcome(), handoff=_handoff())

        kinds = sorted(event.event_type for event in captured)
        assert kinds == sorted(
            [EVENT_MEMORY_UPDATED, EVENT_RELATIONSHIP_UPDATED, EVENT_STATE_VERSION_BUMPED]
        )
        assert set(outcome.emitted_events) == set(kinds)
        assert captured[0].run_id == "r-update"

    def test_events_silent_when_flag_off(self, monkeypatch, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_MEMORY_UPDATED, captured.append)
        override_settings(runtime_event_bus_enabled="false")
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)

        _run_update(action_outcome=_action_outcome())

        assert captured == []

    def test_applied_routes_observe_state_manager(self, monkeypatch, override_settings):
        from app.application.agent_runtime import state as state_manager

        override_settings(runtime_event_bus_enabled="true")
        state_manager.reset_observed_cache()
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)

        outcome = _run_update(action_outcome=_action_outcome(), handoff=_handoff())

        assert state_manager.observed_version("memory", "r-update") is not None
        observed = state_manager.observed_version("memory", "r-update")
        assert observed.detail["event_type"] == EVENT_MEMORY_UPDATED
        assert EVENT_MEMORY_UPDATED in outcome.emitted_events

    def test_unapplied_routes_do_not_observe(self, monkeypatch, override_settings):
        from app.application.agent_runtime import state as state_manager

        override_settings(runtime_event_bus_enabled="true")
        state_manager.reset_observed_cache()
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch, raises=RuntimeError("ingest boom"))

        run = RunContext(
            run_id="r-update-fail",
            user_id="u-1",
            run_kind=RUN_KIND_AUTONOMOUS_TICK,
            trigger_type="schedule",
            reason="t",
            started_at=datetime.now(),
        )
        _run_update(action_outcome=_action_outcome(), run=run)

        assert state_manager.observed_version("memory", "r-update-fail") is None


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _code_identifiers(path: Path) -> set[str]:
    """代码里出现的名字 / 属性 / 关键字实参（**不含 docstring**）。

    按裸文本扫描会被 docstring 里「`deferred_world_op → outbox`」这类**通道说明**误伤。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
    return found


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_update_module_has_no_forbidden_imports(self):
        imported = _imported_modules(UPDATE_PATH)
        offenders = [
            name
            for name in imported
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORTS
            )
        ]
        assert offenders == []

    def test_no_direct_domain_writes(self):
        used = _code_identifiers(UPDATE_PATH)
        source = UPDATE_PATH.read_text(encoding="utf-8")

        assert not (used & set(FORBIDDEN_WRITE_TOKENS))
        assert "session.add" not in source
        assert ".commit(" not in source

    def test_feedback_is_frozen(self, monkeypatch):
        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)

        outcome = _run_update(action_outcome=_action_outcome())

        with pytest.raises(dataclasses.FrozenInstanceError):
            outcome.handed_off = True


class TestIntegration:
    pytestmark = pytest.mark.integration

    def test_foreground_update_writes_nothing(self, db_session_factory, monkeypatch):
        from sqlalchemy import event as sqlalchemy_event
        from sqlalchemy.orm import Session

        _stub_post_process(monkeypatch)
        touched: list[str] = []

        def _before_flush(session, flush_context, instances):
            for obj in list(session.new) + list(session.dirty) + list(session.deleted):
                touched.append(type(obj).__tablename__)

        sqlalchemy_event.listen(Session, "before_flush", _before_flush)
        try:
            outcome = _run_update(
                action_outcome=_action_outcome(),
                spec=_spec(RUN_KIND_FOREGROUND_CHAT, "foreground"),
                handoff=_handoff(),
            )
        finally:
            sqlalchemy_event.remove(Session, "before_flush", _before_flush)

        assert outcome.handed_off is True
        assert touched == []

    def test_memory_candidates_written_via_ingest_only(
        self, db_session_factory, monkeypatch
    ):
        """记忆通道走既有 `ingest_from_action_record`：候选行的幂等键不变。"""
        from app.services.memory2 import ingest

        record = _record()
        _stub_record(monkeypatch, record)
        _stub_post_process(monkeypatch)
        calls: list = []
        real_ingest = ingest.ingest_from_action_record

        def _spy(rec, character_id="asuna", trace=None):
            calls.append(rec.id)
            return real_ingest(rec, character_id, trace)

        monkeypatch.setattr(ingest, "ingest_from_action_record", _spy)

        _run_update(action_outcome=_action_outcome(record.id))

        assert calls == [record.id]

    async def test_loop_update_method_delegates_to_rt012_stage(
        self, db_session_factory, monkeypatch
    ):
        from app.application import agent_runtime
        from app.application.agent_runtime.loop import AgentLoop

        _stub_record(monkeypatch)
        _stub_post_process(monkeypatch)
        _stub_ingest(monkeypatch)
        spec = get_profile(RUN_KIND_AUTONOMOUS_TICK)
        run = agent_runtime.open_run(
            "u-loop-update", RUN_KIND_AUTONOMOUS_TICK, "schedule", "rt012", NOW
        )
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry={})
        loop.session_context = _session()
        loop.act_outcome = _action_outcome()

        feedback = await loop.update()

        assert isinstance(feedback, Feedback)
        assert loop.feedback is feedback
        assert any(item.target == TARGET_MEMORY for item in feedback.items)
