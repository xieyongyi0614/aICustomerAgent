"""Agent Loop Core（RT-006）：显式六段认知循环状态机。

把「按 Profile 线性执行阶段」升级为**段级显式**的六段循环
（Observe → Reason → Plan → Act → Reflect → Update），只显式化与契约化，不重造器官：

- **D1 环节 vs 实现**：六段是「环节」，既有阶段名是「实现」；`STAGE_TO_PHASE` 是唯一映射表
  （一环节可含多阶段），既有阶段名不重命名 → 零回归。
- **D2 唯一声明处**：段序列仍**只**来自 `profiles.py`（`resolve_stages(spec)`），
  本模块零内联段序列——「无第二套 Agent Pipeline」的红线。
- **D3 fail-closed**：未注册阶段抛 `ValueError`，注册表与实现不一致必须暴露。
- **D4 并发语义**：前台不加 per-user 写锁，后台保留 `get_user_write_lock`（既有语义不变）。
- **D5 不切换生产路径**：`run()` 供测试与 RT-015 / RT-016 调用；生产路径仍是
  `controller.run_autonomous_cycle` / `chat_pipeline`（RT-006 零收编）。
- **D6 段方法只委派**：段本体归 RT-007 ~ RT-012；本任务段方法只委派既有阶段实现。

驱动顺序：`run()` 按 `resolve_stages` 的**声明顺序**逐段驱动（AC1：顺序零改动，
避免按环节重排既有 Profile 的段序）；六段方法（`observe` / `reason` / `plan` /
`act` / `reflect` / `update`）是**段级实现的挂载点**，按环节取段，供 RT-007 ~ RT-012
替换段本体与做段级单测。段的六段归属始终由 `stage_phase` 裁决，段级错误类型由
`ERROR_KIND_BY_PHASE` 裁决。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.application import agent_state_assembler
from app.core import clock as logical_clock
from app.application.agent_runtime import controller, events as event_bus, profiles
from app.application.agent_runtime import state as state_manager
from app.application.agent_runtime.stages import act as stages_act
from app.application.agent_runtime.stages import observe as observe_stage
from app.application.agent_runtime.stages import plan as stages_plan
from app.application.agent_runtime.stages import reflect as stages_reflect
from app.application.agent_runtime.stages import update as stages_update
from app.application.agent_runtime.stages import reason as stages_reason
from app.application.agent_runtime.contracts import (
    ErrorKind,
    RunResult,
    RuntimeFailure,
    RuntimeInput,
    SessionContext,
    terminal_status_for,
)
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
    TERMINAL_ABORTED,
    TERMINAL_DEGRADED,
    TERMINAL_DONE,
    RunContext,
)
from app.application.agent_runtime.profiles import ProfileSpec
from app.application.life_loop_context import memory_digest_var
from app.core.settings import get_settings
from app.services.life import budget as life_loop_budget

logger = logging.getLogger(__name__)

PHASE_OBSERVE = "observe"
PHASE_REASON = "reason"
PHASE_PLAN = "plan"
PHASE_ACT = "act"
PHASE_REFLECT = "reflect"
PHASE_UPDATE = "update"

PHASES: tuple[str, ...] = (
    PHASE_OBSERVE,
    PHASE_REASON,
    PHASE_PLAN,
    PHASE_ACT,
    PHASE_REFLECT,
    PHASE_UPDATE,
)

STATE_PREP_STAGES: frozenset[str] = frozenset({"state_update", "state_snapshot"})
"""决策前状态准备实现名（L-2）：归 Reason 环节，**不是** Update 回写段。"""

STAGE_TO_PHASE: dict[str, str] = {
    "perception": PHASE_OBSERVE,
    "context_assembly": PHASE_OBSERVE,
    "turn_decisions": PHASE_REASON,
    "mode_stabilize": PHASE_REASON,
    "scene_resolve": PHASE_REASON,
    "behavior_resolve": PHASE_REASON,
    "goal_check": PHASE_REASON,
    "goal_stack": PHASE_REASON,
    "goal_supply": PHASE_REASON,
    "goal_advance": PHASE_REASON,
    "memory_retrieval": PHASE_REASON,
    "decision": PHASE_REASON,
    "action_planning": PHASE_ACT,
    "reply_generation": PHASE_ACT,
    "reflection_check": PHASE_REFLECT,
    "record_handoff": PHASE_UPDATE,
    "world_experience": PHASE_UPDATE,
    "event_pregate": PHASE_UPDATE,
}
STAGE_TO_PHASE.update({name: PHASE_REASON for name in STATE_PREP_STAGES})

OPTIONAL_PHASES: frozenset[str] = frozenset({PHASE_PLAN, PHASE_REFLECT})

ERROR_KIND_BY_PHASE: dict[str, ErrorKind] = {
    PHASE_OBSERVE: "perception",
    PHASE_REASON: "decision",
    PHASE_PLAN: "planning",
    PHASE_ACT: "execution",
    PHASE_REFLECT: "feedback",
    PHASE_UPDATE: "state",
}

TRACE_STAGE = "runtime_stage"

SIX_STAGE_LOOP_SETTING = "runtime_six_stage_loop_enabled"
SHADOW_STAGE_METHODS = True
"""默认生产循环仍是 Profile 阶段序列；`runtime_six_stage_loop_enabled` 打开后 `run()` 走六段。"""

SIX_STAGE_SEQUENCE: tuple[str, ...] = (
    PHASE_OBSERVE,
    PHASE_REASON,
    PHASE_PLAN,
    PHASE_ACT,
    PHASE_REFLECT,
    PHASE_UPDATE,
)
SIX_STAGE_CRITICAL: frozenset[str] = frozenset(
    {PHASE_OBSERVE, PHASE_REASON, PHASE_ACT, PHASE_UPDATE}
)


def stage_phase(name: str) -> str:
    """阶段名 → 六段环节；未注册阶段 fail-closed（裁决 D3）。"""
    try:
        return STAGE_TO_PHASE[name]
    except KeyError as exc:
        raise ValueError(f"未注册的阶段：{name}") from exc


def enabled_optional_phases() -> frozenset[str]:
    """`runtime_loop_optional_stages`（csv）→ 已启用的可选环节集合。"""
    raw = get_settings().runtime_loop_optional_stages or ""
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def resolve_stages(spec: ProfileSpec) -> tuple[str, ...]:
    """可选段裁决（Q4）：只过滤**被 Profile 声明为可选**的段，其余逐元素保留。

    可选段必须同时满足三条才可被剔除：① 段在 `spec.optional_stages` 中（Profile 显式让出）；
    ② 段的环节 ∈ `OPTIONAL_PHASES`（只有 Plan / Reflect 是可选环节）；
    ③ 该环节未出现在 `runtime_loop_optional_stages` 中。

    三 Profile 默认 `optional_stages` 为空 → 返回值恒等于 `spec.stages`（零行为变化）。
    """
    enabled = enabled_optional_phases()
    return tuple(name for name in spec.stages if not _optional_skipped(name, spec, enabled))


def _optional_skipped(name: str, spec: ProfileSpec, enabled: frozenset[str]) -> bool:
    if name not in spec.optional_stages:
        return False
    phase = stage_phase(name)
    if phase not in OPTIONAL_PHASES:
        return False
    return phase not in enabled


@dataclass(frozen=True, slots=True)
class StageContext:
    """段执行上下文（RT-007 ~ RT-012 的实现挂载面）。

    `inputs` 是段间中间值通道（Observation / Intention / Plan / ActionResult /
    Insight / Feedback）：一律值对象，只落 Trace **不落业务表**。
    """

    stage: str
    phase: str
    run_context: RunContext
    user_id: str | None
    now: datetime
    llm: Any = None
    spec: ProfileSpec | None = None
    inputs: Mapping[str, Any] = field(default_factory=dict)


StageRunner = Callable[[StageContext], Awaitable[Any]]


def _life_loop_runner(stage: str) -> StageRunner:
    """既有阶段本体的委派（实现仍只有 `controller` 的注册表一处）。"""

    async def _run(context: StageContext) -> Any:
        factory = controller._autonomous_stage_runner(  # pylint: disable=protected-access
            stage, context.user_id, context.run_context, context.now
        )
        return await factory()

    return _run


def _plain_stage_names() -> tuple[str, ...]:
    """有纯阶段本体的自治段：LLM 能力段带预算闸，其门控归调用方（RT-016）。"""
    spec = profiles.get_profile(RUN_KIND_AUTONOMOUS_TICK)
    return tuple(name for name in spec.stages if name not in spec.llm_capable)


STAGE_RUNNERS: dict[str, StageRunner] = {
    name: _life_loop_runner(name) for name in _plain_stage_names()
}
_STAGE_RUNNERS_LOCK = threading.Lock()


def register_stage_runner(name: str, runner: StageRunner) -> None:
    """注册段实现（代码静态注册，沿 `ToolRegistry` 模式）；重复注册 fail-closed。"""
    stage_phase(name)
    with _STAGE_RUNNERS_LOCK:
        if name in STAGE_RUNNERS:
            raise ValueError(f"阶段实现已注册：{name}")
        STAGE_RUNNERS[name] = runner


def snapshot_stage_runners() -> dict[str, StageRunner]:
    with _STAGE_RUNNERS_LOCK:
        return dict(STAGE_RUNNERS)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class AgentLoop:
    """一次 Run 的六段认知循环；段序列来自 Profile，段本体来自注册表。"""

    def __init__(
        self,
        spec: ProfileSpec,
        *,
        user_id: str | None,
        run: RunContext,
        llm: Any = None,
        now: datetime | None = None,
        trace: Any = None,
        registry: Mapping[str, StageRunner] | None = None,
        promote_degraded: bool = True,
    ) -> None:
        self.spec = spec
        self.user_id = user_id
        self.run_context = run
        self.llm = llm
        self.now = now or datetime.now()
        self.trace = trace
        self.stages = resolve_stages(spec)
        self.runtime_input: RuntimeInput | None = None
        self.session_context: SessionContext | None = None
        self.runtime_context: Any = None
        self.observation: Any = None
        self.intention: Any = None
        self.plan_value: Any = None
        self.act_outcome: Any = None
        self.reflect_outcome: Any = None
        self.feedback: Any = None
        self._registry: Mapping[str, StageRunner] = (
            snapshot_stage_runners() if registry is None else registry
        )
        self._promote_degraded = promote_degraded
        self._steps: list[dict] = []
        self._status: str = TERMINAL_DONE
        self._session_id: str | None = None
        self._budget = None

    # ---- 段查询面 -------------------------------------------------------

    def stage_runner(self, name: str) -> StageRunner:
        try:
            return self._registry[name]
        except KeyError as exc:
            raise ValueError(f"未注册的阶段实现：{name}") from exc

    def stages_in(self, phase: str) -> tuple[str, ...]:
        """本 Run 中归属该环节的段（按声明顺序）。"""
        return tuple(name for name in self.stages if stage_phase(name) == phase)

    def phase_sequence(self) -> tuple[str, ...]:
        """本 Run 实际经过的六段环节（按段序列出现顺序）。"""
        seen: list[str] = []
        for name in self.stages:
            phase = stage_phase(name)
            if phase not in seen:
                seen.append(phase)
        return tuple(seen)

    # ---- 段执行原语 -----------------------------------------------------

    def _coro_factory(
        self, name: str, phase: str, inputs: Mapping[str, Any] | None
    ) -> Callable[[], Awaitable[Any]]:
        runner = self.stage_runner(name)
        context = StageContext(
            stage=name,
            phase=phase,
            run_context=self.run_context,
            user_id=self.user_id,
            now=self.now,
            llm=self.llm,
            spec=self.spec,
            inputs=dict(inputs or {}),
        )
        return lambda: runner(context)

    def _record_step(self, entry: dict) -> None:
        controller.append_step(self.run_context, self._steps, entry)

    def _emit_stage(self, name: str, phase: str, entry: dict) -> None:
        event_bus.emit_stage_completed(
            self.run_context.run_id,
            self._session_id,
            name,
            duration_ms=float(entry.get("duration_ms") or 0.0),
            status=str(entry.get("status") or "ok"),
            correlation_id=self.run_context.run_id,
            payload={"phase": phase, "error": entry.get("error")},
            trace=self.trace,
        )

    def _on_failure(self, failure: RuntimeFailure) -> None:
        if terminal_status_for(failure) == TERMINAL_DEGRADED:
            self.run_context.degraded = True
        if self.trace is not None:
            self.trace.record(
                TRACE_STAGE,
                0.0,
                status="error",
                stage=failure.stage,
                run_id=failure.run_id,
                kind=failure.kind,
                recoverable=failure.recoverable,
            )

    async def _run_stage(
        self,
        name: str,
        phase: str,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        critical: bool,
    ) -> dict:
        """段执行原语：计时 + 异常归一 + 降级裁决 + `loop_runs.steps` 落账。

        记账口径与 `controller.run_stage_async` 一致；差异只在降级裁决由
        `RuntimeFailure.recoverable` 统一决定（可恢复 → degraded 继续；
        不可恢复 → 落账后抛错，由 `run()` 收口为 aborted）。
        """
        started = time.perf_counter()
        entry: dict = {"step": name}
        try:
            detail = await coro_factory()
        except Exception as exc:  # noqa: BLE001 — 段级异常一律归一为 RuntimeFailure
            logger.exception("agent loop 段失败：%s", name)
            entry.update({"status": "error", "error": exc.__class__.__name__})
            entry["duration_ms"] = _elapsed_ms(started)
            self._record_step(entry)
            failure = RuntimeFailure(
                kind=ERROR_KIND_BY_PHASE[phase],
                stage=name,
                run_id=self.run_context.run_id,
                recoverable=not critical,
                detail={"error": exc.__class__.__name__},
            )
            self._on_failure(failure)
            self._emit_stage(name, phase, entry)
            if not failure.recoverable:
                raise
            return entry
        entry.update(detail or {})
        entry.setdefault("status", "ok")
        entry["duration_ms"] = _elapsed_ms(started)
        self._record_step(entry)
        self._emit_stage(name, phase, entry)
        return entry

    async def _run_stages(
        self, names: Sequence[str], *, inputs: Mapping[str, Any] | None = None
    ) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for name in names:
            phase = stage_phase(name)
            results[name] = await self._run_stage(
                name,
                phase,
                self._coro_factory(name, phase, inputs),
                critical=name in self.spec.critical,
            )
        return results

    # ---- 六段方法（RT-007 ~ RT-012 的挂载点） ---------------------------
    #
    # H-1 裁决 B → R-15 灰度：默认 `run()` 仍走 Profile 阶段序列；仅当
    # `runtime_six_stage_loop_enabled=True` 时由 `_run_six_stage_loop` 调用。

    async def _run_phase(
        self, phase: str, inputs: Mapping[str, Any] | None = None
    ) -> object | None:
        names = self.stages_in(phase)
        if not names:
            return None
        return await self._run_stages(names, inputs=inputs)

    async def observe(self) -> object | None:
        """Observe 段：RT-007 显式实现（四类触发增量 → `Observation`）。"""
        self.observation = observe_stage.observe(
            self.runtime_input,
            self.session_context,
            runtime_context=self.runtime_context,
            runtime_state=state_manager.current(self.run_context),
            now=self.run_context.started_at or self.now,
            run_id=self.run_context.run_id,
            trace=self.trace,
        )
        return self.observation

    async def reason(
        self,
        observation: object | None = None,
        *,
        chat_response_intention: str | None = None,
        chat_response_goal_id: str | None = None,
        trigger_intention: str | None = None,
        trigger_goal_id: str | None = None,
    ) -> object | None:
        """Reason 段：RT-008 显式实现（情境 → 决策管线 → `Intention`）。

        前后台分叉由 `spec.run_kind` 裁决（前台 `chat_response*`、后台 `trigger_*`），
        调用方只需给出本轮的触发 / 回复意图；能力面由段内按 Profile 解析。
        """
        self.intention = await stages_reason.reason(
            self.runtime_input,
            self.session_context,
            observation if observation is not None else self.observation,
            spec=self.spec,
            runtime_state=state_manager.current(self.run_context),
            chat_response_intention=chat_response_intention,
            chat_response_goal_id=chat_response_goal_id,
            trigger_intention=trigger_intention,
            trigger_goal_id=trigger_goal_id,
            run=self.run_context,
            now=self.run_context.started_at or self.now,
            trace=self.trace,
        )
        return self.intention

    async def plan(self, intention: object | None = None) -> object | None:
        """Plan 段：RT-009 显式实现（`Intention` → `PlanValue`，可选段）。

        未启用 / 无目标 / 未通过一律返回 `None`，Act 回落消费 `Intention`（RT-009 D5）。
        """
        self.plan_value = await stages_plan.plan(
            intention if intention is not None else self.intention,
            spec=self.spec,
            session_context=self.session_context,
            run=self.run_context,
            llm=self.llm,
            now=self.run_context.started_at or self.now,
            trace=self.trace,
        )
        return self.plan_value

    async def act(
        self, intention: object | None = None, plan: object | None = None
    ) -> object | None:
        """Act 段：RT-010 显式实现（`Intention` / `PlanValue` → `ActOutcome`）。

        计划步骤存在（`PlanValue.current_step`）时走既有计划步骤执行路径；否则按意图
        映射创建并执行行动。行动失败只置 Run `degraded`，不中断循环。
        """
        self.act_outcome = await stages_act.act(
            intention if intention is not None else self.intention,
            plan=plan if plan is not None else self.plan_value,
            session_context=self.session_context,
            run=self.run_context,
            llm=self.llm,
            now=self.run_context.started_at or self.now,
            trace=self.trace,
        )
        return self.act_outcome

    async def reflect(self, action_result: object | None = None) -> object | None:
        """Reflect 段：RT-011 显式实现（慢时钟；默认关闭，可选段裁决）。"""
        self.reflect_outcome = await stages_reflect.reflect(
            action_outcome=(
                action_result if action_result is not None else self.act_outcome
            ),
            session_context=self.session_context,
            run=self.run_context,
            llm=self.llm,
            now=self.run_context.started_at or self.now,
            trace=self.trace,
        )
        return self.reflect_outcome

    async def update(
        self,
        action_result: object | None = None,
        insights: object | None = None,
    ) -> object | None:
        """Update 段：RT-012 显式实现（回写路由；前台只交接、后台走既有合法通道）。"""
        self.feedback = await stages_update.update(
            action_outcome=(
                action_result if action_result is not None else self.act_outcome
            ),
            reflect_outcome=insights if insights is not None else self.reflect_outcome,
            context=self.runtime_context,
            session_context=self.session_context,
            spec=self.spec,
            run=self.run_context,
            now=self.run_context.started_at or self.now,
            trace=self.trace,
        )
        return self.feedback

    # ---- 驱动 -----------------------------------------------------------

    def _six_stage_enabled(self) -> bool:
        return bool(getattr(get_settings(), SIX_STAGE_LOOP_SETTING, False))

    async def _run_six_stage_loop(self) -> None:
        """R-15 灰度驱动。

        - 前台 / 事件升级：按六环节分组调用既有 Profile 段本体（`_run_phase`），
          保持 22 步流式与业务闭包，只改「循环形状」。
        - 自治 tick：走 RT-007~012 六段显式实现（真收编目标路径）。
        """
        if self.spec.run_kind != RUN_KIND_AUTONOMOUS_TICK:
            for phase in SIX_STAGE_SEQUENCE:
                await self._run_phase(phase)
            return

        foreground = self.spec.run_kind == RUN_KIND_FOREGROUND_CHAT

        def _summary(value: object | None) -> dict[str, Any]:
            return {"outcome": None if value is None else type(value).__name__}

        async def _do_observe():
            return _summary(await self.observe())

        async def _do_reason():
            payload = getattr(self.runtime_input, "payload", None) or {}
            text = payload.get("text") if isinstance(payload, Mapping) else None
            return _summary(
                await self.reason(
                    chat_response_intention=text if foreground else None,
                    trigger_intention=(
                        None
                        if foreground
                        else str(getattr(self.runtime_input, "kind", "") or "")
                    ),
                )
            )

        async def _do_plan():
            return _summary(await self.plan())

        async def _do_act():
            return _summary(await self.act())

        async def _do_reflect():
            return _summary(await self.reflect())

        async def _do_update():
            return _summary(await self.update())

        handlers = {
            PHASE_OBSERVE: _do_observe,
            PHASE_REASON: _do_reason,
            PHASE_PLAN: _do_plan,
            PHASE_ACT: _do_act,
            PHASE_REFLECT: _do_reflect,
            PHASE_UPDATE: _do_update,
        }
        for phase in SIX_STAGE_SEQUENCE:
            await self._run_stage(
                phase,
                phase,
                handlers[phase],
                critical=phase in SIX_STAGE_CRITICAL,
            )

    @asynccontextmanager
    async def _lifecycle(self):
        """并发语义（裁决 D4）：前台不加 per-user 写锁，后台保留既有写锁。"""
        if self.user_id is None or self.run_context.run_kind == RUN_KIND_FOREGROUND_CHAT:
            yield
            return
        from app.application.post_process import get_user_write_lock

        async with get_user_write_lock(self.user_id):
            yield

    def _close(self) -> dict:
        """Run 收口：终态提升 + 关账 + RunClosed 事件（**必须**在 finally 内调用）。

        关账自身异常不得掩盖上游异常（取消 / 段失败），故内部兜底并只记日志。
        同时释放 Run 内投影缓存（H-5）：`state` / `context` 的内容不再留在 `run.data`。
        """
        if self._status == TERMINAL_DONE and (
            (self._promote_degraded and self.run_context.degraded)
            or any(
                isinstance(step, dict) and step.get("status") == "error"
                for step in self._steps
            )
        ):
            self._status = TERMINAL_DEGRADED
        budget_account = self._budget.as_dict() if self._budget is not None else {}
        try:
            controller.close_run(
                self.run_context,
                self._status,
                self._steps,
                budget_state=budget_account,
                now=datetime.now(),
                trace_ref=getattr(self.trace, "request_id", None),
            )
            event_bus.emit_run_closed(
                self.run_context.run_id, self._session_id, self._status, self.trace
            )
        except Exception:  # noqa: BLE001 — 关账失败不得掩盖上游异常
            logger.exception("agent loop 关账失败：%s", self.run_context.run_id)
        return budget_account

    async def run(
        self,
        runtime_input: RuntimeInput | None = None,
        session_context: SessionContext | None = None,
        *,
        runtime_context: Any = None,
    ) -> RunResult:
        """驱动一次认知循环：RunOpened → 段序列 → 收口 → RunClosed。

        **关账在 finally 内**：`CancelledError` 属 `BaseException`，不被 `except Exception`
        捕获；客户端断流会取消本任务，若关账在 try 之后则台账永久停留 `running`
        （只等孤儿扫掠收敛）。故取消 / 任意 BaseException 都必须在此收口为 `aborted`。
        """
        self.runtime_input = runtime_input
        self.session_context = session_context
        self.runtime_context = runtime_context
        self._session_id = (
            session_context.session_id if session_context is not None else None
        )
        self._budget = life_loop_budget.check_daily_budget(now=self.now)
        clock_token = logical_clock.bind(self.now)
        event_bus.emit_run_opened(self.run_context.run_id, self._session_id, self.trace)
        try:
            async with self._lifecycle():
                if self._six_stage_enabled():
                    await self._run_six_stage_loop()
                else:
                    await self._run_stages(self.stages)
        except asyncio.CancelledError:
            logger.warning(
                "agent loop run 被取消，按 aborted 关账：%s", self.run_context.run_id
            )
            self._status = TERMINAL_ABORTED
            self._record_step(
                {"step": "cancel", "status": "error", "error": "CancelledError"}
            )
            raise
        except Exception as exc:  # noqa: BLE001 — critical 段失败收口为 aborted
            logger.exception("agent loop run 中止：%s", self.run_context.run_id)
            self._status = TERMINAL_ABORTED
            self._record_step(
                {"step": "abort", "status": "error", "error": exc.__class__.__name__}
            )
        except BaseException as exc:  # noqa: BLE001 — KeyboardInterrupt / SystemExit 等
            logger.exception("agent loop run 被中断：%s", self.run_context.run_id)
            self._status = TERMINAL_ABORTED
            self._record_step(
                {"step": "abort", "status": "error", "error": exc.__class__.__name__}
            )
            raise
        finally:
            logical_clock.unbind(clock_token)
            digest_token = self.run_context.data.get("digest_token")
            if digest_token is not None:
                memory_digest_var.reset(digest_token)
            agent_state_assembler.reset_run_state(self.run_context)
            controller._reset_run_projections(  # pylint: disable=protected-access
                self.run_context
            )
            budget_account = self._close()
        return RunResult(
            run_id=self.run_context.run_id,
            status=self._status,  # type: ignore[arg-type]
            trace_ref=getattr(self.trace, "request_id", None),
            budget_account=budget_account,
        )
