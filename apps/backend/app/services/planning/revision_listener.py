"""V2.5.0 PLAN-010 重规划监听器（Task Detail §4.1.2 / §4.2.2 / §4.3.2 / §6.3；architecture.md §7.6 ④⑤、§8.6）。

本模块是**本版本唯一的 Planning 侧反思接线**：`reflection/lifecycle.register_insight_created_listener`
的第四个注册点（既有三处：`development/policy.py` / `relationship_narrative.py` /
`world/event_bridge.py`，三者零改动）。

职责边界一句话：**反思分析计划效能，但不改写计划**。`on_insight_created` 的全部行为就是
「判断该不该投一个幂等的重规划触发，该投就投一次」——它不碰计划、不碰目标状态、不碰工具注册表。

```text
notify_insight_created_listeners(user_id, created)
    ├─ 三个既有消费者（零改动）
    └─ ★ PlanningRevisionListener.on_insight_created
          ├─ 门槛一：insight.type ∈ PLAN_INFLUENCE_INSIGHT_TYPES（capability_note / pattern）
          ├─ 门槛二：insight.confidence ≥ plan_replan_min_confidence（0.7）
          ├─ 门槛三：存在可映射的 active 目标（scope → 目标 domain）
          └─ 全过 → enqueue_replan（幂等键 plan_replan:{goal_id}:{insight_id}）
                ▼
            goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)   ← 唯一动作，到此为止
```

Q8 裁决（§4.3.2 / §9.7 Q8）：四条重规划判据同时命中时只产生**一个**重规划触发

| 优先序 | 理由码 | 性质 |
|---|---|---|
| 1 | `step_attempt_exhausted` | 事实（步骤层，最直接） |
| 2 | `criteria_undecidable` | 事实（判据层） |
| 3 | `tool_persistently_unavailable` | 事实（工具面，可能暂时性） |
| 4 | `insight_driven` | **建议**（认知层统计倾向，最弱） |

裁决理由：事实优先于建议——反思的统计倾向不得覆盖计划自身的失败证据。归一由
`dominant_revision_reason` 承担（纯函数，`REVISION_REASON_PRIORITY` 即上表）；
`PlanRevisionPolicy.should_replan` 的判定实现属 PLAN-005，本任务**不改**它（Task Detail §1.2
Non-Scope），只提供 `insight_driven` 这个触发源与归一资产。

**幂等的双重保障**（§4.3.2）：本任务层 `plan_replan:{goal_id}:{insight_id}`（同一 Insight
对同一目标只触发一次）+ 既有 job 层 `background_job_repository.has_job(idempotency_key)`
（`enqueue_planning` 内部，同一目标的重规划 job 不重复入队）。

明确不做（§4.4 / §5.2）

1. ❌ 不直接改写 `sub_goals` / `GoalPlanStatus`（规划改写只发生在 `goal_planning` 的新轮次里）。
2. ❌ 不直接改 `GoalStatus`（唯一写面在 `goal_repository`，由 PLAN-005 `settle` 使用）。
3. ❌ 不直接写计划表（落库面属 PLAN-003 计划引擎；本模块零 `create_plan` / `set_plan_status`）。
4. ❌ 零工具注册表调用（工具下线 / 健康度另有通道，反思不得形成「反思 → 熔断工具」的耦合）。
5. ❌ 不在 `foreground` 关键路径执行（本模块由 `reflection_run` 后台 job 的落库回调触发）。

**证据引用（§4.2.5 / §8 Step 5）**：触发时把 Insight id 记进监听器的证据账
（`evidence_refs_for`），供装配期为重规划轮次填充 `RunContext.data["evidence_refs"]` →
`PlanContext.evidence_refs` → 规划 prompt 与 `GoalPlanRecord.evidence_refs`。
账目是进程内内存态（重启即丢，与既有 `triggers._tool_evidence_seen` 同款纪律）：
它只影响「下一轮规划能带上哪些证据」，不影响任何闸门判定。
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.settings import get_settings
from app.models.goal import LAYER_VALUES
from app.models.plan import PlanRevision
from app.models.reflection import InsightScopeEnum
from app.repositories import goal_repository
from app.services.goal import planning as goal_planning
from app.services.planning import revision as plan_revision

logger = logging.getLogger(__name__)

STEP_NAME = "plan_revision_listener"

REASON_INSIGHT_DRIVEN = plan_revision.REASON_INSIGHT_DRIVEN

PLAN_INFLUENCE_INSIGHT_TYPES: tuple[str, ...] = ("capability_note", "pattern")
"""门槛一的影响类型值域（§4.2.3）：计划证据窗只产这两类认知（`usage_preference` 亦属窗口
允许类型，但不构成重规划理由）。零新增配置：值集随反思域的既有类型域而变。"""

REVISION_REASON_PRIORITY: tuple[str, ...] = (
    plan_revision.REASON_STEP_ATTEMPT_EXHAUSTED,
    plan_revision.REASON_CRITERIA_UNDECIDABLE,
    plan_revision.REASON_TOOL_PERSISTENTLY_UNAVAILABLE,
    plan_revision.REASON_INSIGHT_DRIVEN,
)
"""Q8 裁决的固定优先序（事实优先于建议，§4.3.2 表序）。"""

SCOPE_GOAL_DOMAINS: dict[str, tuple[str, ...]] = {
    InsightScopeEnum.USER.value: ("personal",),
    InsightScopeEnum.RELATIONSHIP.value: ("relationship",),
    InsightScopeEnum.WORLD.value: ("world",),
}
"""门槛三的 scope → 目标 domain 映射（§4.2.2）。

键取自反思域的 `InsightScopeEnum`（而不是字面量：scope 值集的唯一声明处在
`models/reflection.py`，计划层不复制它）；`relationship` 域给出对关系类目标的映射，
但计划证据窗的结构性 scope 闸只允许 user / world 两值——映射留此以免静默丢弃。
"""

PLANNABLE_LAYERS: tuple[str, ...] = tuple(LAYER_VALUES)
"""可重规划的层级（层级目标才有计划；v1 行 `layer is None` 不参与）。"""

REPLAN_IDEMPOTENCY_TEMPLATE = "plan_replan:{goal_id}:{insight_id}"
"""本任务层幂等键形态（§4.2.2 D11）。"""

LEDGER_LIMIT = 500


class PlanningRevisionListener:
    """重规划监听器（§8.6 冻结契约：`on_insight_created` / `enqueue_replan`）。

    三个协作面可注入（仅影响测试与复用场景，缺省即既有实现）：`enqueue`（唯一动作，
    缺省 `goal_planning.enqueue_planning`）、`goal_reader`（目标只读）、`candidates`
    （可映射目标候选，缺省 `goal_repository.list_active_plans`）。`settings_provider`
    可注入以固定门控（确定性用例）。
    """

    def __init__(
        self,
        *,
        enqueue=None,
        goal_reader=None,
        candidates=None,
        settings_provider=None,
    ) -> None:
        self._enqueue = enqueue
        self._goal_reader = goal_reader
        self._candidates = candidates
        self._settings_provider = settings_provider
        self._replanned: dict[str, bool] = {}
        self._evidence_refs: dict[str, list[str]] = {}

    def on_insight_created(self, user_id: str, created: list[dict]) -> None:
        """Insight 创建事件消费者：逐个候选过三门槛，全过才投一次触发。

        异常契约（§6.5）：本监听器内异常一律捕获 + log——不抛出、不影响其他监听器，
        也不影响已完成的 Insight 落库（既有 `notify_insight_created_listeners` 的隔离语义）。
        """
        settings = self._settings()
        for item in list(created or []):
            try:
                self._consider(user_id, item or {}, settings)
            except Exception:
                logger.exception("计划重规划监听异常，已忽略（不影响其他消费者）")

    def enqueue_replan(self, goal_id: str, insight_id: str) -> bool:
        """唯一动作（幂等）：入一个 `TRIGGER_REPLAN` 规划 job。

        返回语义（§9.1 U13）：首次触发 → `True`；重复触发 / 既有 job 层已占用 /
        目标不存在 → `False`。**零其他副作用**：不碰计划内容、不碰 `GoalStatus`、
        不碰工具注册表。
        """
        key = replan_idempotency_key(goal_id, insight_id)
        if not key or key in self._replanned:
            return False
        goal = self._read_goal(goal_id)
        if goal is None:
            return False
        enqueued = self._enqueue_once(goal, insight_id)
        if enqueued:
            self._remember(key, str(goal.id), str(insight_id))
        return enqueued

    def mappable_goal_id(self, user_id: str, scope: str) -> str | None:
        """门槛三：洞察 → 可重规划的活跃目标（按 `scope` 与目标 `domain` / `layer` 匹配）。

        候选集合取自既有只读入口 `goal_repository.list_active_plans`（有活跃计划的目标才是
        重规划对象）；`layer` 只做「层级目标」过滤。匹配不唯一时取**最新创建**的一个
        （`created_at` + `id` 确定性序）——单一动作纪律：一个 Insight 至多产生一个触发。
        """
        domains = SCOPE_GOAL_DOMAINS.get(str(scope or ""), ())
        if not domains:
            return None
        try:
            pairs = self._candidate_pairs(user_id)
        except Exception:
            logger.exception("活跃计划读取失败，本 Insight 不触发重规划：%s", user_id)
            return None
        candidates = [
            goal
            for goal, _plan in pairs
            if goal.domain in domains and goal.layer in PLANNABLE_LAYERS
        ]
        if not candidates:
            return None
        return max(
            candidates, key=lambda goal: (str(goal.created_at or ""), str(goal.id))
        ).id

    def evidence_refs_for(self, goal_id: str) -> tuple[str, ...]:
        """该目标的待注入证据引用（触发它的 Insight id 列表，按触发序去重）。

        装配期据此填充 `RunContext.data["evidence_refs"]` → `PlanContext.evidence_refs`
        → 规划 prompt 与 `GoalPlanRecord.evidence_refs`（§4.2.5 的下游契约）。
        """
        return tuple(self._evidence_refs.get(str(goal_id or ""), ()))

    def reset(self) -> None:
        """清空幂等账与证据账（测试与运维复位）。"""
        self._replanned.clear()
        self._evidence_refs.clear()

    def _consider(self, user_id: str, item: dict, settings) -> None:
        """三门槛顺序判定（任一不过即零动作返回）。"""
        insight_id = str(item.get("insight_id") or "")
        if not insight_id:
            return
        if str(item.get("type") or "") not in PLAN_INFLUENCE_INSIGHT_TYPES:
            return
        if _confidence_of(item) < float(settings.plan_replan_min_confidence):
            return
        goal_id = self.mappable_goal_id(user_id, str(item.get("scope") or ""))
        if goal_id is None:
            return
        self.enqueue_replan(goal_id, insight_id)

    def _read_goal(self, goal_id: str):
        """目标只读（`user_id` 的唯一来源；异常与缺失同处置：不触发）。"""
        if not goal_id:
            return None
        try:
            reader = self._goal_reader or goal_repository.get_goal
            return reader(str(goal_id))
        except Exception:
            logger.exception("目标读取失败，不触发重规划：%s", goal_id)
            return None

    def _candidate_pairs(self, user_id: str) -> list:
        source = self._candidates or goal_repository.list_active_plans
        return list(source(user_id))

    def _enqueue_once(self, goal, insight_id: str) -> bool:
        """**本模块唯一触达规划入队的调用点**（§6.3 D10）。"""
        runner = self._enqueue or goal_planning.enqueue_planning
        try:
            return bool(
                runner(goal.user_id, goal.id, goal_planning.TRIGGER_REPLAN)
            )
        except Exception:
            logger.exception(
                "重规划入队异常，已忽略（goal=%s insight=%s）", goal.id, insight_id
            )
            return False

    def _remember(self, key: str, goal_id: str, insight_id: str) -> None:
        """登记本任务层幂等账与证据账（有界；越界逐出最旧项）。"""
        if len(self._replanned) >= LEDGER_LIMIT:
            self._replanned.pop(next(iter(self._replanned)), None)
        self._replanned[key] = True
        refs = self._evidence_refs.setdefault(goal_id, [])
        if insight_id not in refs:
            refs.append(insight_id)

    def _settings(self):
        provider = self._settings_provider or get_settings
        return provider()


_DEFAULT_LISTENER: PlanningRevisionListener | None = None


def get_revision_listener() -> PlanningRevisionListener:
    """模块级默认监听器（无状态依赖协作面，进程内单例）。"""
    global _DEFAULT_LISTENER  # pylint: disable=global-statement
    if _DEFAULT_LISTENER is None:
        _DEFAULT_LISTENER = PlanningRevisionListener()
    return _DEFAULT_LISTENER


def register_runtime() -> None:
    """编排层入口（`main.lifespan` 调用）：注册第四个 `insight_created` 消费者。

    注册恒发生（子闸已随开关体系删除），与既有三个消费者同款纪律。
    """
    from app.services.reflection import lifecycle as reflection_lifecycle

    reflection_lifecycle.register_insight_created_listener(on_insight_created)


def on_insight_created(user_id: str, created: list[dict]) -> None:
    """注册进 `notify_insight_created_listeners` 的**函数面**（默认监听器的绑定）。"""
    get_revision_listener().on_insight_created(user_id, created)


def enqueue_replan(goal_id: str, insight_id: str) -> bool:
    """幂等入队入口（默认监听器）。"""
    return get_revision_listener().enqueue_replan(goal_id, insight_id)


def evidence_refs_for(goal_id: str) -> tuple[str, ...]:
    """该目标的待注入证据引用（默认监听器）。"""
    return get_revision_listener().evidence_refs_for(goal_id)


def reset_revision_state() -> None:
    """清空默认监听器的幂等账与证据账（测试与运维复位）。"""
    get_revision_listener().reset()


def replan_idempotency_key(goal_id: str, insight_id: str) -> str:
    """幂等键：`plan_replan:{goal_id}:{insight_id}`（缺任一 id → 空串，调用方据此短路）。"""
    if not goal_id or not insight_id:
        return ""
    return REPLAN_IDEMPOTENCY_TEMPLATE.format(
        goal_id=str(goal_id), insight_id=str(insight_id)
    )


def dominant_revision_reason(reasons) -> str | None:
    """Q8 归一：同时命中的多个理由码 → 一个理由码（固定优先序，纯函数、零 IO）。

    未命中任何已知理由码 → `None`（不猜测、不兜底）。
    """
    hits = {str(reason) for reason in (reasons or ()) if reason}
    for reason in REVISION_REASON_PRIORITY:
        if reason in hits:
            return reason
    return None


def plan_revision_record(
    plan, insight_ids, *, reason: str = REASON_INSIGHT_DRIVEN, at: datetime | None = None
) -> PlanRevision:
    """修订记录（§4.2.5）：把触发本轮的 Insight id 带进 `PlanRevision.evidence_refs`。

    `kept_steps` 取既有 `PlanRevisionPolicy.kept_steps`（已完成步骤在新版本中复用，G-RETRY），
    本模块不另立保留步口径。
    """
    refs = [str(item) for item in (insight_ids or ()) if item]
    return PlanRevision(
        from_version=int(plan.version),
        to_version=int(plan.version) + 1,
        reason=reason,
        trigger_source=reason,
        at=at or datetime.now(),
        evidence_refs=refs,
        kept_steps=plan_revision.PlanRevisionPolicy.kept_steps(plan),
    )


def _confidence_of(item: dict) -> float:
    try:
        return float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0
