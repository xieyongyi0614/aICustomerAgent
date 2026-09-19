"""PLAN-007 Step 5：额度与冷却**未放宽**的四条负例（评审红线）。

覆盖 Task Detail §9.2 I8、§9.3 S5 与 §4.2.4 表。

判定要点（额度与冷却的权威点各自不动，本任务只做接线）：

| 关注 | 权威点 | 本任务 |
|---|---|---|
| `action_max_active_per_user` | `services/action/planner.evaluate_gates`（六闸门 `quota_exceeded`） | 未触碰：达上限仍拒绝 |
| `autonomy_action_daily_limit` | `autonomy_engine._produce_autonomy_action`（自治产行动分支） | 未触碰：达上限仍不产行动 |
| `autonomy_min_interval_minutes` | `autonomy_policy.effective_interval_minutes` / `_cooldown_passed` | 未触碰：间隔未到仍 `wait` |
| 步骤冷却窗口 | `PlanScheduler.blocked_reason`（`cooldown`） | 未触碰：窗口内仍不可调度 |

**与 §8 Step 5.1 的一处实现核对（已在测试留痕）**：§8 记「达上限 → 计划步骤不执行、
**不产生 `ActionRecord`**」，而既有 Action 引擎在六闸门拒绝时**必然持久化一条终态
`cancelled` 拒绝记录**（fail-closed 审计，V9 既有行为，本任务不得改动）。故负例的判定口径
取「不执行（零工具调用 / 零 `steps` 结果）+ 不占额度（活跃计数不增）+ 不产生成功记录」，
而非字面的「零记录」——后者会把既有闸门审计语义误判成回归。
"""

from datetime import timedelta

import pytest

from app.application import autonomy_engine
from app.core.settings import get_settings
from app.models.action import ActionRecord
from app.repositories import action_repository
from app.services import autonomy_policy
from app.services.planning.executor_bridge import PlanExecutorBridge

from . import plan007_support as support

USER = support.USER
NOW = support.NOW
BRIDGE = PlanExecutorBridge()

ACTIVE_STATUSES = ("created", "planned", "executing")

WORLD_FREE_ACTION = support.OTHER_ACTION
"""`send_notification` 不在 `WORLD_DEPENDENT_ACTIONS` 内：世界关闭时 G3 仍通过。

额度负例必须让**额度闸门成为第一个拒绝点**——若用 `create_reminder`，`world_enabled=false`
会让 G3 抢先返回 `capability_unavailable`，断言就退化成「路径不通」而非「额度生效」。
"""


def _seed_active_records(count: int, *, user_id: str = USER, status: str = "planned"):
    for index in range(count):
        action_repository.save_record(
            ActionRecord(
                id=f"plan7-active-{index}",
                user_id=user_id,
                session_id=support.SESSION_ID,
                source="autonomy",
                action_type=support.REMINDER_ACTION,
                dedupe_key=f"seed:{index}",
                status=status,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _active_count(user_id: str = USER) -> int:
    return sum(
        1
        for record in action_repository.list_records(user_id, limit=200)
        if record.status in ACTIVE_STATUSES
    )


def _ready_plan():
    """计划当前步与自治动作同源（`create_reminder`）之外，另备世界无关动作的步骤。"""
    return support.plan([support.spec(1)])


def _world_free_plan():
    """世界无关动作的单步计划（额度负例专用：G3 不拦，额度闸门是首个拒绝点）。"""
    return support.plan([support.spec(1, capability=WORLD_FREE_ACTION)])


@pytest.fixture
def action_on(override_settings):
    override_settings(action_enabled="true", world_enabled="false")
    return True


class TestActiveActionQuotaIsNotRelaxed:
    """I8 ①：`action_max_active_per_user` 达上限 → 计划步骤不执行、不占额度。"""

    def test_the_limit_itself_is_unchanged(self):
        assert get_settings().action_max_active_per_user == 5

    @pytest.mark.asyncio
    async def test_a_plan_step_is_refused_at_the_active_limit(
        self, action_on, db_session_factory
    ):
        limit = get_settings().action_max_active_per_user
        _seed_active_records(limit)
        before = _active_count()
        assert before == limit
        plan = _world_free_plan()

        outcome = await BRIDGE.execute_step(
            support.seed_layered_goal(USER),
            plan,
            plan.sub_goals[0],
            support.bridge_ctx(NOW),
        )

        assert outcome.status == "hold"
        assert outcome.failure_kind is None
        assert outcome.effects == []
        assert _active_count() == before, "计划不得成为绕过活跃额度的后门"

    @pytest.mark.asyncio
    async def test_the_rejection_is_a_gate_record_without_any_tool_step(
        self, action_on, db_session_factory
    ):
        _seed_active_records(get_settings().action_max_active_per_user)
        plan = _world_free_plan()
        await BRIDGE.execute_step(
            support.seed_layered_goal(USER),
            plan,
            plan.sub_goals[0],
            support.bridge_ctx(NOW),
        )
        rejected = [
            record
            for record in action_repository.list_records(USER, limit=10)
            if record.status == "cancelled"
        ]
        assert len(rejected) == 1
        assert rejected[0].gate_reason == "quota_exceeded"
        assert rejected[0].steps == [], "闸门拒绝在工具装配之前：零工具调用"

    @pytest.mark.asyncio
    async def test_the_step_is_not_advanced_by_the_rejection(
        self, action_on, db_session_factory
    ):
        _seed_active_records(get_settings().action_max_active_per_user)
        plan = _world_free_plan()
        step = plan.sub_goals[0]
        outcome = await BRIDGE.execute_step(
            support.seed_layered_goal(USER), plan, step, support.bridge_ctx(NOW)
        )
        reconciled = BRIDGE.reconcile(outcome, step, max_attempts=2)
        assert reconciled.status == "in_progress"
        assert reconciled.attempt_count == 0
        assert reconciled.failure_note is None

    def test_the_quota_gate_is_the_only_rejection(self, action_on, db_session_factory):
        """负例的对照面：额度未满时同一动作通过闸门（负例不是「路径根本不通」）。"""
        from app.application import action_engine
        from app.services.action.planner import evaluate_gates

        plan = _world_free_plan()
        goal = support.seed_layered_goal(USER)
        intent = BRIDGE.to_intent(goal, plan, plan.sub_goals[0], support.bridge_ctx(NOW))

        below = evaluate_gates(intent, action_engine._build_snapshot(USER, get_settings()))
        assert below.allowed is True

        _seed_active_records(get_settings().action_max_active_per_user)
        above = evaluate_gates(intent, action_engine._build_snapshot(USER, get_settings()))
        assert above.allowed is False
        assert above.reason == "quota_exceeded"


class TestDailyLimitIsNotRelaxed:
    """I8 ②：`autonomy_action_daily_limit` 达上限 → 自治产行动分支不产行动。"""

    def test_the_limit_itself_is_unchanged(self):
        assert get_settings().autonomy_action_daily_limit == 1
        assert get_settings().autonomy_action_enabled is False

    @staticmethod
    def _verdict():
        return autonomy_policy.AutonomyVerdict(
            decision="act",
            reason="触发 conversation_inactivity，存在 user_care 目标",
            trigger=support.signal(),
            goal_id=support.GOAL_ID,
            intention=support.CHECK_IN_INTENTION,
        )

    @staticmethod
    async def _produce(monkeypatch, *, limit: int, seeded: int):
        calls: list = []

        async def _runner(user_id, intent, session_id=None, goal_id=None, source=None):
            calls.append({"user_id": user_id, "intent": intent, "source": source})
            return ActionRecord(
                id="plan7-daily-1",
                user_id=user_id,
                session_id=session_id,
                source=source,
                action_type=intent.action_type,
                dedupe_key=intent.dedupe_key,
                status="succeeded",
                created_at=NOW,
                updated_at=NOW,
            )

        monkeypatch.setattr(autonomy_engine, "run_action_planning", _runner)
        _seed_autonomy_records(seeded)
        produced = await autonomy_engine._produce_autonomy_action(
            TestDailyLimitIsNotRelaxed._verdict(), USER, support.SESSION_ID, NOW
        )
        return produced, calls

    @pytest.mark.asyncio
    async def test_the_daily_limit_still_stops_the_autonomy_branch(
        self, monkeypatch, db_session_factory, override_settings
    ):
        override_settings(autonomy_action_enabled="true", autonomy_action_daily_limit=1)
        produced, calls = await self._produce(monkeypatch, limit=1, seeded=1)
        assert produced is False
        assert calls == [], "日额度已满时不得触达执行入口"

    @pytest.mark.asyncio
    async def test_below_the_daily_limit_the_branch_still_produces(
        self, monkeypatch, db_session_factory, override_settings
    ):
        override_settings(autonomy_action_enabled="true", autonomy_action_daily_limit=2)
        produced, calls = await self._produce(monkeypatch, limit=2, seeded=1)
        assert produced is True
        assert len(calls) == 1
        assert calls[0]["source"] == autonomy_engine.AUTONOMY_SOURCE

    @pytest.mark.asyncio
    async def test_an_advancing_plan_does_not_relax_the_daily_limit(
        self, monkeypatch, db_session_factory, override_settings
    ):
        """计划事实不是豁免凭证：产行动分支**零计划感知**（不读 `plan_facts`、不读计划库）。"""
        override_settings(autonomy_action_enabled="true", autonomy_action_daily_limit=1)
        produced, calls = await self._produce(monkeypatch, limit=1, seeded=1)
        assert produced is False and calls == []

        from pathlib import Path

        source = Path(autonomy_engine.__file__).read_text(encoding="utf-8")
        branch = source.split("async def _produce_autonomy_action", 1)[1].split(
            "\ndef _session_tail", 1
        )[0]
        assert "plan_facts" not in branch
        assert "plan_scheduler" not in branch
        assert "list_active_plans" not in branch


def _seed_autonomy_records(count: int, *, user_id: str = USER):
    for index in range(count):
        action_repository.save_record(
            ActionRecord(
                id=f"plan7-daily-{index}",
                user_id=user_id,
                session_id=support.SESSION_ID,
                source="autonomy",
                action_type=support.REMINDER_ACTION,
                dedupe_key=f"autonomy:seed:{index}",
                status="cancelled",
                created_at=NOW,
                updated_at=NOW,
            )
        )


class TestIntervalAndCooldownAreNotRelaxed:
    """I8 ③ / ④：最小间隔与步骤冷却窗口原样生效，`plan_facts` 不放宽任何一项。"""

    def test_the_interval_settings_are_unchanged(self):
        settings = get_settings()
        assert settings.autonomy_min_interval_minutes == 240
        assert settings.autonomy_min_interval_floor_minutes == 60
        assert settings.autonomy_backoff_multiplier == 2.0
        assert settings.autonomy_max_attempts_per_episode == 2

    def test_the_effective_interval_math_is_unchanged(self):
        settings = get_settings()
        cases = (
            (support.act_snapshot(), 120.0),
            (support.act_snapshot(intimacy=0.4), 240.0),
            (support.act_snapshot(comfort=0.2), 180.0),
            (support.act_snapshot(attempt_count=3), 480.0),
            (support.act_snapshot(attempt_count=10), 120.0 * 2**9),
        )
        observed = tuple(
            autonomy_policy.effective_interval_minutes(snapshot, settings)
            for snapshot, _expected in cases
        )
        assert observed == tuple(expected for _snapshot, expected in cases)

    def test_an_unmet_interval_still_waits_with_a_plan_in_flight(self):
        snapshot = support.barrier_snapshot(
            last_proactive_at=NOW.replace(hour=11, minute=30)
        )
        verdict = autonomy_policy.evaluate(
            support.signal(), snapshot, get_settings(), NOW
        )
        assert verdict.decision == "wait"
        assert verdict.reason == "冷却中"

    def test_the_plan_packet_never_turns_wait_into_act(self):
        for minutes_ago in (1, 30, 120, 239):
            snapshot = support.barrier_snapshot(
                last_proactive_at=NOW - timedelta(minutes=minutes_ago)
            )
            verdict = autonomy_policy.evaluate(
                support.signal(), snapshot, get_settings(), NOW
            )
            assert verdict.decision == "wait", minutes_ago

    def test_the_step_cooldown_window_is_unchanged(self):
        assert get_settings().plan_step_cooldown_minutes == 30

    def test_a_step_inside_the_cooldown_window_is_not_schedulable(self):
        step = support.spec(1, last_attempt_at=NOW - timedelta(minutes=5))
        plan = support.plan([step])
        reason = autonomy_engine.plan_scheduler.PlanScheduler.blocked_reason(
            plan, autonomy_engine._plan_schedule_context(USER, NOW)
        )
        assert reason == autonomy_engine.plan_scheduler.BLOCKED_COOLDOWN

    def test_the_packet_reports_the_block_without_relaxing_it(
        self, override_settings, db_session_factory
    ):
        override_settings(world_enabled="false")
        goal = support.seed_layered_goal(USER)
        support.seed_plan(
            goal.id, [support.spec(1, last_attempt_at=NOW - timedelta(minutes=5))]
        )
        facts = autonomy_engine._collect_plan_facts(USER, NOW)
        assert facts["blocked_steps"] == 1
        assert facts["current_step"] == 1, "阻塞只上报表述，不改计划状态"

    def test_blocked_steps_never_loosens_the_verdict(self):
        blocked = autonomy_policy.evaluate(
            support.signal(),
            support.barrier_snapshot({'blocked_steps': 1}),
            get_settings(),
            NOW,
        )
        unblocked = autonomy_policy.evaluate(
            support.signal(),
            support.barrier_snapshot({'blocked_steps': 0}),
            get_settings(),
            NOW,
        )
        assert blocked.model_dump() == unblocked.model_dump()
        assert blocked.decision == "wait"
