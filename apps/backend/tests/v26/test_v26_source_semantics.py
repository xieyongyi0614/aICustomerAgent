"""V2.6.1 REF-002 T7：source=plan 的关系信号与自治日额度口径。"""

import asyncio
from datetime import datetime, timedelta

from app.application import world_engine
from app.application.autonomy_engine import _autonomy_action_today
from app.character.asuna.action import ACTION_RELATIONSHIP_MAP
from app.models.action import ActionIntent
from app.repositories import action_repository
from app.repositories import relationship_event_repository
from app.services.action import manager, relationship_bridge


def _due_at(hours: int = 2) -> str:
    return (datetime.now() + timedelta(hours=hours)).isoformat()


class TestRelationshipMapCoverage:
    def test_plan_rows_match_autonomy_success_rows(self):
        autonomy_types = {
            action_type
            for (action_type, source, status) in ACTION_RELATIONSHIP_MAP
            if source == "autonomy" and status == "succeeded"
        }
        plan_types = {
            action_type
            for (action_type, source, status) in ACTION_RELATIONSHIP_MAP
            if source == "plan" and status == "succeeded"
        }
        assert autonomy_types, "autonomy 成功行必须存在"
        assert autonomy_types.issubset(plan_types), "plan 成功行必须覆盖 autonomy 成功行"
        assert ACTION_RELATIONSHIP_MAP[
            ("create_reminder", "plan", "succeeded")
        ] == ("user_care", "weak")
        assert ACTION_RELATIONSHIP_MAP[("create_reminder", "conversation", "succeeded")] == (
            "user_help",
            "normal",
        )

    def test_lookup_signal_plan_succeeded(self):
        from app.models.action import ActionRecord

        record = ActionRecord(
            id="act_src1",
            user_id="u_t7",
            action_type="create_reminder",
            source="plan",
            status="succeeded",
            params={"content": "x", "due_at": _due_at()},
        )
        assert relationship_bridge.lookup_signal(record) == ("user_care", "weak")

    def test_lookup_signal_plan_failed_none(self):
        from app.models.action import ActionRecord

        record = ActionRecord(
            id="act_src2",
            user_id="u_t7",
            action_type="create_reminder",
            source="plan",
            status="failed",
            params={"content": "x", "due_at": _due_at()},
        )
        assert relationship_bridge.lookup_signal(record) is None


class TestAutonomyQuotaCountsPlan:
    def test_plan_source_counts_toward_daily_limit(self, override_settings):
        override_settings(world_enabled=True)
        now = datetime.now()
        user_id = "u_t7_quota"
        world_engine.ensure_world(user_id)
        action = manager.create(
            user_id=user_id,
            action_type="create_reminder",
            params={"content": "额度", "due_at": _due_at()},
            source="plan",
        )
        asyncio.run(manager.execute(action.id))
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.source == "plan"
        assert loaded.status == "succeeded"
        count = _autonomy_action_today(user_id, now)
        assert count >= 1

    def test_conversation_source_not_counted(self, override_settings):
        override_settings(world_enabled=True)
        now = datetime.now()
        user_id = "u_t7_conv"
        world_engine.ensure_world(user_id)
        action = manager.create(
            user_id=user_id,
            action_type="create_reminder",
            params={"content": "对话额度", "due_at": _due_at()},
            source="conversation",
        )
        asyncio.run(manager.execute(action.id))
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.source == "conversation"
        count = _autonomy_action_today(user_id, now)
        assert count == 0


class TestPlanBridgeSourceAndDelivery:
    def test_bridge_dispatch_plan_source_and_relationship_event(self, override_settings):
        override_settings(
            action_relationship_enabled=True,
            world_enabled=True,
        )
        from app.services.planning.executor_bridge import PlanExecutorBridge

        user_id = "u_t7_bridge"
        world_engine.ensure_world(user_id)
        bridge = PlanExecutorBridge()

        class Goal:
            id = "g_t7"
            user_id = "u_t7_bridge"

        intent = ActionIntent(
            action_type="create_reminder",
            confidence="confident",
            params={"content": "桥提醒", "due_at": _due_at()},
            dedupe_key="t7bridge00000001",
        )
        record = asyncio.run(bridge._dispatch(Goal(), intent))
        assert record is not None
        assert record.source == "plan"
        assert record.status == "succeeded"

        events = relationship_event_repository.list_events(user_id, limit=50)
        action_events = [
            e
            for e in events
            if e.type == "user_care" and e.cause.startswith("行动 create_reminder")
        ]
        assert action_events, "plan 成功必须投递 user_care 关系信号"

        assert _autonomy_action_today(user_id, datetime.now()) >= 1
