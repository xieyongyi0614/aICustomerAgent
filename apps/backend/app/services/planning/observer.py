"""V2.5.0 PLAN-005 计划观测与终态结算（Task Detail §4.1.4 / §4.2.4 / §6.4；architecture.md §3.8、§8.5）。

本模块回答「做成了没有」。它**包装既有 `goal_observation`**（判据数学、推进裁决、失败计数
一律复用，零重写），只补三件事：第四类事实源（`tool`）、推进裁决的可观测面（`PlanAdvance`
落 `decision_records`）、终态结算的**唯一写面**（`settle`）。

四源事实包（B7 关闭点，§4.2.4）

| 源 | 内容 | 读取入口 | 是否新增 |
|---|---|---|---|
| `world` | 时间 / 时段 / 天气 / 地点 / 显著事件 | `world_engine.collect_facts` | ❌ |
| `state` | `tension` / `intimacy` / `mood` / `intensity` | `state_service.load_states` | ❌ |
| `memory` | `salient_memory_count` + 显著记忆投影 | `memory_repository.list_top_salience` | ❌ |
| `tool` | `steps[].result.observations`（白名单裁剪）+ `steps[].status` | `action_repository` 只读 | **✅** |

`tool` 源的两类判定（§4.2.4）**不新增判据类型**，也不复制判据数学：

- `field_equals` + `source="tool"`：既有 `evaluate_criteria` 经 `_fact_value(facts, "tool", path)`
  读的正是本模块装配的 `facts["tool"]`（白名单裁剪后的 `ToolResult.observations`）。
- `action_succeeded`：既有分支读 `facts["action_results"]`（台账投影，`status` 取
  **步级 `steps[].status`**，缺步骤时回退记录级 `status`）。两个投影在「是否 succeeded」上
  构造性等价：`action_engine` 的结账判据是 `outcome = next((s for s in statuses if s !=
  "succeeded"), "succeeded")`——全步 succeeded ⇔ 记录 succeeded；任一步非 succeeded ⇔ 记录
  非 succeeded（`failed` / `executing` / `cancelled` / `planned`）。故判定口径不变，信息更细。

`evaluate` 的两条 tool 源纪律（D10）：`threshold_reached` + `source="tool"` **不支持**
（Q4 冻结，模型层已拒、此处纵深防御）→ `None`；未声明判据 / 无对应事实 → `None`。
**绝不默认 `True`**。

`settle` 是唯一改 `GoalStatus` 的入口（D11）：`completed` → `finish_goal(completed)`；
`failed` → `finish_goal(failed, failure_reason="plan_exhausted")`；其余裁决（`advanced` /
`replanning` / `skipped` / `hold`，即 §6.4 所称「blocked / 冻结」）**冻结不写**。每次终态调
`goal_arbitration.record_goal_lifecycle` **一次**（目标已由既有写面结算过则不重复归因——
避免同一转换两行归因），并把 `PlanAdvance` 落 `decision_records`
（`kind='goal_lifecycle'`，**不新增 kind**，D12）。

**审计写入面与投影口（PLAN-011 §4.2.3 / §4.2.4 / §6.2）**：两条审计各有一个模块级公共写入面，
`settle` 经前者落地，故运行时语义零变化：

| 写入面 | `decision` | `trigger` | `input_snapshot` |
|---|---|---|---|
| `record_plan_advance` | `PlanAdvance.decision`（六值） | `plan_observer` | `PlanAdvance` 整体 |
| `record_plan_revision` | `plan_revised` | `plan_revision` | 修订链六字段 + `at` + 归属键 |

两者的 `kind` 恒为既有 `goal_lifecycle`；反向的 `project_plan_advance` /
`project_plan_revision` 是**唯一**的读回口径（形态不符即 `None`，绝不猜测）——修订链因此
可从 `decision_records` 与 `goal_plans` 两张既有表重建，零新表、零新列。

**终态广播（PLAN-008 §4.2.5 / §6.3）**：`_transition` 在迁移成功后调 `broadcast_goal_terminal`
（映射表 `TERMINAL_BROADCAST_OUTCOMES`，只含 `completed` / `abandoned`），经既有
`event_bridge.register_goal_event` → outbox → `world_events(type=goal_completed, source=character)`，
从而自动获得既有重要事件升级链路；`failed` 不广播，计划修订不产生终态迁移故结构上不可能广播；
广播失败只 log，**不回滚计划终态**（D15）。既有写面 `goal_observation._complete` 与
`goal_arbitration.check_abandonment` 各自的广播未改动（`settle` 只在「既有写面没结算」时迁移）。

**终态记忆（PLAN-009 §4.2.1 / §7.5.5）**：`_transition` 在迁移成功后调
`deliver_goal_terminal_memory`（映射表 `TERMINAL_MEMORY_EVENTS`，含 `completed` / `failed` /
`abandoned`），委托 `planning/memory_policy.py` 完成判据 B → 候选构造 → `memory_policy`
R1~R8 → `memories`（零新列）→ 幂等标记。
与广播的差别只在**覆盖面**：`failed` 不广播但**要**沉淀（「想帮用户做一件事但没做成」本身是
用户可感知的事实）；投递失败只 log，**不回滚计划终态**（D10 / D15 同款纪律）。计划本体与中间
步骤一律不进记忆（判据 B 的 ❌ 四行），步骤是否沉淀由该步的工具按 V2.4.0 边界表独立决定
（判据 C：两层正交，本模块不覆盖工具侧决策）。

与 Task Detail 的两处实现核对（已在测试留痕）

1. **§8.5 的 `settle(...) -> PlanOutcome` 改名为 `PlanSettlement`**：`PlanOutcome` 已被
   PLAN-003 的 `engine.py` 占用（规划产出：`status` / `plan` / `rejection_reason`），同名不同义
   会让同一命名空间出现两个契约。本任务按「不重名」返回 `PlanSettlement`
   （`decision` / `goal_status` / `transitioned` / `reason`），字段语义与 §8.5 一致。
2. **`PlanAdvance` 无 `blocked` 取值**：§4.2.5 的六值集不含 `blocked`，§8 Step 5.2 的
   「`blocked` → 冻结不写」即「**非终态裁决不写 `GoalStatus`**」。特别注意 `skipped`
   虽在 PLAN-002 的 `PLAN_ADVANCE_TERMINAL_DECISIONS` 内（不再推进同一版本），但它**不是**
   目标终态（旁支仍在推进），故 `settle` 对它同样冻结不写。

`collect_facts` 的 `observation_keys=` 是**白名单唯一入口**：显式注入优先；`None` 时由用户
当前 active 计划的步骤声明并集反推；显式**空**且 ctx 无目标时**不装配 `tool` 源**（零额外读取，
使既有 `life_loop._observation_facts` 的兼容出口与 V2.4.0 的查询面逐一相同）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import ValidationError

from app.application import observability, world_engine
from app.core.settings import get_settings
from app.models.goal import GoalStatus
from app.models.observability import DecisionKind, DecisionRecord
from app.models.plan import (
    PLAN_ACTION_DEDUPE_KEY_TEMPLATE,
    PLAN_STEP_DEDUPE_KEY_TEMPLATE,
    PlanAdvance,
    PlanRevision,
)
from app.repositories import action_repository, goal_repository, memory_repository
from app.services.goal import arbitration as goal_arbitration
from app.services.goal import observation as goal_observation
from app.services.conversation import state as state_service
from app.services.planning import goal_contract, memory_policy as plan_memory_policy
from app.services.planning import scheduler as plan_scheduler
from app.services.world import event_bridge

logger = logging.getLogger(__name__)

STEP_NAME = "plan_observer"

GOAL_STATUS_ACTIVE: GoalStatus = "active"
GOAL_STATUS_FAILED: GoalStatus = "failed"

FACT_SOURCE_WORLD = "world"
FACT_SOURCE_STATE = "state"
FACT_SOURCE_MEMORY = "memory"
FACT_SOURCE_TOOL = "tool"

FACT_SOURCES: tuple[str, ...] = (
    FACT_SOURCE_WORLD,
    FACT_SOURCE_STATE,
    FACT_SOURCE_MEMORY,
    FACT_SOURCE_TOOL,
)

FACT_ACTION_RESULTS = "action_results"
FACT_ACTION_HISTORY = "action_history"
FACT_SALIENT_MEMORIES = "salient_memories"
FACT_TOOL_RESULTS = "tool_results"

RECORDS_LIMIT = 50

OUTCOME_DECISIONS: dict[str, str] = {
    "advanced": "advanced",
    "completed": "completed",
    "failed": "failed",
    "replanning": "replanning",
    "retrying": "hold",
    "skipped": "skipped",
    "skipped_ahead": "skipped",
    "error": "hold",
}
"""既有 `advance_goal` 的 `detail["outcome"]` → `PlanAdvance.decision` 六值（§4.2.5）。

`skipped_ahead` → `skipped`（§4.2.5 归一）；`retrying` → `hold`（等 `next_retry_at`）；
`error` → `hold`（观测自身异常只 log，计划状态不变）。
"""

DECISION_OUTCOMES: dict[str, str | None] = {
    "advanced": None,
    "completed": "completed",
    "failed": "failed",
    "replanning": None,
    "skipped": None,
    "hold": None,
}
"""`PlanAdvance.decision` → `GoalStatus`（`None` = 冻结不写，§8 Step 5.2）。"""

REASON_PLAN_ADVANCED = "plan_step_advanced"
REASON_PLAN_HOLD = "plan_step_hold"
REASON_PLAN_SKIPPED = "plan_step_skipped"
REASON_PLAN_REPLANNING = "plan_replanning"
REASON_PLAN_COMPLETED = goal_observation.REASON_COMPLETED
REASON_PLAN_FAILED = goal_contract.PLANNING_FAILURE_REASON_PLAN_EXHAUSTED
REASON_OBSERVATION_ERROR = "observation_error"
REASON_PLAN_WRITE_REFUSED = "plan_write_refused"

DECISION_REASONS: dict[str, str] = {
    "advanced": REASON_PLAN_ADVANCED,
    "completed": REASON_PLAN_COMPLETED,
    "failed": REASON_PLAN_FAILED,
    "replanning": REASON_PLAN_REPLANNING,
    "skipped": REASON_PLAN_SKIPPED,
    "hold": REASON_PLAN_HOLD,
}

REASON_MAX_LENGTH = 60

DECISION_PLAN_REVISED = "plan_revised"
"""修订审计的 `decision` 取值（§4.2.4；`kind` 仍为既有 `goal_lifecycle`，不新增 kind）。"""

DECISION_TRIGGER_REVISION = "plan_revision"
"""修订审计行的 `trigger`（与推进行的 `STEP_NAME` 区分，使两张审计投影互不串行）。"""

TERMINAL_BROADCAST_OUTCOMES: dict[str, str] = {
    "completed": "completed",
    "abandoned": "abandoned",
}
"""终态广播的 `GoalStatus` → `outcome` 映射（PLAN-008 §4.3.2）。

`failed` **不在表内**（失败不是世界事实）；计划修订不产生终态迁移，结构上不可能广播。
`abandoned` 的计划侧迁移在本版本不发生（放弃由既有 `goal_arbitration.check_abandonment`
裁决并广播），映射表仍然显式列出，使计划侧若执行该迁移时广播语义与既有路径一致。
"""

TERMINAL_MEMORY_EVENTS: dict[str, str] = {
    "completed": plan_memory_policy.EVENT_PLAN_COMPLETED,
    "failed": plan_memory_policy.EVENT_PLAN_FAILED,
    "abandoned": plan_memory_policy.EVENT_PLAN_ABANDONED,
}
"""终态记忆的 `GoalStatus` → `event_kind` 映射（PLAN-009 §4.3.2）。

三类终态**都**沉淀（与广播表的关键差别：`failed` 不广播但**要**沉淀，失败语义本身是用户可感知
的事实）。同 `TERMINAL_BROADCAST_OUTCOMES`：`abandoned` 的计划侧迁移本版本不发生，映射表显式
列出使语义完整（既有 `check_abandonment` 路径端到端兑现）。
"""

__all__ = [
    "DECISION_OUTCOMES",
    "DECISION_PLAN_REVISED",
    "DECISION_REASONS",
    "DECISION_TRIGGER_REVISION",
    "FACT_ACTION_HISTORY",
    "FACT_ACTION_RESULTS",
    "FACT_SALIENT_MEMORIES",
    "FACT_SOURCES",
    "FACT_SOURCE_MEMORY",
    "FACT_SOURCE_STATE",
    "FACT_SOURCE_TOOL",
    "FACT_SOURCE_WORLD",
    "FACT_TOOL_RESULTS",
    "ObservationContext",
    "OUTCOME_DECISIONS",
    "PlanObserver",
    "PlanSettlement",
    "REASON_OBSERVATION_ERROR",
    "REASON_PLAN_WRITE_REFUSED",
    "STEP_NAME",
    "TERMINAL_BROADCAST_OUTCOMES",
    "TERMINAL_MEMORY_EVENTS",
    "broadcast_goal_terminal",
    "deliver_goal_terminal_memory",
    "project_plan_advance",
    "project_plan_revision",
    "record_plan_advance",
    "record_plan_revision",
]


@dataclass(frozen=True)
class ObservationContext:
    """`collect_facts` 的最小上下文（§8.5 的 `ctx` 在本任务的可判形态）。

    `PlanContext` 同样可直接传入（鸭子类型）：`goal_id` 取 `ctx.goal_id` 或 `ctx.goal.id`。
    `observation_keys` 三态即白名单纪律：`None`（缺省）= 由 active 计划的步骤声明反推；
    显式元组 = 以注入值为准（空元组 = 明确不装配 `tool` 源，零额外读取）。
    """

    now: datetime | None = None
    goal_id: str | None = None
    observation_keys: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PlanSettlement:
    """终态结算结果（`settle` 的返回契约，字段语义同 §8.5 的 `PlanOutcome`）。"""

    decision: str
    goal_status: str | None
    transitioned: bool
    reason: str


class PlanObserver:
    """观测 / 推进 / 结算（包装既有 `goal_observation`，零重写判据数学）。"""

    def collect_facts(
        self, user_id: str, ctx, *, observation_keys: tuple[str, ...] | None = None
    ) -> dict:
        """装配四源事实包（§4.2.4）：`world` / `state` / `memory` / `tool`。

        `facts` 的其余投影（`now` / `action_results` / `action_history` / `salient_memories`）
        与既有 `life_loop._observation_facts` **同源同形**（本方法即其搬运 + 第四源扩展），
        使 `goal_observation` 与 `goal_arbitration` 的既有消费面零改动。
        """
        settings = get_settings()
        now = _ctx_now(ctx)
        keys = self._resolve_keys(observation_keys, ctx)
        prefixes, keys = self._tool_scope(user_id, ctx, keys)
        records = _records(user_id)
        facts: dict = {
            "now": now,
            FACT_SOURCE_WORLD: {},
            FACT_SOURCE_STATE: {},
            FACT_SOURCE_MEMORY: {},
            FACT_ACTION_RESULTS: _action_results(records, now, settings),
            FACT_ACTION_HISTORY: _action_history(records, now, settings),
            FACT_SOURCE_TOOL: _tool_observations(records, prefixes, keys),
            FACT_TOOL_RESULTS: _tool_results(records, prefixes),
        }
        facts[FACT_SOURCE_WORLD] = _world_facts(settings, user_id)
        facts[FACT_SOURCE_STATE] = _state_facts(user_id)
        memory, salient = _memory_facts(settings, user_id)
        facts[FACT_SOURCE_MEMORY] = memory
        if salient:
            facts[FACT_SALIENT_MEMORIES] = salient
        return facts

    @staticmethod
    def evaluate(criteria: dict, facts: dict) -> bool | None:
        """判据求值（**委托既有 `evaluate_criteria`**，D9 零复制判据数学）。

        `threshold_reached` + `source="tool"` 一律 `None`（Q4 冻结）；其余一律以既有实现为
        唯一权威——未声明判据 / 无对应事实返回 `None`（不可判定），**绝不默认 `True`**。
        """
        if _unsupported_tool_criterion(criteria):
            return None
        return goal_observation.evaluate_criteria(criteria, facts)

    def observe(self, goal, plan, facts: dict, *, now: datetime) -> PlanAdvance:
        """推进裁决（委托既有 `advance_goal`），归一为六值 `PlanAdvance`（§4.2.5）。

        观测自身异常**只 log**：返回 `hold` + `observation_error`，计划状态不变（D13）——
        不把观测故障误判成执行故障。
        """
        current = plan_scheduler.PlanScheduler.current_step(plan)
        step_index = None if current is None else current.index
        try:
            detail = goal_observation.advance_goal(goal, plan, facts, now)
        except Exception:
            logger.exception("计划观测失败，计划状态不变（goal=%s）", goal.id)
            return PlanAdvance(
                goal_id=goal.id,
                plan_id=plan.id,
                plan_version=plan.version,
                decision="hold",
                reason=REASON_OBSERVATION_ERROR,
                at=now,
                step_index=step_index,
                facts_digest={"error": True},
            )
        decision = OUTCOME_DECISIONS.get(str(detail.get("outcome")), "hold")
        return PlanAdvance(
            goal_id=goal.id,
            plan_id=plan.id,
            plan_version=plan.version,
            decision=decision,
            reason=_reason(decision, detail),
            at=now,
            step_index=step_index,
            facts_digest=_facts_digest(facts, detail),
        )

    def settle(self, goal, plan, advance: PlanAdvance) -> PlanSettlement:
        """终态结算（**唯一改 `GoalStatus` 的入口**，D11）：落审计 + 唯一写面 + 归因一次。

        - `completed` → `goal_repository.finish_goal(.., "completed")`；
        - `failed` → `finish_goal(.., "failed", failure_reason="plan_exhausted")`；
        - 其余裁决（`advanced` / `replanning` / `skipped` / `hold`）→ **冻结不写**。
        - 目标已被既有写面（`goal_observation._complete` / `fail_goal`）结算时**不重复归因**：
          `settle` 只在目标仍为 `active` 时迁移并调 `goal_arbitration.record_goal_lifecycle`。
        """
        self._record_advance(goal, advance)
        target = DECISION_OUTCOMES.get(advance.decision)
        if target is None:
            return PlanSettlement(
                advance.decision, goal.status, False, advance.reason
            )
        current = goal_repository.get_goal(goal.id)
        if current is None or current.status != GOAL_STATUS_ACTIVE:
            return PlanSettlement(
                advance.decision,
                None if current is None else current.status,
                False,
                advance.reason,
            )
        return self._transition(goal, plan, advance, target)

    def observe_user_goals(self, user_id: str, facts: dict, *, now: datetime) -> dict:
        """编排入口：对用户当前 active 计划逐个 `observe` + `settle`（Step 8 的接线形态）。

        返回形状与既有 `goal_observation.advance_user_goals` 兼容（`goals` / `results`，
        `results[]` 带 `observations` 计数供既有编排步骤统计），并追加：
        `settled`（本次进入终态的**目标**数，含由既有写面 `_complete` 结算者）、
        `results[].transitioned`（`settle` 本人执行的迁移，与 `settled` 区分——同一转换不重复归因）
        与每条 `PlanAdvance` 的完整投影（计划推进的可观测面，B8）。
        """
        pairs = goal_repository.list_active_plans(user_id)
        if not pairs:
            return {"status": "ok", "goals": 0, "results": [], "settled": 0}
        results: list[dict] = []
        settled = 0
        for goal, plan in pairs:
            advance = self.observe(goal, plan, facts, now=now)
            settlement = self.settle(goal, plan, advance)
            terminal = DECISION_OUTCOMES.get(advance.decision) is not None
            if terminal:
                settled += 1
            results.append(
                {
                    "goal_id": goal.id,
                    "outcome": advance.decision,
                    "observations": 0 if advance.reason == REASON_OBSERVATION_ERROR else 1,
                    "advance": advance.model_dump(mode="json"),
                    "settled": terminal,
                    "transitioned": settlement.transitioned,
                }
            )
        return {
            "status": "ok",
            "goals": len(results),
            "results": results,
            "settled": settled,
        }

    def _transition(self, goal, plan, advance: PlanAdvance, target: str) -> PlanSettlement:
        """唯一写面迁移 + 归因一次；非法迁移按 §6.6 记日志且不改变计划状态。"""
        try:
            record = goal_repository.finish_goal(
                goal.id,
                target,
                failure_reason=(REASON_PLAN_FAILED if target == GOAL_STATUS_FAILED else None),
            )
        except ValueError:
            logger.exception(
                "目标终态迁移被迁移表拒绝，计划状态不变（goal=%s → %s）", goal.id, target
            )
            return PlanSettlement(
                advance.decision, goal.status, False, advance.reason
            )
        settled = record or goal
        self._record_lifecycle(settled, plan, advance, target)
        broadcast_goal_terminal(settled, target)
        deliver_goal_terminal_memory(settled, plan, target)
        return PlanSettlement(
            advance.decision,
            None if record is None else record.status,
            True,
            advance.reason,
        )

    @staticmethod
    def _record_lifecycle(record, plan, advance: PlanAdvance, target: str) -> None:
        """生命周期归因（每次终态**一次**）：委托既有公共入口，未新增 kind。"""
        try:
            goal_arbitration.record_goal_lifecycle(
                record,
                target,
                advance.reason,
                {
                    "goal_id": advance.goal_id,
                    "plan_id": plan.id,
                    "plan_version": plan.version,
                    "decision": advance.decision,
                },
            )
        except Exception:
            logger.exception("计划终态归因失败（goal=%s）", advance.goal_id)

    @staticmethod
    def _record_advance(goal, advance: PlanAdvance) -> None:
        """`PlanAdvance` → `decision_records`（复用 `kind='goal_lifecycle'`，B8 可观测面）。

        委托模块级公共写入面 `record_plan_advance`（§6.2）。`user_id` 由此处已知的目标注入，
        故 settle 热路径的读取面与 V2.4.0 逐一相同（不新增目标读取）。
        """
        record_plan_advance(advance, user_id=goal.user_id)

    @staticmethod
    def _resolve_keys(observation_keys, ctx) -> tuple[str, ...] | None:
        """白名单的唯一入口：显式注入优先；`ctx.observation_keys` 次之；皆无则 `None`（反推）。"""
        if observation_keys is not None:
            return tuple(observation_keys)
        from_ctx = getattr(ctx, "observation_keys", None)
        return None if from_ctx is None else tuple(from_ctx)

    @staticmethod
    def _tool_scope(user_id: str, ctx, keys: tuple[str, ...] | None):
        """工具台账的收敛范围与键白名单（零额外读取的短路见模块文档末段）。"""
        goal_id = _ctx_goal_id(ctx)
        if keys is not None and not keys and goal_id is None:
            return (), ()
        pairs = goal_repository.list_active_plans(user_id)
        goal_ids = (
            (goal_id,)
            if goal_id
            else tuple(sorted({goal.id for goal, _plan in pairs}))
        )
        resolved = _declared_keys(pairs, goal_id) if keys is None else keys
        return _prefixes(goal_ids), resolved


def record_plan_advance(advance: PlanAdvance, *, user_id: str | None = None) -> None:
    """推进审计写入面（§6.2）：`decision_records` 一行，`kind` 恒为既有 `goal_lifecycle`。

    列承载（§4.2.3）：`kind=DecisionKind.GOAL_LIFECYCLE` / `decision=advance.decision` /
    `input_snapshot=PlanAdvance` 整体 / `reason=advance.reason`；`trigger=STEP_NAME` 与
    `settle` 路径同源（既有用例按该 trigger 断言推进行）。

    `PlanAdvance` 自身不带归属字段而 `DecisionRecord.user_id` 必填，故归属按
    「注入优先、否则读目标」解析；注入缺失且目标不可得 → 只 log、**零写入**
    （审计写入异常一律不影响计划推进，§6.5）。
    """
    owner = user_id or _goal_owner(advance.goal_id)
    if not owner:
        logger.warning("计划推进审计缺少归属，已忽略（plan=%s）", advance.plan_id)
        return
    _emit_plan_decision(
        DecisionRecord(
            kind=DecisionKind.GOAL_LIFECYCLE,
            user_id=owner,
            conversation_id=None,
            action_id=None,
            trigger=STEP_NAME,
            input_snapshot=advance.model_dump(mode="json"),
            decision=advance.decision,
            reason=advance.reason,
        ),
        f"计划推进审计（plan={advance.plan_id}）",
    )


def record_plan_revision(
    revision: PlanRevision, *, plan=None, user_id: str | None = None
) -> None:
    """修订审计写入面（§4.2.4 / §6.2）：`decision_records` 一行，`decision="plan_revised"`。

    `kind` 仍为既有 `goal_lifecycle`（新增 kind 需改 CHECK = 需迁移，红线）；
    `input_snapshot` 承载修订链六字段 `from_version` / `to_version` / `reason` /
    `trigger_source` / `evidence_refs` / `kept_steps`，并附 `at`（链行需要时刻）与归属键
    `goal_id` / `plan_id`（`PlanRevision` 无归属字段，`?goal_id=` 的链过滤依赖它；两个附加键
    对 `PlanRevision.model_validate` 是安全未知键）。`plan` 只用于归属与归属键，不读取不改写。
    """
    owner = user_id or _plan_owner(plan)
    if not owner:
        logger.warning(
            "计划修订审计缺少归属，已忽略（to_version=%s）", revision.to_version
        )
        return
    snapshot = revision.model_dump(mode="json")
    snapshot["goal_id"] = str(getattr(plan, "goal_id", "") or "")
    snapshot["plan_id"] = str(getattr(plan, "id", "") or "")
    _emit_plan_decision(
        DecisionRecord(
            kind=DecisionKind.GOAL_LIFECYCLE,
            user_id=owner,
            conversation_id=None,
            action_id=None,
            trigger=DECISION_TRIGGER_REVISION,
            input_snapshot=snapshot,
            decision=DECISION_PLAN_REVISED,
            reason=revision.reason,
        ),
        f"计划修订审计（v{revision.from_version}→v{revision.to_version}）",
    )


def project_plan_advance(record: DecisionRecord) -> PlanAdvance | None:
    """审计行 → `PlanAdvance`（推进历史的重建口）。

    非计划推进审计行一律 `None`（**绝不猜测**）：非 `goal_lifecycle` kind、修订行、以及
    `input_snapshot` 无法还原为 `PlanAdvance` 的行（既有 `goal_observation` /
    `goal_arbitration` 的 lifecycle 归因行只带 `{"goal_id": ...}`）。
    """
    if not _is_plan_audit(record) or record.decision == DECISION_PLAN_REVISED:
        return None
    return _validate(PlanAdvance, record.input_snapshot)


def project_plan_revision(record: DecisionRecord) -> PlanRevision | None:
    """审计行 → `PlanRevision`（修订链的重建口）；非修订行或形态不符一律 `None`。"""
    if not _is_plan_audit(record) or record.decision != DECISION_PLAN_REVISED:
        return None
    return _validate(PlanRevision, record.input_snapshot)


def _emit_plan_decision(record: DecisionRecord, what: str) -> None:
    """计划审计的唯一落库点（行形态由调用方按 §4.2.3 / §4.2.4 构造，此处只做隔离）。"""
    try:
        observability.on_decision(record)
    except Exception:
        logger.exception("%s 落库失败，已忽略", what)


def _is_plan_audit(record: DecisionRecord) -> bool:
    """是否计划审计行（`goal_lifecycle` kind）——值集单一来源是 `DecisionKind`。"""
    return getattr(record, "kind", None) == DecisionKind.GOAL_LIFECYCLE


def _validate(model, payload):
    """`input_snapshot` → 值对象；形态不符返回 `None`（投影失败不抛错）。"""
    if not isinstance(payload, dict):
        return None
    try:
        return model.model_validate(payload)
    except ValidationError:
        return None


def _goal_owner(goal_id: str) -> str | None:
    """归属解析（只读）：目标行 → `user_id`；缺失或读取失败即 `None`。"""
    if not goal_id:
        return None
    try:
        goal = goal_repository.get_goal(str(goal_id))
    except Exception:
        logger.exception("计划审计归属解析失败：%s", goal_id)
        return None
    return None if goal is None else goal.user_id


def _plan_owner(plan) -> str | None:
    return _goal_owner(str(getattr(plan, "goal_id", "") or ""))


def broadcast_goal_terminal(goal, outcome: str) -> bool:
    """终态广播（PLAN-008 §4.2.5 / §6.3）：计划层的**唯一**世界事件表达。

    门控：无（计划编排已随开关体系删除转正常开）。
    只调既有 `event_bridge.register_goal_event`（复用既有 `goal_completed` 类型与既有
    outbox → `world_engine` 链路，不新增事件类型、不新增写入路径）；`outcome` 不在映射表内
    （`failed` 等）即零调用返回 `False`。广播失败（抛错 / Flag off / 幂等键命中）**只 log**：
    不回滚计划终态（§6.5 D15，与 V9「投递失败不回滚执行」同款纪律）。
    """
    mapped = TERMINAL_BROADCAST_OUTCOMES.get(outcome)
    if mapped is None:
        return False
    try:
        return bool(
            event_bridge.register_goal_event(
                goal.user_id, goal.id, goal.description, mapped
            )
        )
    except Exception:
        logger.exception("计划终态广播失败（goal=%s → %s）", goal.id, mapped)
        return False


def deliver_goal_terminal_memory(goal, plan, outcome: str, *, policy=None) -> dict | None:
    """终态记忆投递（PLAN-009 §4.2.1 / §7.5.5）：计划层的**唯一**记忆表达。

    只做 `GoalStatus` → `event_kind` 映射并委托 `memory_policy.deliver_plan_memory`（判据 B、
    候选构造、R1~R8、落库、幂等全在彼处）。投递失败只 log：**不回滚计划终态**
    （同款纪律）；`plan is None` 时不投递（隐私判别与幂等标记都以计划域台账为面）。
    """
    event_kind = TERMINAL_MEMORY_EVENTS.get(outcome)
    if event_kind is None or plan is None:
        return None
    return plan_memory_policy.deliver_plan_memory(
        goal, plan, event_kind, policy=policy
    )


def _unsupported_tool_criterion(criteria: dict, depth: int = 0) -> bool:
    """`threshold_reached` + `source="tool"`（含组合判据子项）：Q4 冻结，不支持（纵深防御）。"""
    if not isinstance(criteria, dict) or depth > 1:
        return False
    if criteria.get("type") == "threshold_reached":
        return criteria.get("source") == FACT_SOURCE_TOOL
    children = criteria.get("children")
    if not isinstance(children, list):
        return False
    return any(_unsupported_tool_criterion(child, depth + 1) for child in children)


def _reason(decision: str, detail: dict) -> str:
    """理由（≤60 字）：既有 `advance_goal` 给出的 `reason` 优先，否则按裁决取词表。"""
    reported = str(detail.get("reason") or "")
    if reported:
        return reported[:REASON_MAX_LENGTH]
    return DECISION_REASONS.get(decision, REASON_PLAN_HOLD)


def _facts_digest(facts: dict, detail: dict) -> dict:
    """判据所用事实摘要（**不含内容**：只记源名 / 计数 / 键名，§4.2.3）。"""
    moment = facts.get("now")
    return {
        "sources": sorted(
            name for name in FACT_SOURCES if facts.get(name)
        ),
        "action_results": len(facts.get(FACT_ACTION_RESULTS) or []),
        "tool_keys": sorted((facts.get(FACT_SOURCE_TOOL) or {}).keys()),
        "at": moment.isoformat() if isinstance(moment, datetime) else None,
        "outcome": detail.get("outcome"),
        "criteria_result": detail.get("criteria_result"),
        "attempt_count": detail.get("attempt_count"),
    }


def _records(user_id: str) -> list:
    """最近动作台账（既有只读入口，失败降级为空 → 工具源与判据按不可判定处理）。"""
    try:
        return action_repository.list_records(user_id, limit=RECORDS_LIMIT)
    except Exception:
        logger.exception("动作台账读取失败，判据按不可判定处理：%s", user_id)
        return []


def _action_results(records: list, now: datetime, settings) -> list[dict]:
    """动作观察窗投影（既有语义）：`status` 取步级 `steps[].status`，缺步骤回退记录级。"""
    window_start = now - timedelta(
        minutes=settings.autonomy_observation_window_minutes
    )
    return [
        {
            "capability": record.action_type,
            "status": _step_status(record) or record.status,
            "created_at": record.created_at,
        }
        for record in records
        if record.created_at is not None and record.created_at >= window_start
    ]


def _action_history(records: list, now: datetime, settings) -> list[dict]:
    """放弃判据的历史窗投影（既有语义，字段集不变）。"""
    history_start = now - timedelta(
        days=settings.autonomy_abandon_min_progress_days
    )
    return [
        {"capability": record.action_type, "created_at": record.created_at}
        for record in records
        if record.created_at is not None and record.created_at >= history_start
    ]


def _step_status(record) -> str | None:
    """步级状态（`action_records.steps[].status`）：无步骤返回 `None`（回退记录级）。"""
    for step in record.steps or []:
        if isinstance(step, dict) and step.get("status"):
            return str(step["status"])
    return None


def _world_facts(settings, user_id: str) -> dict:
    """世界源（可降级）：装配失败即空包（判据按不可判定处理）。"""
    try:
        return world_engine.collect_facts(user_id) or {}
    except Exception:
        logger.exception("world 事实采集失败，判据按不可判定处理")
        return {}


def _state_facts(user_id: str) -> dict:
    """状态源（判据 `CRITERION_METRIC_PATHS` 四值 + `intensity` 的既有投影）。"""
    try:
        character, relationship = state_service.load_states(user_id)
        return {
            "tension": relationship.tension,
            "intimacy": relationship.intimacy,
            "mood": character.mood,
            "intensity": character.intensity,
        }
    except Exception:
        logger.exception("状态事实采集失败，判据按不可判定处理")
        return {}


def _memory_facts(settings, user_id: str) -> tuple[dict, list]:
    """记忆源（可降级）：`salient_memory_count` + 显著记忆对象列表（`salient_memories`）。"""
    try:
        salient = memory_repository.list_top_salience(
            user_id,
            min_salience=settings.life_loop_memory_min_salience,
            limit=settings.life_loop_memory_limit,
        )
    except Exception:
        logger.exception("记忆事实采集失败，判据按不可判定处理")
        return {}, []
    return {"salient_memory_count": len(salient)}, list(salient)


def _ctx_now(ctx) -> datetime:
    value = getattr(ctx, "now", None)
    return value if isinstance(value, datetime) else datetime.now()


def _ctx_goal_id(ctx) -> str | None:
    """目标范围：`ctx.goal_id` 优先，其次 `ctx.goal.id`（`PlanContext` 形态）。"""
    direct = getattr(ctx, "goal_id", None)
    if direct:
        return str(direct)
    goal = getattr(ctx, "goal", None)
    goal_id = getattr(goal, "id", None)
    return None if not goal_id else str(goal_id)


def _declared_keys(pairs: list, goal_id: str | None) -> tuple[str, ...]:
    """白名单反推（§4.2.4 / PLAN-004 判据）：active 计划步骤的 `observation_keys` 并集。

    同计划内键名应唯一（`observation_keys` 由该步 `tool` 源判据反推，键名即判据语义）；
    跨步重名时后执行者胜出（台账按最新记录优先写入），语义已在本模块文档声明。
    """
    keys: list[str] = []
    for goal, plan in pairs:
        if goal_id is not None and goal.id != goal_id:
            continue
        for spec in plan.sub_goals:
            for key in spec.observation_keys:
                if key not in keys:
                    keys.append(key)
    return tuple(keys)


def _prefixes(goal_ids: tuple[str, ...]) -> tuple[str, ...]:
    """目标级幂等键前缀（两种既有形态的模板投影，零硬编码）。

    `action_records.goal_id` 由既有 `action_engine.new_record` 不写入（恒 `None`），故台账按
    **幂等键前缀**收敛到本目标：`plan:{goal_id}:`（本任务的执行桥）与 `goal:{goal_id}:`
    （既有 `goal_execution` 路径）——两条路径产生的步骤结果都进同一事实源。
    """
    prefixes: list[str] = []
    for goal_id in goal_ids:
        for template in (PLAN_STEP_DEDUPE_KEY_TEMPLATE, PLAN_ACTION_DEDUPE_KEY_TEMPLATE):
            prefixes.append(_prefix(template, goal_id))
    return tuple(prefixes)


def _prefix(template: str, goal_id: str) -> str:
    """模板 → 目标级前缀：取占位符之前的字面段 + 目标 id + 分隔符（`plan:{id}:` / `goal:{id}:`）。"""
    return f"{template.split('{', 1)[0]}{goal_id}:"


def _in_scope(record, prefixes: tuple[str, ...]) -> bool:
    return bool(record.dedupe_key) and any(
        record.dedupe_key.startswith(prefix) for prefix in prefixes
    )


def _tool_observations(
    records: list, prefixes: tuple[str, ...], keys: tuple[str, ...]
) -> dict:
    """`tool` 源：`ToolResult.observations` 的**白名单裁剪**投影（最新记录优先，首次写入胜出）。

    未在 `observation_keys` 声明的键**一律不可见**——防「偶发字段」变成隐式契约（§4.2.2 硬纪律）。
    """
    if not keys or not prefixes:
        return {}
    found: dict = {}
    for record in records:
        if not _in_scope(record, prefixes):
            continue
        for step in record.steps or []:
            observations = ((step or {}).get("result") or {}).get("observations")
            if not isinstance(observations, dict):
                continue
            for key in keys:
                if key in observations and key not in found:
                    found[key] = observations[key]
    return found


def _tool_results(records: list, prefixes: tuple[str, ...]) -> list[dict]:
    """步级状态投影（`action_records.steps[].status`）：供 `action_succeeded` 对照与审计。"""
    if not prefixes:
        return []
    projected: list[dict] = []
    for record in records:
        if not _in_scope(record, prefixes):
            continue
        for step in record.steps or []:
            if not isinstance(step, dict):
                continue
            projected.append(
                {
                    "capability": record.action_type,
                    "status": str(step.get("status") or ""),
                    "tool_id": step.get("tool_id"),
                    "action_id": record.id,
                    "at": step.get("started_at") or record.updated_at,
                }
            )
    return projected
