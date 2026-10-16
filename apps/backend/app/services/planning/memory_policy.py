"""V2.5.0 PLAN-009 计划终态记忆边界表（architecture.md §7.5.1 ~ §7.5.5 / §6.2 ⑦ / §9.6 G-MEMORY）。

本模块回答「计划这件事**整体**值不值得记住」，并把答案写成**纯数据 + 纯函数**；「这次**调用**
值不值得记住」仍归 V2.4.0 工具侧（`services/tool/memory_policy.py::BOUNDARY_TABLE`）。两层判据
正交：Planning 不新增工具记忆边界表、不覆盖工具侧的 deposit 决策（判据 C）。

三层交付

| 层 | 判什么 | 形态 |
|---|---|---|
| 判据 A | 计划本体是否落 `goal_plans` | `should_persist_plan`（三条条件全满足才落计划） |
| 判据 B | 计划终态是否进 `memories` | `PlanMemoryPolicy`（七行 `event_kind` × deposit/type/importance/source） |
| 判据 C | 步骤级沉淀 | **不由本层决定**，由该步调用的工具按 V2.4.0 边界表决定（本层只消费 `has_memory_effect`） |

七行边界表（§4.2.2 / §4.3.2）

| `event_kind` | deposit | `memory_type` | `importance` | `source` |
|---|---|---|---|---|
| `plan_completed` | ✅ | `experience` | 0.7 | `user_derived` |
| `plan_failed` | ✅ | `experience` | ≥ `plan_memory_importance_floor` | `user_derived` |
| `plan_abandoned` | ✅ | `experience` | ≥ `plan_memory_importance_floor` | `user_derived` |
| `plan_created` / `plan_revised` / `step_succeeded` / `step_failed` | ❌ | — | — | — |

**G-MEMORY（本任务唯一 Gate）**：`memory_policy._evaluate` 的 R1 对 `source == "ai_inferred"`
一律 `DECISION_DISCARD / "R1"`（「AI 推测不入库」）。故三类终态的 `source` 恒为 `user_derived`，
失败 / 放弃类另加重要度下限；`decide` 内对 `ai_inferred` 行**显式 fail-fast**（配置被写错即实现
缺陷，不静默降级成一条存不进记忆的候选）。

候选构造（§6.3）

- `plan_completed`：**复用**既有 `memory.ingest.ingest_from_goal_completion(user_id, goal_id,
  description)`——其内容（`完成了目标：{description}`）即完成语义、其幂等锚点
  `{goal_id}:completed` 与既有 AUT-003 完成通道**同锚**（重复投递不产生第二条候选行）。
- `plan_failed` / `plan_abandoned`：走 §4.2.2 的**加权重路径**——内容锚定用户委托的目标描述
  并带未完成语义（措辞逐字复用 V9 失败纪律 `上次没能帮用户完成：…`）、重要度取
  `max(FAILED_IMPORTANCE_FLOOR, plan_memory_importance_floor)`。
- 隐私步骤参数（§4.2.2 末行）：步骤 `params` 命中既有显式遗忘指令（`memory.commands.detect_command`
  → `forget`）→ 候选取 `action="forget"`，经 `memory_policy` **R3** 分支判为
  `DECISION_PRIVACY`（「用户要求遗忘，转隐私执行」）并移交既有隐私通道；**本层不复制遗忘执行
  逻辑、不写 `memories`**。隐私优先于沉淀：一个终态只出一个候选。
- 长度一律受 `MEMORY_CONTENT_MAX_CHARS`（120）约束。

记忆通道（零新建，§7.5.5）

```text
计划终态 → 判据 B（deposit=False ⇒ 直接返回，零写入）
        → 候选构造（复用既有 ingest / 加权重模板）
        → memory_policy.apply_policy([candidate], active_contents)   ← R1~R8 零豁免
        → memory_repository.create_memory（既有写面，零新列）
        → effects 登记 kind=memory（幂等标记）
```

**零旁路**：本模块零直接 INSERT、零 `session.*`、零 `sqlalchemy`；`memories` 的写入只有
`memory_repository.create_memory` 一个入口，且必在 `apply_policy` 之后；政策闸未过 → 丢弃
（**不回滚计划终态**，与 V9「投递失败不回滚执行」同款纪律，D10）。

幂等承载位（§4.2.4 / §7）与两处实现核对（已在测试留痕）

1. **承载位读面**：Task Detail 记 `action_records.steps[].result.effects`，而既有幂等判定
   `services/tool/memory_policy.py::has_memory_effect(record)` 读的是**记录级** `result.effects`。
   两者不可同时满足，本任务按**既有读面**落记录级，使「登记位」与「检测函数」同源（否则标记
   写了也检测不到）。
2. **承载位的记录选取**：计划终态在 `settle` 时刻**没有专属 action record**（终态由 Goal 域
   结算产生）。故标记落在计划域（`plan:{goal_id}:` 幂等键前缀）**最新一条** action record 上，
   经既有 `action_repository.save_record` 写入——零新列、零新表。计划域无任何记录时（如从未
   执行过步骤）不落标记，幂等退化为「转态唯一 + 政策闸 R7」两层兜底。
3. **标记判别**：工具侧 deposit 也会写 `kind=memory`（V2.4.0），故检测必须叠加计划域的
   `detail` 判别（`PLAN_MEMORY_RECEIPT_DETAIL`）。只用 `has_memory_effect` 会把「工具侧已沉淀」
   误当成「终态已投递」，使含 `builtin.reminder.create` 步骤的计划永远拿不到终态记忆——
   正交性用例（判据 C）即防这条回归。

与 Task Detail §8 Step 1.3 的接入点确认：判据 A 以**纯判据资产 + 五类场景裁决**交付，**不新增
第七道闸以外的新闸**——`PlanningEngine` 的七道闸与 `goal_repository.create_plan` 调用点是
PLAN-003 的既有链路（单步计划在 PLAN-003 用例中就被断言会落库），在此处插入判据 A 会改变
PLAN-003 / PLAN-005 的既有行为，违反零回归纪律。接入点留待后续任务按需评估。

非范围：`memory_policy` R1~R8 改动、`memory.*` 改动、工具侧边界表改动、`memories` 表结构
（零迁移）、反思证据窗（PLAN-010）、世界写入（PLAN-008）、自治 `plan_facts`（PLAN-007）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.core.settings import get_settings
from app.models.memory import MemoryCandidate
from app.models.plan import PLAN_STEP_DEDUPE_KEY_TEMPLATE
from app.repositories import action_repository, memory_repository
from app.engines import memory_policy as memory_policy_gate
from app.services.memory import commands as memory_commands
from app.services.memory import ingest as memory_ingest
from app.services.memory import types as memory_types
from app.services.tool import memory_policy as tool_memory_policy
from app.services.tool.memory_policy import (
    DEFAULT_CONFIDENCE,
    DEFAULT_IMPORTANCE,
    DEFAULT_MEMORY_TYPE,
    DEFAULT_SOURCE,
    FAILED_IMPORTANCE_FLOOR,
    MEMORY_CONTENT_MAX_CHARS,
    REASON_NO_POLICY_ROW,
    REASON_POLICY_DECLINED,
    REASON_POLICY_DEPOSIT,
)

logger = logging.getLogger(__name__)

CHARACTER_ID = "asuna"
"""记忆落库的角色 id（与既有 `memory.ingest` / `memory_bridge` 同款默认值）。"""

ACTIVE_MEMORY_LIMIT = 200
"""政策闸 R7 的活跃记忆比对窗（与既有 `memory_service.extract_and_save` 同款取值）。"""

RECORD_SCAN_LIMIT = 50
"""计划域台账扫描窗（与 `observer.RECORDS_LIMIT` 同款取值）。"""

PLAN_PERSIST_MIN_STEPS = 2
"""判据 A1 的步数下限（§4.2.1：「步骤数 ≥ 2 **或** 需要跨 tick 观测」）。"""

PLAN_COMPLETED_IMPORTANCE = 0.7
"""完成类终态的重要度（§4.2.2 表；与 `BOUNDARY_TABLE["builtin.reminder.create"]` 同款取值）。"""

PLAN_UNFINISHED_CONTENT_TEMPLATE = "上次没能帮用户完成：{description}"
"""失败 / 放弃类终态的内容模板（未完成语义；措辞逐字复用 V9 失败纪律）。"""

PLAN_MEMORY_RECEIPT_DETAIL = "已记住计划终态"
"""计划终态记忆的幂等标记 detail（判别本层标记与工具侧 `已记住` 的唯一依据）。"""

EVENT_PLAN_COMPLETED = "plan_completed"
EVENT_PLAN_FAILED = "plan_failed"
EVENT_PLAN_ABANDONED = "plan_abandoned"
EVENT_PLAN_CREATED = "plan_created"
EVENT_PLAN_REVISED = "plan_revised"
EVENT_STEP_SUCCEEDED = "step_succeeded"
EVENT_STEP_FAILED = "step_failed"

PLAN_MEMORY_EVENT_KINDS: tuple[str, ...] = (
    EVENT_PLAN_COMPLETED,
    EVENT_PLAN_FAILED,
    EVENT_PLAN_ABANDONED,
    EVENT_PLAN_CREATED,
    EVENT_PLAN_REVISED,
    EVENT_STEP_SUCCEEDED,
    EVENT_STEP_FAILED,
)
"""七值 `event_kind`（§6.2）：取值集恰为七值、与边界表逐行对应，零新增取值。"""

PLAN_MEMORY_FLOOR_EVENT_KINDS: tuple[str, ...] = (EVENT_PLAN_FAILED, EVENT_PLAN_ABANDONED)
"""受 `plan_memory_importance_floor` 约束的两行（§4.2.5：失败 / 放弃类）。"""

PLAN_MEMORY_BOUNDARY_TABLE: dict[str, dict[str, Any]] = {
    EVENT_PLAN_COMPLETED: {
        "deposit": True,
        "memory_type": DEFAULT_MEMORY_TYPE,
        "importance": PLAN_COMPLETED_IMPORTANCE,
        "source": DEFAULT_SOURCE,
    },
    EVENT_PLAN_FAILED: {
        "deposit": True,
        "memory_type": DEFAULT_MEMORY_TYPE,
        "importance": FAILED_IMPORTANCE_FLOOR,
        "source": DEFAULT_SOURCE,
    },
    EVENT_PLAN_ABANDONED: {
        "deposit": True,
        "memory_type": DEFAULT_MEMORY_TYPE,
        "importance": FAILED_IMPORTANCE_FLOOR,
        "source": DEFAULT_SOURCE,
    },
    EVENT_PLAN_CREATED: {"deposit": False},
    EVENT_PLAN_REVISED: {"deposit": False},
    EVENT_STEP_SUCCEEDED: {"deposit": False},
    EVENT_STEP_FAILED: {"deposit": False},
}
"""计划终态记忆边界表（七行；形态对齐 `services/tool/memory_policy.py::BOUNDARY_TABLE`）。

`deposit` 为 `False` 的四行**不带任何沉积字段**——「计划本体与中间步骤不进记忆」是结构性的，
不是靠下游过滤（❌ 行让「计划创建 -> 记忆噪声」在判据层就不可能发生）。
"""

__all__ = [
    "ACTIVE_MEMORY_LIMIT",
    "CHARACTER_ID",
    "EVENT_PLAN_ABANDONED",
    "EVENT_PLAN_COMPLETED",
    "EVENT_PLAN_CREATED",
    "EVENT_PLAN_FAILED",
    "EVENT_PLAN_REVISED",
    "EVENT_STEP_FAILED",
    "EVENT_STEP_SUCCEEDED",
    "PLAN_COMPLETED_IMPORTANCE",
    "PLAN_MEMORY_BOUNDARY_TABLE",
    "PLAN_MEMORY_EVENT_KINDS",
    "PLAN_MEMORY_FLOOR_EVENT_KINDS",
    "PLAN_MEMORY_RECEIPT_DETAIL",
    "PLAN_PERSIST_MIN_STEPS",
    "PLAN_UNFINISHED_CONTENT_TEMPLATE",
    "PlanMemoryDecision",
    "PlanMemoryPolicy",
    "build_candidate",
    "deliver_plan_memory",
    "get_plan_memory_policy",
    "should_persist_plan",
]


def should_persist_plan(
    *,
    step_count: int,
    cross_tick: bool,
    every_step_has_criteria: bool,
    needs_idempotency_or_recovery: bool,
) -> bool:
    """判据 A（§4.2.1 / §6.1）：计划本体是否落 `goal_plans`——三条条件**全满足**才落计划。

    | # | 条件 | 说明 |
    |---|---|---|
    | A1 | `step_count >= 2` **或** `cross_tick` | 单步且当场可判定 → 不需要计划结构 |
    | A2 | 每步有独立达成判据 | 无判据 → 不可观测 → 不构成 Task |
    | A3 | 需要幂等 / 重试 / 失败恢复 | 一次性无副作用操作不需要计划 |

    纯函数、零 IO、零 LLM：只做合取，不读设置、不读库、不读时钟。
    """
    criterion_a1 = step_count >= PLAN_PERSIST_MIN_STEPS or bool(cross_tick)
    criterion_a2 = bool(every_step_has_criteria)
    criterion_a3 = bool(needs_idempotency_or_recovery)
    return criterion_a1 and criterion_a2 and criterion_a3


@dataclass(frozen=True)
class PlanMemoryDecision:
    """计划终态的沉积决策（§6.2；形态同构 `services/tool/memory_policy.py::MemoryDecision`）。

    `deposit` 为 `False` 时其余字段恒 `None`（拒收行不带沉积配置）；`source` 对三类终态恒为
    `user_derived`（G-MEMORY：`ai_inferred` 会被 R1 丢弃）。
    """

    deposit: bool
    reason: str
    memory_type: str | None = None
    importance: float | None = None
    source: str | None = None
    template_key: str | None = None


class PlanMemoryPolicy:
    """计划终态记忆边界表：行查询 + 决策（纯数据 + 纯函数；零 IO、零 LLM）。"""

    def __init__(self, rows: dict[str, dict[str, Any]] | None = None) -> None:
        self._rows = dict(PLAN_MEMORY_BOUNDARY_TABLE if rows is None else rows)

    def row_for(self, event_kind: str) -> dict[str, Any] | None:
        """行查询：未知 `event_kind` 返回 `None`（不猜测、不默认沉积）。"""
        row = self._rows.get(event_kind)
        return None if row is None else dict(row)

    def decide(self, event_kind: str, *, settings=None) -> PlanMemoryDecision:
        """`event_kind` → 沉积决策（§6.2 冻结签名；`settings` 可注入以便确定性用例）。

        失败 / 放弃类另施加 `plan_memory_importance_floor`（§4.2.5）；`ai_inferred` 行
        **fail-fast**（G-MEMORY：该取值必然被 R1 丢弃，静默放行等于交付一条存不进的候选）。
        """
        resolved = settings if settings is not None else get_settings()
        row = self.row_for(event_kind)
        if row is None:
            return PlanMemoryDecision(False, REASON_NO_POLICY_ROW)
        if not row.get("deposit"):
            return PlanMemoryDecision(False, REASON_POLICY_DECLINED)
        source = str(row.get("source", DEFAULT_SOURCE))
        if source == "ai_inferred":
            raise ValueError(
                f"计划终态记忆不得使用 ai_inferred（R1 拒收）: {event_kind}"
            )
        importance = float(row.get("importance", DEFAULT_IMPORTANCE))
        if event_kind in PLAN_MEMORY_FLOOR_EVENT_KINDS:
            importance = max(importance, resolved.plan_memory_importance_floor)
        return PlanMemoryDecision(
            True,
            REASON_POLICY_DEPOSIT,
            memory_type=str(row.get("memory_type", DEFAULT_MEMORY_TYPE)),
            importance=importance,
            source=source,
            template_key=event_kind,
        )


_DEFAULT_POLICY = PlanMemoryPolicy()


def get_plan_memory_policy() -> PlanMemoryPolicy:
    """模块级默认边界表（纯数据，无环境依赖，无重置语义）。"""
    return _DEFAULT_POLICY


def build_candidate(
    goal, plan, event_kind: str, *, policy: PlanMemoryPolicy | None = None, settings=None
) -> MemoryCandidate | None:
    """计划终态 → 0..1 条记忆候选（§6.3）；`deposit=False` 的事件返回 `None`（零写入）。

    异常契约（§6.5）：候选构造异常由投递入口统一承接（跳过本次沉淀、log、不影响计划终态），
    本函数不吞异常——把失败面留给唯一调用方，避免「静默返回 None」把构造故障伪装成判据拒收。
    """
    decision = (policy or get_plan_memory_policy()).decide(event_kind, settings=settings)
    if decision.deposit is not True:
        return None
    privacy_target = _privacy_target(plan)
    if privacy_target is not None:
        return _candidate("forget", privacy_target, decision)
    content = _content_for(goal, event_kind)
    if not content:
        return None
    return _candidate("save", content, decision)


def deliver_plan_memory(goal, plan, event_kind: str, *, policy=None) -> dict | None:
    """计划终态记忆投递：门控 + 幂等 + 判据 B + 候选构造 + R1~R8 + 落库（§7.5.5）。

    返回值三态：`None`（未投递 / 被政策闸丢弃 / 重复投递）、`{"privacy": True, ...}`（R3 转隐私
    执行）、`{"memory_id": ..., "content": ...}`（已沉淀）。任何异常只 log——政策闸未过与落库
    失败都**不回滚计划终态**（D10）。
    """
    try:
        return _deliver(goal, plan, event_kind, policy)
    except Exception:
        logger.exception("计划终态记忆投递失败（不回滚计划终态）")
        return None


def _deliver(goal, plan, event_kind: str, policy) -> dict | None:
    """投递主体（幂等复核 → 判据 B → 政策闸 → 落库与标记）；异常由 `deliver_plan_memory` 承接。"""
    if plan is None or _has_receipt(goal):
        return None
    candidate = build_candidate(goal, plan, event_kind, policy=policy)
    if candidate is None:
        return None
    report = memory_policy_gate.apply_policy([candidate], _active_contents(goal.user_id))
    privacy = _privacy_outcome(report)
    if privacy is not None:
        logger.info(
            "计划终态候选经 %s 转隐私执行（goal=%s, event=%s）",
            privacy.rule,
            goal.id,
            event_kind,
        )
        return {
            "privacy": True,
            "decision": privacy.decision,
            "rule": privacy.rule,
            "event_kind": event_kind,
            "content": privacy.candidate.content,
        }
    saved = report.saved
    if not saved:
        logger.info(
            "计划终态候选未通过政策闸，已丢弃（不回滚计划终态）: goal=%s rules=%s",
            goal.id,
            [outcome.rule for outcome in report.discarded],
        )
        return None
    chosen = saved[0]
    stored_type = memory_types.normalize_type(chosen.type)
    if stored_type is None:
        logger.warning(
            "计划终态记忆类型非法，已丢弃（不回滚计划终态）: goal=%s type=%s",
            goal.id,
            chosen.type,
        )
        return None
    memory = memory_repository.create_memory(
        goal.user_id,
        CHARACTER_ID,
        content=chosen.content or "",
        memory_type=stored_type,
        importance=chosen.importance,
        confidence=chosen.confidence,
        source=chosen.source,
    )
    _register_receipt(goal, memory.id)
    return {
        "memory_id": memory.id,
        "content": memory.content,
        "event_kind": event_kind,
    }


def _candidate(action: str, content: str, decision: PlanMemoryDecision) -> MemoryCandidate:
    """候选构造（§6.3）：类型 / 重要度 / 来源取自判据 B，置信度与长度预算复用工具侧取值。"""
    return MemoryCandidate(
        action=action,
        type=decision.memory_type or DEFAULT_MEMORY_TYPE,
        content=content[: MEMORY_CONTENT_MAX_CHARS],
        importance=(
            DEFAULT_IMPORTANCE
            if decision.importance is None
            else decision.importance
        ),
        confidence=DEFAULT_CONFIDENCE,
        source=decision.source or DEFAULT_SOURCE,
    )


def _content_for(goal, event_kind: str) -> str:
    """内容模板（§8 Step 3.2）：完成类复用既有摄取，失败 / 放弃类带未完成语义。"""
    if event_kind == EVENT_PLAN_COMPLETED:
        row = memory_ingest.ingest_from_goal_completion(
            goal.user_id, goal.id, goal.description
        )
        return "" if row is None else str(row.content or "")
    if event_kind in PLAN_MEMORY_FLOOR_EVENT_KINDS:
        return PLAN_UNFINISHED_CONTENT_TEMPLATE.format(description=goal.description)
    return ""


def _privacy_target(plan) -> str | None:
    """隐私步骤参数（§4.2.2 末行）：步骤 `params` 命中既有显式遗忘指令即返回待遗忘对象。

    识别复用既有 `memory.commands.detect_command`（词表、疑问句与短对象纪律一并复用），
    **不新增隐私词表**；本层只做路由，遗忘执行仍归既有隐私通道。
    """
    if plan is None:
        return None
    for spec in plan.sub_goals:
        for value in _params(spec):
            detected = memory_commands.detect_command(value)
            if detected is not None and detected[0] == memory_commands.ACTION_FORGET:
                return detected[1]
    return None


def _params(spec) -> list[str]:
    params = getattr(spec, "params", None) or {}
    return [value for value in params.values() if isinstance(value, str)]


def _privacy_outcome(report):
    """R3 结果（§6.6：隐私请求**不是异常**，是既有分支的正常产出）；无隐私项返回 `None`。"""
    for outcome in report.outcomes:
        if outcome.decision == memory_policy_gate.DECISION_PRIVACY:
            return outcome
    return None


def _active_contents(user_id: str) -> list[str]:
    """政策闸 R7 的比对窗（读取失败降级为空，与既有 `memory_service` 同款处置）。"""
    try:
        active = memory_repository.list_active(
            user_id, CHARACTER_ID, limit=ACTIVE_MEMORY_LIMIT
        )
    except Exception:
        logger.exception("活跃记忆读取失败，R7 去重降级为空窗")
        return []
    return [memory.content for memory in active]


def _plan_scope_records(goal) -> list:
    """计划域台账（`plan:{goal_id}:` 幂等键前缀，最新优先）：幂等标记的读写面。"""
    try:
        records = action_repository.list_records(goal.user_id, limit=RECORD_SCAN_LIMIT)
    except Exception:
        logger.exception("计划域台账读取失败，幂等标记按未登记处理")
        return []
    prefix = f"{PLAN_STEP_DEDUPE_KEY_TEMPLATE.split('{', 1)[0]}{goal.id}:"
    return [record for record in records if str(record.dedupe_key or "").startswith(prefix)]


def _has_receipt(goal) -> bool:
    """幂等检测（§4.2.4）：计划域台账中已登记本层标记 → 重复投递不再产生第二条记忆。"""
    return any(_carries_receipt(record) for record in _plan_scope_records(goal))


def _carries_receipt(record) -> bool:
    """标记判别：复用既有 `has_memory_effect`（泛化）**并**叠加计划域 `detail` 判别。

    只用前者会把工具侧 deposit（`builtin.reminder.create` 等）误判成本层已投递，从而让含工具
    沉淀步骤的计划永远拿不到终态记忆——两层判据由此保持正交（判据 C）。
    """
    if not tool_memory_policy.has_memory_effect(record):
        return False
    result = record.result or {}
    effects = result.get("effects")
    if not isinstance(effects, list):
        return False
    return any(
        isinstance(effect, dict) and effect.get("detail") == PLAN_MEMORY_RECEIPT_DETAIL
        for effect in effects
    )


def _register_receipt(goal, memory_id: str) -> None:
    """幂等标记登记（落库成功后）：追加 `kind="memory"`（与 `action_engine._append_effect` 同款
    取值）到计划域最新台账行；**无计划域记录时不落标记**（幂等退化为转态唯一 + 政策闸 R7）。
    """
    records = _plan_scope_records(goal)
    if not records:
        return
    record = records[0]
    if _carries_receipt(record):
        return
    try:
        result = dict(record.result or {"status": record.status, "effects": []})
        effects = list(result.get("effects") or [])
        effects.append(
            {"kind": "memory", "ref": memory_id, "detail": PLAN_MEMORY_RECEIPT_DETAIL}
        )
        result["effects"] = effects
        record.result = result
        action_repository.save_record(record)
    except Exception:
        logger.exception("计划终态记忆幂等标记登记失败，重复投递由政策闸 R7 兜底")
