"""V2.5.0 PLAN-005 计划执行桥（Task Detail §4.1.3 / §4.3.4 / §4.3.6 / §6.2）。

architecture.md 对应章节：§3.7（PlanExecutorBridge）、§6.4（执行流程）、§8.4（接口）。

本模块回答「这一步怎么变成一次 Action，以及结果怎么回到计划上」。**只做翻译与回收**：
不执行工具（**唯一执行入口**是 `action_engine.run_action_planning`）、不做退避（退避数学只有
一份，在 Action 层 `_process_due_retries`）、不落库（落库由调用方经
`goal_repository.update_plan_progress` 统一完成）。

```text
PlanScheduler.current_step(plan) → PlanStepSpec
        ▼  to_intent（翻译）
ActionIntent{action_type, params, dedupe_key=plan:{goal}:{ver}:{idx}, confidence="confident"}
        ▼  execute_step（两道防御性断言 + 委托既有编排器）
action_engine.run_action_planning（六闸门 → 装配 → ToolExecutor 五段 → integrate_result）
        ▼  _outcome（回收 + 白名单裁剪）
PlanStepOutcome{status, action_id, tool_id, failure_kind, effects, observations, duration_ms}
        ▼  reconcile（回填内存副本）
PlanStepSpec{status, attempt_count, last_attempt_at, failure_note}
```

两道**防御性断言**（§6.3，不是第二次决策：不改变计划内容，只防「规划到执行之间世界 /
关系 / 时段变化」）

| # | 断言 | 触发条件 | 结果 |
|---|---|---|---|
| A1 | 就绪复核 | `PlanScheduler.ready_steps(plan)` 不含该步 | `skipped`，**不执行** |
| A2 | 面复核 | `step.tool_id` 不在执行期重解析的工具面上 | `blocked` + `unavailable`，**不执行** |

双层重试的边界（B5 关闭点，§4.3.5）

- Action 层管**技术性重试**（`failure_kind ∈ RETRYABLE_FAILURES` 的退避重试，本模块只观察
  其终态）；Plan 层管**业务性放弃**（`v25_plan_step_max_attempts`）。
- `attempt_count` **只在 Action 落终态**（`succeeded` / `failed`，取值即 PLAN-002 的
  `PLAN_STEP_ATTEMPT_INCREMENT_STATUSES`）时递增——与 V9 的 `executing` 中间态解耦（D7/U8）。
- 本模块**零等待、零退避、零 `next_retry_at` 计算**（D8）。

与 Task Detail 的三处实现核对（均按真实源码冻结，已在测试留痕）

1. **`to_intent` 的 `params` 不做 `normalize_core_params` 变换**：§6.4 Step ③ 记
   `params=normalize_core_params(step.params)`，而该函数会**字符串化**全部取值并**丢弃**
   `None` / 空串。执行期 `ParamValidator.validate` 是参数校验的唯一权威（§5.2 校验分层），
   提前字符串化会把声明为 `default=None` 的必填参数变成「缺参」、把数值型参数变成字符串——
   即「规划期替执行期做了第二次加工」。故本实现的 `params` **原样透传** `step.params`；
   `normalize_core_params` 只用于生成**审计摘要**（进 `ActionIntent.evidence`，随
   `action_records.intent` 落库），保留「同输入同输出」的确定性而不改参数语义。
2. **`timeout` 以 `status="failed" + failure_kind="timeout"` 表达**：§4.3.4 的 `timeout` 行
   映射到 `ActionRecord.status="failed"`；若把 `PlanStepOutcome.status` 也记为 `timeout`，
   则 `PLAN_STEP_ATTEMPT_INCREMENT_STATUSES`（只有 `succeeded` / `failed`）会**漏计**
   `attempt_count`（违反 D7）。可重试语义由 `failure_kind` 承载（与 Action 层
   `RETRYABLE_FAILURES` 同源），信息零丢失。
3. **A2 的面复核用执行期时刻重解析**：§6.3 记 `ToolSurfaceResolver.resolve(...)`；本实现按
   `RUN_KIND_AUTONOMOUS_TICK` + 执行期 `now` 重解析（同一 `ToolSurfaceResolver`，零新增面规则），
   并把 `ctx.world` 的规划期事实注入世界维度——时段类剔除因此对「规划到执行之间跨时段」有效。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.application.action_engine import run_action_planning
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.character.asuna.action import ACTION_CAPABILITY_MAP
from app.core.settings import get_settings
from app.models.action import ACTION_TYPES, ActionIntent, normalize_core_params
from app.models.plan import (
    PLAN_STEP_ACTION_CONFIDENCE,
    PLAN_STEP_ACTION_SOURCE,
    PLAN_STEP_ATTEMPT_INCREMENT_STATUSES,
    PLAN_STEP_DEDUPE_KEY_TEMPLATE,
    PlanStepOutcome,
    PlanStepOutcomeStatus,
)
from app.models.tool import TOOL_FAILURE_KIND_VALUES
from app.repositories import conversation_repository
from app.services.planning import scheduler as plan_scheduler
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, get_tool_registry
from app.services.tool.surface import ToolSurfaceResolver
from app.services.tool.world_context import apply_world_facts

logger = logging.getLogger(__name__)

EVIDENCE_DIGEST_BUDGET = 240

STEP_STATUS_IN_PROGRESS = plan_scheduler.STEP_STATUS_IN_PROGRESS
STEP_STATUS_FAILED = plan_scheduler.STEP_STATUS_FAILED

OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_FAILED = "failed"
OUTCOME_BLOCKED = "blocked"
OUTCOME_SKIPPED = "skipped"
OUTCOME_HOLD = "hold"

KIND_UNAVAILABLE = "unavailable"
KIND_DENIED = "denied"
KIND_INVALID = "invalid"
KIND_TIMEOUT = "timeout"
KIND_PERMANENT = "permanent"
KIND_TRANSIENT = "transient"

BLOCKING_FAILURE_KINDS: tuple[str, ...] = (KIND_DENIED, KIND_INVALID)
"""按 §4.3.6 直接判 `failed` 的两类（授权拒绝非瞬时；参数非法需换参数/重规划），**不重试**。"""

BLOCKED_STEP_STATUS: dict[str | None, str] = {
    KIND_DENIED: STEP_STATUS_FAILED,
    KIND_INVALID: STEP_STATUS_FAILED,
    KIND_UNAVAILABLE: STEP_STATUS_IN_PROGRESS,
    None: STEP_STATUS_IN_PROGRESS,
}
"""`blocked` 四类 × 步骤状态（§4.3.6 判定树的逐行落地）。

`permission_denied` → `failed`（不重试、不得自动绕过）；`invalid_params` → `failed`（permanent）；
`pending_confirmation`（`failure_kind=None`）→ `in_progress`（等既有确认流
`run_confirmation_round`）；`capability_unavailable` → `in_progress`（等下一 tick 复面，
持续 `off_surface` 由 `PlanRevisionPolicy` 触发换工具重规划）。
"""

DEFAULT_BLOCKED_STEP_STATUS = STEP_STATUS_IN_PROGRESS

GATE_REASON_OUTCOMES: dict[str, tuple[PlanStepOutcomeStatus, str | None]] = {
    "capability_unavailable": (OUTCOME_BLOCKED, KIND_UNAVAILABLE),
    "disabled": (OUTCOME_BLOCKED, KIND_UNAVAILABLE),
    "permission_denied": (OUTCOME_BLOCKED, KIND_DENIED),
    "invalid_params": (OUTCOME_BLOCKED, KIND_INVALID),
    "ambiguous_params": (OUTCOME_BLOCKED, KIND_INVALID),
    "target_not_found": (OUTCOME_BLOCKED, KIND_INVALID),
    "pending_confirmation": (OUTCOME_BLOCKED, None),
    "expired": (OUTCOME_FAILED, KIND_PERMANENT),
    "duplicate": (OUTCOME_HOLD, None),
    "quota_exceeded": (OUTCOME_HOLD, None),
    "effect_already_satisfied": (OUTCOME_HOLD, None),
}
"""六闸门拒绝理由 → `PlanStepOutcome` 的归一表（§4.3.4；**不新增** `GATE_REASONS` 取值）。

四类 `blocked` 取 §4.3.4 表列的四个理由；其余理由按「是否执行了动作」归类：
未执行但可等（`duplicate` / `quota_exceeded` / `effect_already_satisfied`）→ `hold`（留在计划中
等下一 tick），已过期（`expired`）→ `failed`（本步放弃），未列出的理由取 `hold` 保守不动。
"""

DEFAULT_GATE_OUTCOME: tuple[PlanStepOutcomeStatus, str | None] = (OUTCOME_HOLD, None)

__all__ = [
    "BLOCKED_STEP_STATUS",
    "BLOCKING_FAILURE_KINDS",
    "DEFAULT_BLOCKED_STEP_STATUS",
    "DEFAULT_GATE_OUTCOME",
    "GATE_REASON_OUTCOMES",
    "KIND_DENIED",
    "KIND_INVALID",
    "KIND_PERMANENT",
    "KIND_TIMEOUT",
    "KIND_UNAVAILABLE",
    "OUTCOME_BLOCKED",
    "OUTCOME_FAILED",
    "OUTCOME_HOLD",
    "OUTCOME_SKIPPED",
    "OUTCOME_SUCCEEDED",
    "PlanBridgeDefect",
    "PlanExecutorBridge",
]


class PlanBridgeDefect(ValueError):
    """实现缺陷（**不是业务结果**）：反查不到 `action_type`、步序号错配等。

    与 §6.6 同款纪律：编程缺陷上抛，不静默构造（静默构造会把缺陷伪装成一次执行尝试）。
    """


class PlanExecutorBridge:
    """步骤 → `ActionIntent` → Action → `PlanStepOutcome` 的翻译与回收。

    `runner` / `session_resolver` / `registry` / `settings` 均可注入，仅影响测试与后续任务
    的复用场景；缺省即既有实现（`action_engine.run_action_planning` / 最近会话 / 工具系统
    单例 / 全局设置），语义不变。
    """

    def __init__(
        self,
        *,
        runner=None,
        session_resolver=None,
        registry: ToolRegistry | None = None,
        settings=None,
    ) -> None:
        self._runner = runner
        self._session_resolver = session_resolver
        self._registry_override = registry
        self._settings_override = settings

    def to_intent(self, goal, plan, step, ctx) -> ActionIntent:  # pylint: disable=unused-argument
        """`PlanStepSpec` → `ActionIntent`（确定性：同输入同输出，含步级幂等键）。

        `ctx` 是 §6.2 冻结签名的一部分（执行期面复核的输入面），本方法不消费它——翻译只用
        步骤自身与计划的版本号，避免把执行期状态混进幂等键。

        禁止空 `action_type`：`step.capability` 是 PLAN-004 已校验 ∈ `ACTION_TYPES` 的能力名
        （即 `action_type` 本身）；若上游给了别的能力名，则按既有 `ACTION_CAPABILITY_MAP`
        反查，**唯一命中**才接受，否则抛 `PlanBridgeDefect`。
        """
        params = dict(step.params or {})
        return ActionIntent(
            action_type=_action_type(step),
            confidence=PLAN_STEP_ACTION_CONFIDENCE,
            params=params,
            dedupe_key=_dedupe_key(goal, plan, step),
            evidence=_evidence(step, params),
        )

    async def execute_step(self, goal, plan, step, ctx) -> PlanStepOutcome:
        """执行一步（A1 → A2 → 委托既有编排器 → 结果归一）。**唯一执行入口**。

        落库由调用方完成（本方法零 `goal_repository` 调用）：`plan.sub_goals` 的替换与
        `goal_repository.update_plan_progress(plan.id, sub_goals)` 属观测/编排侧。
        """
        at = _moment(ctx)
        if not _is_ready(plan, step):
            return _plain_outcome(step, OUTCOME_SKIPPED, at)
        if not self._on_surface(goal, step, ctx, at):
            return _plain_outcome(
                step, OUTCOME_BLOCKED, at, failure_kind=KIND_UNAVAILABLE
            )
        intent = self.to_intent(goal, plan, step, ctx)
        try:
            record = await self._dispatch(goal, intent)
        except Exception:
            logger.exception(
                "计划步骤执行异常，判为永久失败（goal=%s step=%s）", goal.id, step.index
            )
            return _plain_outcome(
                step, OUTCOME_FAILED, at, failure_kind=KIND_PERMANENT
            )
        return _normalize(step, record, at)

    def reconcile(self, outcome: PlanStepOutcome, step, *, max_attempts: int | None = None):
        """结果回填（**只写内存副本**，D6）：`status` / `attempt_count` / `last_attempt_at` / `failure_note`。

        `attempt_count` 只在 Action 终态递增（D7）；`last_attempt_at` 只在**确实产生了
        Action 记录**时推进（`skipped` 无 Action，故不动冷却窗口）。`done` 不在此处落——
        唯一推进后继的状态由判据达成（`observe`）决定（§4.3.1）。
        """
        if outcome.step_index != step.index:
            raise PlanBridgeDefect(
                f"结果步序号 {outcome.step_index} 与步骤 {step.index} 不匹配"
            )
        limit = _step_max_attempts(max_attempts, self._settings())
        attempt_count = step.attempt_count + (
            1 if outcome.status in PLAN_STEP_ATTEMPT_INCREMENT_STATUSES else 0
        )
        status = _reconciled_status(outcome, step, attempt_count, limit)
        return step.model_copy(
            update={
                "status": status,
                "attempt_count": attempt_count,
                "last_attempt_at": (
                    outcome.at if outcome.action_id else step.last_attempt_at
                ),
                "failure_note": _failure_note(outcome, attempt_count, status),
            }
        )

    async def _dispatch(self, goal, intent: ActionIntent):
        """既有编排器入口（唯一）：`source="autonomy"` 使额度与冷却结构性生效（§5.1）。

        V2.6.0：总闸 on 时经 ActionManager.create(source=plan) + execute，保持
        PlanStep 与 Action 1:1（不新建第二条记录）。
        """
        settings = get_settings()
        if getattr(settings, "v26_action_execution_enabled", False):
            from app.repositories import action_repository
            from app.services.action import manager as action_manager

            action = action_manager.create(
                user_id=goal.user_id,
                action_type=intent.action_type,
                params=dict(intent.params or {}),
                source="plan",
                session_id=self._session_id(goal.user_id),
                goal_id=goal.id,
                intent=intent,
            )
            await action_manager.execute(action.id)
            return action_repository.get_record(action.id)
        runner = run_action_planning if self._runner is None else self._runner
        return await runner(
            goal.user_id,
            intent,
            session_id=self._session_id(goal.user_id),
            goal_id=goal.id,
            source=PLAN_STEP_ACTION_SOURCE,
        )

    def _session_id(self, user_id: str) -> str | None:
        """会话关联：与既有自治路径同源（最近会话），失败即降级为 `None`（不阻塞执行）。"""
        try:
            if self._session_resolver is not None:
                return self._session_resolver(user_id)
            conversation = conversation_repository.get_latest_for_user(user_id)
        except Exception:
            logger.exception("最近会话读取失败，计划步骤执行不带会话：%s", user_id)
            return None
        return None if conversation is None else conversation.id

    def _on_surface(self, goal, step, ctx, at: datetime) -> bool:
        """A2 面复核（§6.3）：按执行期时刻重解析工具面，不在面上即 `blocked`。

        无 `tool_id` 的步骤（纯观测 / 绑定子闸 off）不做面判定：此时工具选择属执行期
        `ToolSelector`，本模块不预判（避免与执行期分歧）。
        """
        tool_id = str(step.tool_id or "")
        if not tool_id:
            return True
        settings = self._settings()
        registry = (
            self._registry_override
            if self._registry_override is not None
            else get_tool_registry()
        )
        surface = ToolSurfaceResolver(registry, settings).resolve(
            RUN_KIND_AUTONOMOUS_TICK,
            _surface_context(goal.user_id, ctx, at, settings),
        )
        return tool_id in set(surface.tool_ids)

    def _settings(self):
        return get_settings() if self._settings_override is None else self._settings_override


def _action_type(step) -> str:
    """能力名 → `action_type`：`ACTION_TYPES` 直接命中优先；否则按既有映射**唯一**反查。"""
    capability = str(step.capability or "")
    if capability in ACTION_TYPES:
        return capability
    matched = [
        action_type
        for action_type, mapping in ACTION_CAPABILITY_MAP.items()
        if mapping[0] == capability
    ]
    if len(matched) != 1:
        raise PlanBridgeDefect(
            f"步骤 {step.index} 的能力 {capability!r} 无法反查唯一的 action_type"
            f"（命中 {matched}）"
        )
    return matched[0]


def _dedupe_key(goal, plan, step) -> str:
    """步级幂等键（§4.4 幂等锚点）：按 `PLAN_STEP_DEDUPE_KEY_TEMPLATE`（`models/plan.py` 的
    **唯一字面声明处**）渲染为 `plan:<goal_id>:<version>:<index>`，确定性且跨版本可区分。"""
    return PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(
        goal_id=goal.id, version=plan.version, index=step.index
    )


def _evidence(step, params: dict) -> str:
    """审计摘要（进 `action_records.intent.evidence`）：可读理由 + 规范化参数摘要（有界）。"""
    digest = normalize_core_params(params)
    rendered = json.dumps(digest, ensure_ascii=False, sort_keys=True)
    return f"计划步骤 {step.index}：{step.description}；参数摘要 {rendered}"[
        :EVIDENCE_DIGEST_BUDGET
    ]


def _is_ready(plan, step) -> bool:
    """A1 就绪复核（§6.3）：同一 `(index)` 在就绪集内才可执行。"""
    return any(
        ready.index == step.index for ready in plan_scheduler.PlanScheduler.ready_steps(plan)
    )


def _surface_context(user_id: str, ctx, at: datetime, settings) -> ToolContext:
    """面复核用的 `ToolContext`：执行期时刻 + 规划期世界事实（预读注入，零额外 IO）。"""
    base = ToolContext(
        user_id=user_id,
        now=at,
        settings=settings,
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        source=PLAN_STEP_ACTION_SOURCE,
    )
    world = getattr(ctx, "world", None)
    if isinstance(world, dict) and world:
        return apply_world_facts(base, {"world": world})
    return base


def _moment(ctx) -> datetime:
    return getattr(ctx, "now", None) or datetime.now()


def _step_max_attempts(explicit: int | None, settings) -> int:
    """Plan 层尝试上限：显式注入优先，其次 `v25_plan_step_max_attempts`（非非负整数按 0 处理）。"""
    value = settings.v25_plan_step_max_attempts if explicit is None else explicit
    return value if isinstance(value, int) and value >= 0 else 0


def _plain_outcome(
    step, status: PlanStepOutcomeStatus, at: datetime, *, failure_kind: str | None = None
) -> PlanStepOutcome:
    """未产生 Action 的归一结果（A1 / A2 / 执行期异常）。"""
    return PlanStepOutcome(
        step_index=step.index,
        status=status,
        at=at,
        tool_id=str(step.tool_id or ""),
        failure_kind=failure_kind,
    )


def _normalize(step, record, at: datetime) -> PlanStepOutcome:
    """`ActionRecord` → `PlanStepOutcome`（§4.3.4 映射 + `observations` 白名单裁剪）。

    `record is None`（`action_enabled` off，编排器未建记录）→ `hold`：本步没被执行，也不该
    被判失败（既有的行动总闸语义）。
    """
    if record is None:
        return _plain_outcome(step, OUTCOME_HOLD, at)
    step_dict = record.steps[0] if record.steps else {}
    result = dict(step_dict.get("result") or {})
    status, failure_kind = _record_outcome(record, result)
    return PlanStepOutcome(
        step_index=step.index,
        status=status,
        at=at,
        action_id=record.id,
        tool_id=str(step_dict.get("tool_id") or step.tool_id or ""),
        failure_kind=_failure_kind(failure_kind),
        attempt=int(record.attempt or 0),
        effects=_effects(result),
        observations=_observations(result, step),
        duration_ms=_duration_ms(step_dict),
    )


def _record_outcome(record, result: dict) -> tuple[PlanStepOutcomeStatus, str | None]:
    """动作记录状态 → 步骤结果（§4.3.4 / §4.3.6 的归一，逐行可对照）。"""
    if record.status == OUTCOME_FAILED:
        kind = _result_kind(result)
        return OUTCOME_FAILED, (
            KIND_TIMEOUT if kind == KIND_TIMEOUT else (kind or KIND_PERMANENT)
        )
    if record.status == "cancelled":
        return GATE_REASON_OUTCOMES.get(
            str(record.gate_reason or ""), DEFAULT_GATE_OUTCOME
        )
    if record.status == OUTCOME_SUCCEEDED:
        return OUTCOME_SUCCEEDED, None
    if record.status == "executing":
        return OUTCOME_HOLD, _result_kind(result)
    if record.gate_reason == "pending_confirmation":
        return OUTCOME_BLOCKED, None
    return OUTCOME_HOLD, None


def _result_kind(result: dict) -> str | None:
    """`ToolResult.failure_kind` 优先，`payload.failure_kind` 兜底（V2.4.0 兼容双写）。"""
    payload = result.get("payload") or {}
    kind = result.get("failure_kind") or payload.get("failure_kind")
    return None if kind is None else str(kind)


def _failure_kind(kind: str | None) -> str | None:
    """值域收敛：越出既有 `TOOL_FAILURE_KINDS`（6 值）一律记 `permanent`（**不新增取值**）。"""
    if kind in TOOL_FAILURE_KIND_VALUES:
        return kind
    return None if kind is None else KIND_PERMANENT


def _effects(result: dict) -> list[dict]:
    """`ToolResult.effects` → `{kind, ref, reversible}` 投影（§4.2.2）。"""
    effects = result.get("effects")
    if not isinstance(effects, list):
        return []
    return [
        {
            "kind": str(effect.get("kind")),
            "ref": str(effect.get("ref") or ""),
            "reversible": bool(effect.get("reversible")),
        }
        for effect in effects
        if isinstance(effect, dict) and effect.get("kind")
    ]


def _observations(result: dict, step) -> dict:
    """`observations` **白名单裁剪**（§4.2.2 硬纪律）：未在 `observation_keys` 声明的键一律不可见。"""
    raw = result.get("observations")
    if not isinstance(raw, dict):
        return {}
    return {
        key: raw[key] for key in step.observation_keys if key in raw
    }


def _duration_ms(step_dict: dict) -> int | None:
    """步骤耗时：`steps[].duration_ms` 优先，`ToolResult.usage.duration_ms` 兜底（缺省即 `None`）。"""
    value = step_dict.get("duration_ms")
    if value is None:
        usage = dict((step_dict.get("result") or {}).get("usage") or {})
        value = usage.get("duration_ms")
    return value if isinstance(value, int) else None


def _reconciled_status(
    outcome: PlanStepOutcome, step, attempt_count: int, max_attempts: int
) -> str:
    """结果 → 步骤状态（§4.3.6 / §5.5）：`done` 不在此处落（判据达成才算），`hold` 留在 `in_progress`。"""
    if outcome.status == OUTCOME_FAILED:
        return STEP_STATUS_FAILED if attempt_count >= max_attempts else STEP_STATUS_IN_PROGRESS
    if outcome.status == OUTCOME_BLOCKED:
        return BLOCKED_STEP_STATUS.get(
            outcome.failure_kind, DEFAULT_BLOCKED_STEP_STATUS
        )
    if outcome.status == OUTCOME_SKIPPED:
        return step.status
    return STEP_STATUS_IN_PROGRESS


def _failure_note(outcome: PlanStepOutcome, attempt_count: int, status: str) -> str | None:
    """失败注记：只在本步被判失败时书写（其余情形返回 `None`，即清空上次注记）。"""
    if status != STEP_STATUS_FAILED:
        return None
    kind = outcome.failure_kind or OUTCOME_FAILED
    return (
        f"{kind} 第 {attempt_count} 次尝试失败（action={outcome.action_id or '-'}）"
    )[:200]
