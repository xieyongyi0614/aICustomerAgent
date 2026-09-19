"""V2.6.1 REF-103/104：状态机权威与计划↔行动溯源。"""

import asyncio

from app.application import action_engine, world_engine
from app.core.settings import get_settings
from app.models.action import ActionResult
from app.repositories import action_repository
from app.services.action import manager


class TestStateMachineAuthority:
    def test_recovery_uses_transition_action(self):
        source = open(action_engine.__file__, encoding="utf-8").read()
        assert 'transition_action("executing", "step_permanent_failed")' in source
        assert "_recover_stale_executing" in source

    def test_partial_mapping_not_stuck_executing(self, monkeypatch):
        from app.models.action import ActionIntent

        s = get_settings()
        monkeypatch.setattr(s, "action_retry_max_attempts", 2)
        record = action_repository.save_record(
            action_engine.new_record(
                ActionIntent(
                    action_type="remember_fact",
                    confidence="confident",
                    params={"fact": "sm"},
                    dedupe_key="sm_partial_1",
                ),
                "u_sm_auth",
                None,
            )
        )
        record.status = "executing"
        action_engine._apply_action_result_to_record(
            record, ActionResult(status="partial", failure_kind="transient"), s
        )
        assert record.status == "failed"


class TestPlanStepTraceability:
    def test_create_from_plan_intent_fills_plan_step(self):
        from app.models.action import ActionIntent

        intent = ActionIntent(
            action_type="remember_fact",
            confidence="confident",
            params={"fact": "溯源事实"},
            dedupe_key="trace_step_1",
        )
        action = manager.create(
            user_id="u_trace",
            action_type="remember_fact",
            params=dict(intent.params),
            source="plan",
            intent=intent,
            plan_step="step_1",
            goal_id="g_trace",
        )
        assert action.plan_step == "step_1"
        assert action.source == "plan"
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert (loaded.intent or {}).get("plan_step") == "step_1"

    def test_bridge_flag_on_fills_plan_step(self, monkeypatch):
        from app.models.action import ActionIntent
        from app.services.planning.executor_bridge import PlanExecutorBridge

        settings = get_settings()
        monkeypatch.setattr(settings, "action_enabled", True)
        monkeypatch.setattr(settings, "world_enabled", True)
        world_engine.ensure_world("u_bridge_trace")
        bridge = PlanExecutorBridge()

        class Goal:
            id = "g_bridge_trace"
            user_id = "u_bridge_trace"

        intent = ActionIntent(
            action_type="remember_fact",
            confidence="confident",
            params={"fact": "桥溯源"},
            dedupe_key="bridge_trace_0001",
        )
        record = asyncio.run(
            bridge._dispatch(Goal(), intent, plan_step="step_2")
        )
        assert record is not None
        assert record.source == "plan"
        assert (record.intent or {}).get("plan_step") == "step_2"

    def test_run_id_independent_column(self, monkeypatch):
        from app.models.action import ActionIntent

        s = get_settings()
        monkeypatch.setattr(s, "action_enabled", True)
        record = action_engine.new_record(
            ActionIntent(
                action_type="remember_fact",
                confidence="confident",
                params={"fact": "run"},
                dedupe_key="run_id_col_1",
            ),
            "u_runid",
            "sess_abc",
            run_id="run_loop_1",
        )
        saved = action_repository.save_record(record)
        loaded = action_repository.get_record(saved.id)
        assert loaded is not None
        assert loaded.run_id == "run_loop_1"
        assert loaded.session_id == "sess_abc"
        action = manager.create(
            user_id="u_runid2",
            action_type="remember_fact",
            params={"fact": "run2"},
            session_id="sess_x",
        )
        # create 未显式传 run_id 时回退 session_id（兼容窗口）
        assert action.run_id == "sess_x"