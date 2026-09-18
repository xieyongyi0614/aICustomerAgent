"""PLAN-008 Step 2 / Step 6：正向三条合法路径与关系域通道（U6 / U7 / I4 / I5 / I7、S2~S4）。

覆盖 Task Detail §9.1 U6 / U7、§9.2 I4 / I5 / I7、§9.3 S2 / S3 / S4；对应 §8 Step 2 与 Step 6。

三条合法路径（§4.2.2）

| # | 形态 | 本用例的驱动方式 |
|---|---|---|
| ① | 只读世界 | 计划步骤绑 `world.env.query`（能力 `environment_query`，零 `deferred_world_op`） |
| ② | 延迟写世界 | 计划步骤绑 `builtin.reminder.create`（`deferred_world_op={op:"create_event"}` → outbox） |
| ③ | 提交世界意图 | 不接线（`WIRED=False`，见 `test_plan008_intent.py`） |

**「白名单外无调用路径」的可判定形态**（§4.2.3 边界纪律，按真实源码留痕）

消费器 `outbox_consumer._apply_world_op` 的分派是 `hasattr(world_engine, op_name)`（V2.0 既有实现，
本任务零改动），故「非白名单 op」存在两种可判定形态，本模块各断言一条：

1. **产出面封闭**（强断言）：全仓 `deferred_world_op` 的 op 字面量产出点面（`WORLD_OP_LITERAL_PRODUCERS`）
   的字面量集合 ⊆ 七 op 白名单；计划层零 op 字面量（它只透传工具的产物）。故**不存在**产出非白名单
   op 的代码路径。
2. **名字不可解析即被拒**（负例）：op 名落在 `world_engine` 之外 → `RuntimeError` → 既有重试/死信，
   零世界副作用（V2.4.0 既有纪律，本任务复述为 PLAN-008 的边界用例）。

关系域通道（Step 6 / Q9）：计划步骤触达关系域的**唯一**通道是既有
`outbox_consumer._apply_outbox_row` 的关系段（`relationship_bridge.deliver_action_signal`），
其判定输入是行动记录 + 角色资产映射表（`ACTION_RELATIONSHIP_MAP`），**不是** `ToolEffect` 的
`kind="relationship"` 本身——§6.4 E4 的字面表述（「关系变化必有对应 `ToolEffect`」）与真实源码
不符，本模块按源码语义断言：关系变化必有**行动记录**且只经既有 bridge 通道、且在 outbox 消费之后
（计划层零直写，静态断言见 `test_plan008_static_scan.py`）。
"""

from datetime import datetime, timedelta

import pytest

from app.application import outbox_consumer, world_engine
from app.models.action import ActionRecord
from app.models.plan import PlanContext
from app.repositories import (
    outbox_repository,
    relationship_event_repository,
    world_repository,
)
from app.services.action import relationship_bridge
from app.services.planning import context as plan_context
from app.services.planning.executor_bridge import PlanExecutorBridge
from app.services.tool.registry import get_tool_registry
from tests.v24.tool007_support import seed_all, seed_world, world_event_titles

from . import plan008_support as support
from .plan008_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    planning_world_on,
)

USER = support.USER
ENV_QUERY = support.ENV_QUERY
REMINDER_CREATE = support.REMINDER_CREATE

REMINDER_DUE_AT = "2027-01-01T09:00:00"

WHITELIST_REJECTED_OP = "explode_world"

RELATIONSHIP_SESSION = "plan8-relationship-session"


@pytest.fixture
def forward_on(planning_world_on, override_settings):
    """正向路径开关面：在装配面之上开「行动总闸 + outbox + 生命周期」（outbox 依赖 life_loop）。"""
    override_settings(
        action_outbox_enabled="true",
        world_household_autoseed_enabled="false")
    return True


def _bridge(**kwargs) -> PlanExecutorBridge:
    kwargs.setdefault("registry", get_tool_registry())
    kwargs.setdefault("session_resolver", lambda _user_id: None)
    return PlanExecutorBridge(**kwargs)


async def _run_step(
    *, tool_id: str, capability: str, params: dict, index: int = 1, session_id: str | None = None
):
    goal = support.goal(user_id=USER)
    plan = support.plan([support.step(index, capability=capability, tool_id=tool_id, params=params)])
    bridge = _bridge() if session_id is None else _bridge(session_resolver=lambda _id: session_id)
    outcome = await bridge.execute_step(
        goal, plan, plan.sub_goals[0], support.surface_context(tool_id)
    )
    return goal, plan, outcome


WORLD_TABLE_PREFIX = "world"


def _world_tables(counts: dict[str, int]) -> dict[str, int]:
    """世界四表的计数投影（世界侧零变更的可判定面：行动台账与 outbox 行不计入）。"""
    return {
        name: value
        for name, value in counts.items()
        if name == WORLD_TABLE_PREFIX or name.startswith(WORLD_TABLE_PREFIX + "_")
    }


def _world_write_callers(monkeypatch) -> list[tuple[str, str]]:
    """记录世界写函数的调用方模块（唯一写路径的举证形态，与 V2.4.0 TOOL-007 同款）。"""
    import inspect

    calls: list[tuple[str, str]] = []
    for name in ("create_event", "create_object", "move_object", "apply_object_action"):
        original = getattr(world_engine, name)

        def wrapper(*args, _name: str = name, _original=original, **kwargs):
            caller = next(
                frame.frame.f_globals.get("__name__", "")
                for frame in inspect.stack()
                if frame.frame.f_globals.get("__name__", "") != __name__
            )
            calls.append((_name, caller))
            return _original(*args, **kwargs)

        monkeypatch.setattr(world_engine, name, wrapper)
    return calls


class TestWorldOpWhitelist:
    """§4.2.3：白名单七 op 即合法写面；白名单外无产出路径，未知 op 被既有消费器拒绝。"""

    def test_seven_whitelisted_ops_are_the_world_engine_write_face(self):
        missing = [op for op in support.WORLD_OP_WHITELIST if not hasattr(world_engine, op)]
        assert missing == []
        assert all(
            op not in plan_context.WORLD_READ_ENTRIES for op in support.WORLD_OP_WHITELIST
        )
        assert set(support.WORLD_OP_WHITELIST) <= set(support.WORLD_WRITE_FACE)

    def test_producers_only_emit_whitelisted_ops(self):
        produced = support.produced_op_literals()
        assert produced == {
            "reminder.py": {"create_event", "cancel_events_by_type"},
            "world_action.py": {"create_object", "move_object", "apply_object_action"},
            "event_bridge.py": {"create_event"},
        }
        flat = {op for ops in produced.values() for op in ops}
        assert flat <= set(support.WORLD_OP_WHITELIST)

    def test_planning_package_holds_no_world_op_literal(self):
        """计划层只**透传**工具产出的 op：包内零 op 字面量（§4.2.3 边界纪律）。"""
        offenders = {
            path.name: sorted(support.op_literals(path) & set(support.WORLD_OP_WHITELIST))
            for path in support.planning_modules()
        }
        assert {name: ops for name, ops in offenders.items() if ops} == {}

    def test_unknown_op_is_rejected_by_the_existing_consumer(
        self, db_session_factory, forward_on, override_settings
    ):
        """负例：名字落在 `world_engine` 之外 → 重试（零世界副作用）。"""
        override_settings(life_loop_outbox_max_attempts="3")
        seed_world(USER)
        key = "plan8-neg-op"
        outbox_repository.insert(
            {
                "action_id": key,
                "user_id": USER,
                "record": _record_payload(key),
                "world_ops": [{"op": WHITELIST_REJECTED_OP, "args": [USER]}],
            },
            idempotency_key=key,
            now=support.NOW,
        )
        stats = outbox_consumer.consume_pending(now=support.NOW)
        assert stats["retried"] == 1 and stats["dead_lettered"] == 0
        row = outbox_repository.get(key)
        assert row.status == "pending" and row.attempts == 1
        assert "未知 world op" in (row.last_error or "")
        assert world_event_titles(USER) == []

    def test_whitelist_boundary_is_hasattr_dispatch_not_a_new_gate(self):
        """留痕：消费器分派面未被本任务改动（白名单靠**产出面封闭**，不新增闸门）。"""
        import inspect

        source = inspect.getsource(outbox_consumer._apply_world_op)
        assert "hasattr(world_engine, op_name)" in source
        assert len(support.WORLD_OP_WHITELIST) == 7


class TestReadOnlyWorldPath:
    """S2 / ① 只读世界：查天气步骤零 `deferred_world_op`、零世界表变更、零 outbox 行。"""

    @pytest.mark.asyncio
    async def test_env_query_step_writes_nothing(self, db_session_factory, forward_on):
        """只读步的判定面是 `world_ops` 为空（outbox 行仍存在——它承载关系段所需的行动记录）。"""
        seed_world(USER)
        before = support.table_counts(db_session_factory)
        goal, _plan, outcome = await _run_step(
            tool_id=ENV_QUERY, capability="query_environment", params={"dimension": "weather"}
        )
        assert outcome.status == "succeeded"
        assert outcome.tool_id == ENV_QUERY
        assert outcome.effects == []
        record = outbox_repository.get(outcome.action_id)
        assert record is not None
        assert record.payload["world_ops"] == []
        outbox_consumer.consume_pending(now=datetime.now())
        assert world_repository.list_events(
            world_repository.world_id_for(USER), limit=10
        ) == []
        after = support.table_counts(db_session_factory)
        assert _world_tables(after) == _world_tables(before)
        assert goal.id == support.GOAL_ID


class TestDeferredWorldWritePath:
    """S3 / S4 / U7 / I4 / I5：延迟写世界——唯一写面在 outbox 消费之后。"""

    @pytest.mark.asyncio
    async def test_s3_reminder_step_defers_then_lands_through_the_consumer(
        self, db_session_factory, forward_on, monkeypatch
    ):
        seed_world(USER)
        callers = _world_write_callers(monkeypatch)
        _goal, _plan, outcome = await _run_step(
            tool_id=REMINDER_CREATE,
            capability="create_reminder",
            params={"content": "复查", "due_at": REMINDER_DUE_AT},
        )
        assert outcome.status == "succeeded"
        assert outcome.tool_id == REMINDER_CREATE
        record = outbox_repository.get(outcome.action_id)
        assert record is not None
        assert [op["op"] for op in record.payload["world_ops"]] == ["create_event"]
        assert record.payload["world_ops"][0]["args"][0] == USER
        assert world_event_titles(USER) == []
        assert callers == []

        stats = outbox_consumer.consume_pending(now=datetime.now())
        assert stats["consumed"] == 1
        assert world_event_titles(USER) == ["复查"]
        assert [caller for _, caller in callers] == ["app.application.outbox_consumer"]
        assert outbox_repository.get(outcome.action_id).status == "consumed"

    @pytest.mark.asyncio
    async def test_i4_world_change_always_has_a_preceding_outbox_row(
        self, db_session_factory, forward_on
    ):
        seed_world(USER)
        before = support.table_counts(db_session_factory)
        _goal, _plan, outcome = await _run_step(
            tool_id=REMINDER_CREATE,
            capability="create_reminder",
            params={"content": "复查", "due_at": REMINDER_DUE_AT},
        )
        after_execute = support.table_counts(db_session_factory)
        assert _world_tables(after_execute) == _world_tables(before)
        row = outbox_repository.get(outcome.action_id)
        assert row is not None and row.status == "pending"
        assert row.idempotency_key == outcome.action_id

        outbox_consumer.consume_pending(now=datetime.now())
        after_consume = support.table_counts(db_session_factory)
        assert after_consume["world_events"] == before["world_events"] + 1

    @pytest.mark.asyncio
    async def test_u7_repeated_consume_does_not_duplicate_world_side_effect(
        self, db_session_factory, forward_on
    ):
        seed_world(USER)
        _goal, _plan, outcome = await _run_step(
            tool_id=REMINDER_CREATE,
            capability="create_reminder",
            params={"content": "复查", "due_at": REMINDER_DUE_AT},
        )
        outbox_consumer.consume_pending(now=datetime.now())
        assert world_event_titles(USER) == ["复查"]
        assert outbox_consumer.consume_pending(now=datetime.now())["consumed"] == 0
        assert world_event_titles(USER) == ["复查"]

    @pytest.mark.asyncio
    async def test_i5_crash_replay_resumes_without_a_second_side_effect(
        self, db_session_factory, forward_on
    ):
        """崩溃重放续走：行被重置为 pending 后重放不产生第二条世界事件（幂等键 = record.id）。"""
        from app.core.db import OutboxEventRow

        seed_world(USER)
        _goal, _plan, outcome = await _run_step(
            tool_id=REMINDER_CREATE,
            capability="create_reminder",
            params={"content": "复查", "due_at": REMINDER_DUE_AT},
        )
        outbox_consumer.consume_pending(now=datetime.now())
        assert world_event_titles(USER) == ["复查"]

        with outbox_repository.SessionLocal() as session:
            session.query(OutboxEventRow).filter(
                OutboxEventRow.idempotency_key == outcome.action_id
            ).update({"status": "pending", "attempts": 0})
            session.commit()
        stats = outbox_consumer.consume_pending(now=datetime.now())
        assert stats["consumed"] == 1
        assert world_event_titles(USER) == ["复查"]

    def test_idempotency_key_is_the_action_record_id(self):
        """D10：幂等键 = `ActionRecord.id`（机制未改）。"""
        import inspect

        signature = inspect.signature(outbox_consumer._apply_world_op)
        assert list(signature.parameters) == ["action_id", "op"]
        from app.application import action_engine

        assert "idempotency_key=record.id" in inspect.getsource(
            action_engine._integrate_via_outbox
        )

    @pytest.mark.asyncio
    async def test_s4_a_repeated_step_produces_no_second_world_side_effect(
        self, db_session_factory, forward_on
    ):
        """S4（G-RETRY 世界侧）：同一步骤重复执行不产生第二个 `deferred_world_op`。"""
        seed_world(USER)
        first = await _run_step(
            tool_id=REMINDER_CREATE,
            capability="create_reminder",
            params={"content": "复查", "due_at": REMINDER_DUE_AT},
        )
        second = await _run_step(
            tool_id=REMINDER_CREATE,
            capability="create_reminder",
            params={"content": "复查", "due_at": REMINDER_DUE_AT},
        )
        assert first[2].action_id != second[2].action_id
        second_record = outbox_repository.get(second[2].action_id)
        if second_record is not None:
            assert second_record.payload["world_ops"] == []
        assert outbox_consumer.consume_pending(now=datetime.now())["consumed"] == 1
        assert world_event_titles(USER) == ["复查"]

    @pytest.mark.asyncio
    async def test_s4_replanning_keeps_the_dedupe_key_versioned(
        self, db_session_factory, forward_on
    ):
        """S4 补充：步级幂等键含计划版本（重规划换版本 → 键变，保留步不重做由 PLAN-005 断言）。"""
        from app.models.plan import PLAN_STEP_DEDUPE_KEY_TEMPLATE

        goal = support.goal(user_id=USER)
        plan = support.plan(
            [
                support.step(
                    1,
                    capability="create_reminder",
                    tool_id=REMINDER_CREATE,
                    params={"content": "复查", "due_at": REMINDER_DUE_AT},
                )
            ]
        )
        intent = _bridge().to_intent(goal, plan, plan.sub_goals[0], support.surface_context())
        assert intent.dedupe_key == PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(
            goal_id=goal.id, version=plan.version, index=1
        )


class TestRelationshipChannel:
    """I7 / Step 6（Q9）：关系域变化只经既有 bridge 通道，且发生在 outbox 消费之后。"""

    @pytest.mark.asyncio
    async def test_relationship_change_happens_only_after_consume(
        self, db_session_factory, forward_on, override_settings
    ):
        override_settings(action_relationship_enabled="true")
        seed_world(USER)
        _goal, _plan, outcome = await _run_step(
            tool_id=REMINDER_CREATE,
            capability="create_reminder",
            params={"content": "复查", "due_at": REMINDER_DUE_AT},
            session_id=RELATIONSHIP_SESSION,
        )
        assert outcome.status == "succeeded"
        assert relationship_event_repository.count_events(USER) == 0

        outbox_consumer.consume_pending(now=datetime.now())
        events = relationship_event_repository.list_events(USER, limit=10)
        assert [event.type for event in events] == ["user_care"]
        assert events[0].cause.startswith("行动 create_reminder")

    @pytest.mark.asyncio
    async def test_relationship_change_requires_an_action_record(
        self, db_session_factory, forward_on, override_settings
    ):
        """E4 的源码语义形态：关系变化的充分输入是**行动记录 + 角色资产映射表**。"""
        override_settings(action_relationship_enabled="true")
        record = ActionRecord(
            id="plan8-rel-ghost",
            user_id=USER,
            action_type="create_reminder",
            source="autonomy",
            status="succeeded",
            created_at=support.NOW,
            updated_at=support.NOW,
        )
        assert relationship_bridge.lookup_signal(record) == ("user_care", "weak")
        failed = record.model_copy(update={"status": "failed"})
        assert relationship_bridge.lookup_signal(failed) is None
        assert relationship_event_repository.count_events(USER) == 0


class TestOutboxConsumerFace:
    """§10.2：`outbox_consumer` / `save_record_with_outbox` 的消费语义未改（形状快照）。"""

    def test_consume_entry_points_are_unchanged(self):
        import inspect

        assert list(inspect.signature(outbox_consumer.consume_pending).parameters) == [
            "limit",
            "now",
        ]
        assert list(inspect.signature(outbox_consumer._apply_outbox_row).parameters) == ["row"]
        from app.repositories import action_repository

        assert list(
            inspect.signature(action_repository.save_record_with_outbox).parameters
        ) == ["record", "outbox_payload", "idempotency_key"]

    def test_relationship_bridge_importers_are_the_two_existing_paths(self):
        """关系域写入面零扩张：全仓只有既有两处导入 `relationship_bridge`。"""
        import ast
        from pathlib import Path

        root = support.repo_root() / "app"
        importers = set()
        for path in Path(root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and any(
                    alias.name == "relationship_bridge" for alias in node.names
                ):
                    importers.add(path.relative_to(root).as_posix())
        assert importers == {
            "application/action_engine.py",
            "application/outbox_consumer.py",
        }


def _record_payload(key: str) -> dict:
    return ActionRecord(
        id=key,
        user_id=USER,
        action_type="create_reminder",
        intent={"action_type": "create_reminder", "confidence": "confident", "params": {}},
        dedupe_key=f"plan8:{key}",
        params={},
        status="succeeded",
        created_at=support.NOW,
        updated_at=support.NOW,
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_world_fixture_is_readable_under_the_forward_switch_face(
    db_session_factory, forward_on, make_goal
):
    """夹具自检：本模块依赖的世界夹具在正向开关面下可用（防「夹具与开关面漂移」）。"""
    seed_all(USER)
    goal = make_goal(user_id=USER, description="夹具自检目标")
    result = await plan_context.PlanContextAssembler().assemble(goal, now=support.NOW)
    assert isinstance(result, PlanContext)
    assert result.world["weather"] == "sunny"
    assert result.world_context is not None
