"""V2.5.0 PLAN-003 规划上下文装配（Task Detail §4.1.3 / architecture.md §3.3、§6.3）。

本模块回答「规划这一刻，Agent 能看见什么」，输出 `PlanContext` 供规划引擎与后续的
`TaskDecomposer`（PLAN-004）消费。**只读装配**：不执行、不写库、不调 LLM。

六源与降级形态（Task Detail §4.3.3）

| 源 | 读取入口 | 不可用形态（`degraded` 标记） |
|---|---|---|
| Goal | `goal_repository.get_goal` | **硬依赖**：缺失即 `PlanUnavailable("goal_missing")` |
| World | `world_engine.collect_facts` / `build_context` | 空包 / `world_disabled` |
| Context | `scene_profile_for` / `get_active_situation` / 关系投影 | 空包 / `scene_unavailable` 等 |
| Memory | `memory2.retriever.retrieve` | 空列表 / `memory_unavailable` |
| Reflection | `list_user_active_insights` / `interest_signal` | 空列表 / `reflection_unavailable` |
| ToolSurface | `build_tool_context` + `ToolSurfaceResolver` | **硬依赖**（总闸 off / 注册表不可得 / 无面退化见下） |

ToolSurface 的三态：`v25_plan_tool_required` on 且工具系统可用 → 按 `RUN_KIND_AUTONOMOUS_TICK`
投影；总闸 off → `PlanUnavailable("tool_system_disabled")`；注册表不可得 →
`PlanUnavailable("registry_unavailable")`；`v25_plan_tool_required` off → 空面 +
`surface_unavailable`（允许无面规划，退化为 V2.4.0 行为）。

**零 IO / 零 LLM / 零写库**：`assemble` 是唯一允许读仓储的入口，且只读不写；`PlanContextProbe`
是 `assemble` 快照的**只读投影**（零 IO——不读仓储、不调 LLM、不写库）。`assemble` 不触发
`world_engine.ensure_world` 的建档写入：世界记录缺失即降级为空包（`world_disabled`）。

工具面一律按 `RUN_KIND_AUTONOMOUS_TICK` 解析（architecture.md §6.3 裁决）：计划的执行发生在
后台节拍，「必须用户在线」的 `channel.*` 类工具被结构性地剔除，规划层不可能规划出
「趁用户不在时发消息」的步骤——权限边界的结构化解法，而非运行时补丁。

内部辅助函数与 Task Detail §6.3 的三处差异（均为源码签名核对结果，已在测试留痕）：

1. `_assemble_context` 的第二个参数是**世界事实包**（`world`）而非世界记录：场景画像按
   `world["location"]` 取地点 id，与 §4.1.3 的 `scene_profile_for(world.location_id)` 同源。
2. `_assemble_context` 的第二个返回值是 `list[UserSituation]`（`PlanContext.situations` 为
   列表），由 `get_active_situation(user_id, dimension)` 逐维度装配——该函数真实签名要求
   dimension，故按五维枚举取值。
3. `_assemble_world` / `_gather_sources` 不接 `now`：世界源的既有入口不接时刻参数（时刻由
   `TimeProvider` 从世界时钟取），`now` 仅用于工具面装配。装配中间态用 `_WorldSource` /
   `_PlanSources` 两个内部载体承载（§6.3 的裸 tuple 不便承载逐源降级清单）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.application import world_engine
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK, RunContext
from app.character.asuna.scene_profiles import scene_profile_for
from app.core.settings import get_settings
from app.models.goal import GoalRecord
from app.models.plan import GoalRef, MemoryRef, PlanContext
from app.models.reflection import InsightSummary
from app.models.tool import ToolSurface
from app.models.world_simulation import (
    SceneProfile,
    SituationDimension,
    UserSituation,
    WorldBrief,
)
from app.repositories import goal_repository, world_simulation_repository
from app.services.memory2 import retriever as memory_retriever
from app.services.reflection import lifecycle as reflection_lifecycle
from app.services.reflection import tool_feed as reflection_tool_feed
from app.services.tool.context import ToolContext
from app.services.tool.registry import get_tool_registry
from app.services.tool.surface import ToolSurfaceResolver
from app.services.tool.world_context import WorldContextBuilder, build_tool_context
from app.services.world import world_brief as world_brief_service

logger = logging.getLogger(__name__)

PLAN_UNAVAILABLE_GOAL_MISSING = "goal_missing"
PLAN_UNAVAILABLE_TOOL_SYSTEM_DISABLED = "tool_system_disabled"
PLAN_UNAVAILABLE_REGISTRY_UNAVAILABLE = "registry_unavailable"

PLAN_UNAVAILABLE_REASONS: tuple[str, ...] = (
    PLAN_UNAVAILABLE_GOAL_MISSING,
    PLAN_UNAVAILABLE_TOOL_SYSTEM_DISABLED,
    PLAN_UNAVAILABLE_REGISTRY_UNAVAILABLE,
)

DEGRADED_WORLD_DISABLED = "world_disabled"
DEGRADED_SCENE_UNAVAILABLE = "scene_unavailable"
DEGRADED_SITUATION_UNAVAILABLE = "situation_unavailable"
DEGRADED_MEMORY_UNAVAILABLE = "memory_unavailable"
DEGRADED_REFLECTION_UNAVAILABLE = "reflection_unavailable"
DEGRADED_SURFACE_UNAVAILABLE = "surface_unavailable"

PLAN_DEGRADED_REASONS: tuple[str, ...] = (
    DEGRADED_WORLD_DISABLED,
    DEGRADED_SCENE_UNAVAILABLE,
    DEGRADED_SITUATION_UNAVAILABLE,
    DEGRADED_MEMORY_UNAVAILABLE,
    DEGRADED_REFLECTION_UNAVAILABLE,
    DEGRADED_SURFACE_UNAVAILABLE,
)

PLAN_BUDGET_KEYS: tuple[str, ...] = (
    "max_steps",
    "max_depth",
    "revision_budget",
    "step_max_attempts",
)

PLAN_RUN_KEYS: tuple[str, ...] = ("run_id", "run_kind", "trigger_type")

PLAN_TOOL_RUN_SOURCE = "autonomy"

ANCESTOR_CHAIN_LIMIT = 4

_PROBE_SNAPSHOT_LIMIT = 64


@dataclass(frozen=True)
class PlanUnavailable:
    """硬依赖缺失（Task Detail §4.2.3）：**正常业务结果**——这一轮不规划，不是异常。

    `reason` 取值即 `PLAN_UNAVAILABLE_REASONS`；调用方（规划引擎 / 生活环）据此跳过本轮，
    零 LLM 调用、零计划落库。
    """

    reason: str


@dataclass(frozen=True)
class PlanProbeSnapshot:
    """`assemble` 写下的只读探测快照：`PlanContextProbe` 的唯一数据面。"""

    world_available: bool = False
    tool_surface_size: int = 0
    surface_run_kind: str = RUN_KIND_AUTONOMOUS_TICK
    degraded: tuple[str, ...] = ()


_PROBE_SNAPSHOTS: dict[str, PlanProbeSnapshot] = {}


def plan_budget(settings) -> dict[str, int]:
    """`PlanContext.budget` 的 settings 投影（步数 / 深度 / 修订 / 尝试四项上限）。"""
    return {
        "max_steps": int(settings.v25_plan_max_steps),
        "max_depth": int(settings.v25_plan_max_depth),
        "revision_budget": int(settings.v25_plan_revision_budget),
        "step_max_attempts": int(settings.v25_plan_step_max_attempts),
    }


def context_digest(context: PlanContext) -> str:
    """`PlanContext` 哈希摘要（同输入同输出，对齐 `ToolSurface.surface_hash` 工程标准）。

    只覆盖**稳定投影**（身份 / 预算 / 运行态 / 降级 / 各源可判定字段），不哈希完整对象：
    摘要的用途是「计划为什么规划成这样」的事后可复现锚点，不是内容寻址。
    """
    payload: dict[str, Any] = {
        "goal": [context.goal.id, context.goal.status, context.goal.description],
        "budget": sorted(context.budget.items()),
        "run": sorted(context.run.items()),
        "degraded": sorted(context.degraded),
        "world_keys": sorted(context.world.keys()),
        "world_part_of_day": context.world.get("part_of_day"),
        "world_location": context.world.get("location"),
        "world_brief": None if context.world_brief is None else context.world_brief.text,
        "scene": None if context.scene is None else context.scene.location_id,
        "situations": [situation.id for situation in context.situations],
        "relationship": sorted(context.relationship.items()),
        "memories": [memory.id for memory in context.memories],
        "insights": [insight.insight_id for insight in context.insights],
        "ancestors": [goal.id for goal in context.ancestors],
        "siblings": [goal.id for goal in context.siblings],
        "evidence_refs": list(context.evidence_refs),
        "surface_hash": context.tool_surface.surface_hash,
        "surface_size": len(context.tool_surface.tool_ids),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


class PlanContextProbe:
    """只读探测面（Task Detail §6.2 / architecture.md §8.2）：供 debug 与自治事实收集。

    **零 IO**：只读 `assemble` 留下的内存快照（`PlanProbeSnapshot`），不读仓储、不调 LLM、
    不写库。`snapshots` 可注入（测试与调用方自持存储）；缺省用模块级有界快照表。
    """

    def __init__(self, snapshots: Mapping[str, PlanProbeSnapshot] | None = None) -> None:
        self._snapshots = _PROBE_SNAPSHOTS if snapshots is None else snapshots

    def world_available(self, user_id: str) -> bool:
        """最近一次装配里世界源是否可用（无快照 = 未装配 = 不可用）。"""
        return self._snapshot(user_id).world_available

    def surface_size(self, user_id: str, *, run_kind: str) -> int:
        """最近一次装配的工具面规模；`run_kind` 不匹配该快照时返回 0（不跨 Run Profile 复用）。"""
        snapshot = self._snapshot(user_id)
        if snapshot.surface_run_kind != run_kind:
            return 0
        return snapshot.tool_surface_size

    def degraded_sources(self, user_id: str) -> list[str]:
        """最近一次装配的降级源清单（稳定字符串，可进 `loop_runs.steps` 子步骤）。"""
        return list(self._snapshot(user_id).degraded)

    def _snapshot(self, user_id: str) -> PlanProbeSnapshot:
        return self._snapshots.get(user_id, PlanProbeSnapshot())


class PlanContextAssembler:
    """六源装配器（Task Detail §6.2）：`assemble` 是唯一读仓储入口，且只读不写。

    `assemble` 为 async：World 源的既有装配入口是同步阻塞的仓储读（与 `chat_pipeline`
    同款 `asyncio.to_thread` 卸载）。其余源同步只读。
    `v25_plan_context_enabled` off 时**不做四源装配**（只保硬依赖两源，`degraded` 为空）。
    """

    async def assemble(
        self,
        goal: GoalRecord,
        *,
        run: RunContext | None = None,
        now: datetime | None = None,
    ) -> PlanContext | PlanUnavailable:
        """装配 `PlanContext`；硬依赖缺失返回 `PlanUnavailable`（调用方跳过本轮规划）。"""
        settings = get_settings()
        moment = now or datetime.now()
        resolved_goal = goal_repository.get_goal(goal.id)
        if resolved_goal is None:
            return PlanUnavailable(PLAN_UNAVAILABLE_GOAL_MISSING)
        surface = self._assemble_tool_surface(resolved_goal.user_id, settings, moment)
        if isinstance(surface, PlanUnavailable):
            return surface
        context = await self._build_context(resolved_goal, surface, settings, run)
        _remember_snapshot(resolved_goal.user_id, context)
        return context

    async def _build_context(
        self,
        goal: GoalRecord,
        surface: ToolSurface,
        settings,
        run: RunContext | None,
    ) -> PlanContext:
        """汇总四源（`v25_plan_context_enabled` 才装配）+ 硬依赖两源 → `PlanContext`。"""
        sources = _PlanSources()
        if settings.v25_plan_context_enabled:
            sources = await _gather_sources(goal, settings)
        degraded = list(sources.degraded)
        if not settings.v25_plan_tool_required:
            degraded.append(DEGRADED_SURFACE_UNAVAILABLE)
        ancestors, siblings = _assemble_goal_chain(goal)
        return PlanContext(
            goal=goal,
            tool_surface=surface,
            budget=plan_budget(settings),
            ancestors=ancestors,
            siblings=siblings,
            world=sources.world.facts,
            world_brief=sources.world.brief,
            world_context=sources.world.context,
            situations=sources.situations,
            scene=sources.scene,
            relationship=sources.relationship,
            memories=sources.memories,
            insights=sources.insights,
            run=_run_projection(run),
            degraded=degraded,
            evidence_refs=_evidence_refs(run),
        )

    @staticmethod
    def _assemble_tool_surface(
        user_id: str, settings, now: datetime
    ) -> ToolSurface | PlanUnavailable:
        """工具面（硬依赖，Task Detail §4.3.2）：按 `RUN_KIND_AUTONOMOUS_TICK` 解析。

        `v25_plan_tool_required` off → 允许无面规划（空面，退化为 V2.4.0 行为）；
        on 时总闸 off / 注册表不可得都是硬依赖缺失——**宁可这一轮不规划**。
        """
        base = ToolContext(
            user_id=user_id,
            now=now,
            settings=settings,
            run_kind=RUN_KIND_AUTONOMOUS_TICK,
            source=PLAN_TOOL_RUN_SOURCE,
        )
        if not settings.v25_plan_tool_required:
            return ToolSurfaceResolver(None, settings).resolve(
                RUN_KIND_AUTONOMOUS_TICK, base
            )
        if not settings.v24_tool_system_enabled:
            return PlanUnavailable(PLAN_UNAVAILABLE_TOOL_SYSTEM_DISABLED)
        registry = get_tool_registry()
        if registry is None:
            return PlanUnavailable(PLAN_UNAVAILABLE_REGISTRY_UNAVAILABLE)
        tool_ctx = build_tool_context(base, settings=settings, now=now)
        return ToolSurfaceResolver(registry, settings).resolve(
            RUN_KIND_AUTONOMOUS_TICK, tool_ctx
        )


@dataclass
class _WorldSource:
    """World 源的三段产物：事实包 / `WorldContext` / 世界简报（逐段可缺省）。"""

    facts: dict[str, Any] = field(default_factory=dict)
    context: Any = None
    brief: WorldBrief | None = None


@dataclass
class _PlanSources:
    """四个可降级源的装配结果（含逐源降级清单）——`assemble` 汇总用的内部载体。"""

    world: _WorldSource = field(default_factory=_WorldSource)
    scene: SceneProfile | None = None
    situations: list[UserSituation] = field(default_factory=list)
    relationship: dict[str, Any] = field(default_factory=dict)
    memories: list[MemoryRef] = field(default_factory=list)
    insights: list[InsightSummary] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)


async def _assemble_world(user_id: str) -> tuple[_WorldSource, list[str]]:
    """World 源（可降级）：事实包 + `WorldContext` + 简报；世界关闭或无世界记录即空包。

    **不触发建档**：`world_engine.get_world` 为只读判定，为 None 时直接降级——不由本模块
    创建世界记录（`ensure_world` 是写路径）。`build_context` 内部的既有通读在世界上存在时
    零写入（世界建档 / 家庭默认物播种是其既有前置，属世界侧 Flag 的既有行为）。
    """
    settings = get_settings()
    empty = (_WorldSource(), [DEGRADED_WORLD_DISABLED])
    if not settings.world_enabled:
        return empty
    try:
        world = world_engine.get_world(user_id)
    except Exception:
        logger.exception("世界读取失败，规划上下文世界源降级：%s", user_id)
        return empty
    if world is None:
        return empty
    try:
        facts = await asyncio.to_thread(world_engine.collect_facts, user_id)
        world_context = await asyncio.to_thread(world_engine.build_context, user_id)
    except Exception:
        logger.exception("世界事实装配失败，规划上下文世界源降级：%s", user_id)
        return empty
    source = _WorldSource(
        facts=facts or {},
        context=world_context,
        brief=_world_brief(world_context, world, settings),
    )
    return source, []


def _world_brief(world_context: Any, world: Any, settings) -> WorldBrief | None:
    """世界简报：`build_context` 已装配时直接取用，否则用既有纯函数按预算装配一次。"""
    if world_context is None:
        return None
    if world_context.brief is not None:
        return world_context.brief
    try:
        return world_brief_service.build_world_brief(
            world_context.time,
            world,
            None,
            None,
            world_context.salient_events,
            budget=settings.world_brief_char_budget,
        )
    except Exception:
        logger.exception("世界简报装配失败，规划上下文简报段缺省")
        return None


async def _gather_sources(goal: GoalRecord, settings) -> _PlanSources:
    """四源顺序装配（Task Detail §4.1.3）：World → Context → Memory → Reflection。"""
    sources = _PlanSources()
    sources.world, world_degraded = await _assemble_world(goal.user_id)
    sources.degraded.extend(world_degraded)
    scene, situations, relationship, context_degraded = _assemble_context(
        goal.user_id, sources.world.facts, settings
    )
    sources.scene, sources.situations, sources.relationship = scene, situations, relationship
    sources.degraded.extend(context_degraded)
    sources.memories, memory_degraded = _assemble_memory(goal, settings)
    sources.degraded.extend(memory_degraded)
    sources.insights, reflection_degraded = _assemble_reflection(goal.user_id, settings)
    sources.degraded.extend(reflection_degraded)
    return sources



def _assemble_context(
    user_id: str, world: dict[str, Any], settings
) -> tuple[SceneProfile | None, list[UserSituation], dict[str, Any], list[str]]:
    """Context 源（可降级）：场景画像 + 活跃处境 + 关系阶段投影，逐项登记降级。"""
    degraded: list[str] = []
    scene, scene_degraded = _scene_profile(world.get("location"))
    degraded.extend(scene_degraded)
    situations, situation_degraded = _active_situations(user_id)
    degraded.extend(situation_degraded)
    relationship, relationship_degraded = _relationship_projection(user_id, settings)
    degraded.extend(relationship_degraded)
    return scene, situations, relationship, degraded


def _scene_profile(location: str | None) -> tuple[SceneProfile | None, list[str]]:
    """场景画像：地点缺失（世界停用 / 无事实）或装配失败即降级（场景维度不裁剪）。"""
    if not location:
        return None, [DEGRADED_SCENE_UNAVAILABLE]
    try:
        return scene_profile_for(str(location)), []
    except Exception:
        logger.exception("场景画像装配失败，规划上下文场景段缺省：%s", location)
        return None, [DEGRADED_SCENE_UNAVAILABLE]


def _active_situations(user_id: str) -> tuple[list[UserSituation], list[str]]:
    """活跃处境：逐维度取 `get_active_situation`（该入口的真实签名要求 dimension）。"""
    try:
        found: list[UserSituation] = []
        for dimension in SituationDimension:
            situation = world_simulation_repository.get_active_situation(user_id, dimension)
            if situation is not None:
                found.append(situation)
        return found, []
    except Exception:
        logger.exception("活跃处境读取失败，规划上下文处境段缺省：%s", user_id)
        return [], [DEGRADED_SITUATION_UNAVAILABLE]


def _relationship_projection(user_id: str, settings) -> tuple[dict[str, Any], list[str]]:
    """关系阶段投影 `{stage, tension}`：复用工具侧八段装配的既有投影（零写、失败空包）。"""
    try:
        projection = WorldContextBuilder(settings).build_relationship(user_id)
    except Exception:
        logger.exception("关系投影装配失败，规划上下文关系段缺省：%s", user_id)
        return {}, []
    return projection or {}, []


def _assemble_memory(goal: GoalRecord, settings) -> tuple[list[MemoryRef], list[str]]:
    """Memory 源（可降级、有界）：既有检索（含打分与拒绝冷却过滤器）后再二次裁剪。"""
    if not settings.v2_memory_enabled:
        return [], [DEGRADED_MEMORY_UNAVAILABLE]
    try:
        ranked = memory_retriever.retrieve(
            goal.user_id, query=goal.description, top_k=settings.memory_top_k
        )
    except Exception:
        logger.exception("规划记忆检索失败，规划上下文记忆源降级：%s", goal.user_id)
        return [], [DEGRADED_MEMORY_UNAVAILABLE]
    refs = [
        MemoryRef(
            id=item.memory.id,
            type=str(item.memory.type),
            content=item.memory.content,
            importance=float(item.memory.importance),
        )
        for item in ranked.items
    ]
    return refs[: settings.v25_plan_context_memory_limit], []


def _assemble_reflection(
    user_id: str, settings
) -> tuple[list[InsightSummary], list[str]]:
    """Reflection 源（可降级、有界）：活跃 Insight 投影 + 工具效能倾向并入后统一截断。"""
    if not settings.v2_reflection_enabled:
        return [], [DEGRADED_REFLECTION_UNAVAILABLE]
    try:
        summaries = [
            InsightSummary(
                insight_id=insight.id,
                statement=insight.statement,
                type=insight.type,
                confidence=insight.confidence,
            )
            for insight in reflection_lifecycle.list_user_active_insights(user_id)
        ]
        signals = reflection_tool_feed.interest_signal(user_id)
        merged = _merge_insights(summaries, signals)
    except Exception:
        logger.exception("规划反思读取失败，规划上下文反思源降级：%s", user_id)
        return [], [DEGRADED_REFLECTION_UNAVAILABLE]
    return merged[: settings.v25_plan_context_insight_limit], []


def _merge_insights(
    summaries: list[InsightSummary], signals: list[dict[str, Any]]
) -> list[InsightSummary]:
    """工具效能倾向并入 Insight 投影（按 `insight_id` 去重，先到者胜）。

    `PlanContext` 无独立工具信号字段：`InsightSummary` 与工具信号同构（id / 陈述 /
    类型 / 置信度），故并入而不新增模型字段（零模型层改动）。
    """
    merged = list(summaries)
    known = {summary.insight_id for summary in merged}
    for signal in signals:
        insight_id = str(signal.get("insight_id") or "")
        if not insight_id or insight_id in known:
            continue
        known.add(insight_id)
        merged.append(
            InsightSummary(
                insight_id=insight_id,
                statement=str(signal.get("statement") or ""),
                type=signal.get("type"),
                confidence=float(signal.get("confidence") or 0.0),
            )
        )
    return merged


def _assemble_goal_chain(goal: GoalRecord) -> tuple[list[GoalRef], list[GoalRef]]:
    """Goal 源的链投影（祖先链 + 同父兄弟）：只读、有界，失败降级为空链不阻塞规划。"""
    try:
        ancestors = _ancestors(goal)
        siblings = (
            [
                _goal_ref(sibling)
                for sibling in goal_repository.list_children(goal.parent_goal_id)
                if sibling.id != goal.id
            ]
            if goal.parent_goal_id
            else []
        )
        return ancestors, siblings
    except Exception:
        logger.exception("目标链投影失败，规划上下文链段缺省：%s", goal.id)
        return [], []


def _ancestors(goal: GoalRecord) -> list[GoalRef]:
    chain: list[GoalRef] = []
    parent_id = goal.parent_goal_id
    while parent_id and len(chain) < ANCESTOR_CHAIN_LIMIT:
        parent = goal_repository.get_goal(parent_id)
        if parent is None:
            break
        chain.append(_goal_ref(parent))
        parent_id = parent.parent_goal_id
    return chain


def _goal_ref(goal: GoalRecord) -> GoalRef:
    return GoalRef(
        id=goal.id,
        type=goal.type,
        status=goal.status,
        layer=goal.layer,
        domain=goal.domain,
        priority=goal.priority,
    )


def _run_projection(run: RunContext | None) -> dict[str, Any]:
    if run is None:
        return {}
    return {
        "run_id": run.run_id,
        "run_kind": run.run_kind,
        "trigger_type": run.trigger_type,
    }


def _evidence_refs(run: RunContext | None) -> list[str]:
    """证据引用透传：本轮 Run 携带的 `evidence_refs`（内容由 PLAN-010 注入）。"""
    if run is None:
        return []
    raw = (run.data or {}).get("evidence_refs") or []
    return [str(item) for item in raw]


def _remember_snapshot(user_id: str, context: PlanContext) -> None:
    """写下探测快照（有界内存表，越界即逐出最旧项）；不参与任何落库。"""
    if user_id not in _PROBE_SNAPSHOTS and len(_PROBE_SNAPSHOTS) >= _PROBE_SNAPSHOT_LIMIT:
        _PROBE_SNAPSHOTS.pop(next(iter(_PROBE_SNAPSHOTS)), None)
    _PROBE_SNAPSHOTS[user_id] = PlanProbeSnapshot(
        world_available=bool(context.world),
        tool_surface_size=len(context.tool_surface.tool_ids),
        surface_run_kind=context.tool_surface.run_kind,
        degraded=tuple(context.degraded),
    )
