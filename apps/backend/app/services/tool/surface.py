"""V2.4.0 工具面投影与工具选择（architecture.md §4.1 / §8.4、TOOL-004 §2.2、§2.3）。

三个纯函数组件：

```text
ToolSurfaceResolver.resolve(run_kind, ctx) → ToolSurface
    候选全集（注册表声明）→ 七维规则逐条过滤（记 {tool_id, reason}，首条命中短路）
    → priority 升序 + tool_id 字典序（确定性 tiebreak）→ 上限截断（reason=surface_limit）
    → surface_hash = sha1(规范化输入 + tool_ids)[:16]

ToolSelector.select(intent, surface) → ToolBinding | None
    ACTION_TOOL_MAP 候选 → 与 surface.tool_ids 取交集 → 空交返回 None（等价 V9 capability_unavailable）
    → 排序取首（确定性，规则见下）→ 注册表解析为绑定
    select_with_reason(...) 另返回 selection_reason（可排障、可断言）

ToolSurfacePolicy.policy_for / should_exclude
    Run Profile → SurfaceRule；八维规则判定裁剪原因（None = 保留）
```

**选择排序（P0-2，确定且零 IO）**：候选集同时含 `channel.*` 与非 `channel.*` 且意图参数带
非空收件人键（`recipient` / `recipient_id` / `to` / `external_id`）时，`channel.*` 整体前置
（reason=`channel_recipient_preferred`）——否则旗舰通道工具会被 priority 更小的本地工具
永久压住（选择器按 priority 升序取首）。其余情况一律 priority + tool_id 字典序
（reason=`priority_order`），与 TOOL-004 交付态逐字节一致。

**八维**：状态 / 可用性降级（TOOL-010，必然失败的已声明工具默认裁剪）/ Run Profile /
日时段 / 场景 / 关系阶段 / 世界可用性（预读事实 TOOL-007）/ 世界可用性（配置）。

**零 IO / 零 LLM**：全部输入来自 `ToolContext` 与注册表内存态（无 DB / 无网络 / 无 LLM）。
**缺省即降级**：世界事实维度为空（TOOL-007 未装配）时该维度不裁剪，只记 warning（E5 / E14）。
**总闸 off（注册表为 None）**：`resolve` 返回空 `ToolSurface`，调用方走 V9 原路径（E1）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.character.asuna.action import ACTION_CAPABILITY_MAP, ACTION_TOOL_MAP
from app.character.asuna.tool import (
    CHANNEL_NAMESPACE,
    DEFAULT_SURFACE_RULE,
    INTIMATE_TAG,
    LATE_NIGHT_EXCLUDE_NAMESPACES,
    LATE_NIGHT_EXCLUDE_TAGS,
    LATE_NIGHT_PARTS,
    SCENE_EXCLUDE_TAGS_BY_TONE,
    SURFACE_RULES,
    TOOL_UNAVAILABLE_REASON,
    TOOL_UNAVAILABLE_TOOL_IDS,
    WORLD_NAMESPACE,
    SurfaceRule,
    intimate_min_stage_rank,
    known_tone_biases,
    relationship_stage_rank,
)
from app.models.action import ActionIntent
from app.models.tool import ToolBinding, ToolDefinition, ToolSurface
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_SURFACE_MAX_TOOLS = 12

SURFACE_LIMIT_REASON = "surface_limit"

RECIPIENT_PARAM_KEYS: tuple[str, ...] = ("recipient", "recipient_id", "to", "external_id")

SELECTION_REASON_PRIORITY_ORDER = "priority_order"
SELECTION_REASON_CHANNEL_RECIPIENT = "channel_recipient_preferred"
SELECTION_REASON_NO_CANDIDATE = "no_candidate"

STATUS_REASON_PREFIX = "tool_status"
RUN_PROFILE_REASON_PREFIX = "run_profile"
PART_OF_DAY_REASON_PREFIX = "part_of_day"
SCENE_REASON_PREFIX = "scene"
RELATIONSHIP_REASON_PREFIX = "relationship_stage"
WORLD_REASON = "world_unavailable"
WORLD_FACTS_REASON = "world_disabled"

STATUS_LABELS: tuple[str, ...] = ("disabled", "deprecated", "removed", "tripped")

_HASH_WORLD_KEYS: tuple[str, ...] = (
    "location",
    "part_of_day",
    "weather",
    "current_block",
    "active_events",
    "world_enabled",
)

_HASH_SCENE_KEYS: tuple[str, ...] = ("location_id", "tone_bias")

_HASH_RELATIONSHIP_KEYS: tuple[str, ...] = ("stage", "tension")


class ToolSurfacePolicy:
    """六维投影策略（纯数据 + 纯函数）：`policy_for` 取规则，`should_exclude` 判裁剪。

    持有注册表引用只用于读生命周期与健康度内存态（不写、不查库）。
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry

    def policy_for(self, run_kind: str) -> SurfaceRule:
        """Run Profile 维度规则；未注册 Profile 取默认规则（不裁剪）并记 warning（E6）。"""
        rule = SURFACE_RULES.get(run_kind)
        if rule is not None:
            return rule
        logger.warning("surface_unknown_run_kind:%s（取默认规则，不做 Profile 维度裁剪）", run_kind)
        return DEFAULT_SURFACE_RULE

    def should_exclude(
        self, defn: ToolDefinition, ctx: ToolContext, rule: SurfaceRule
    ) -> str | None:
        """八维规则判定（按文档顺序短路）：返回裁剪原因，None 表示保留。"""
        return (
            self._status_reason(defn)
            or self._unavailable_reason(defn)
            or self._run_profile_reason(defn, rule)
            or self._part_of_day_reason(defn, ctx)
            or self._scene_reason(defn, ctx)
            or self._relationship_reason(defn, ctx)
            or self._world_facts_reason(defn, ctx)
            or self._world_reason(defn, ctx)
        )

    def _unavailable_reason(self, defn: ToolDefinition) -> str | None:
        """可用性降级维度（TOOL-010 §6.3 E1）：必然失败的已声明工具默认不进工具面。

        与状态维度正交：工具仍是 `enabled`、仍可被 `resolve`（直调得可判定的
        `unavailable` 结果），只是不再进入决策候选，避免反复触发必然失败的工具。
        """
        if defn.id in TOOL_UNAVAILABLE_TOOL_IDS:
            return TOOL_UNAVAILABLE_REASON
        return None

    def _status_reason(self, defn: ToolDefinition) -> str | None:
        """工具状态维度：非 enabled 一律剔除（内容态 / 运行期禁用 / 熔断）。"""
        registry = self._registry
        status = defn.status if registry is None else registry.effective_status(defn.id)
        if status == "enabled":
            return None
        if status == "disabled" and registry is not None and self._tripped(registry, defn.id):
            return f"{STATUS_REASON_PREFIX}:tripped"
        return f"{STATUS_REASON_PREFIX}:{status}"

    def _run_profile_reason(self, defn: ToolDefinition, rule: SurfaceRule) -> str | None:
        if defn.namespace in rule.exclude_namespaces:
            return f"{RUN_PROFILE_REASON_PREFIX}:{rule.reason or rule.run_kind}"
        if rule.exclude_tags and any(tag in rule.exclude_tags for tag in defn.tags):
            return f"{RUN_PROFILE_REASON_PREFIX}:{rule.reason or rule.run_kind}"
        if rule.exclude_side_effects and any(
            effect in rule.exclude_side_effects for effect in defn.side_effects
        ):
            return f"{RUN_PROFILE_REASON_PREFIX}:{rule.reason or rule.run_kind}"
        return None

    def _part_of_day_reason(self, defn: ToolDefinition, ctx: ToolContext) -> str | None:
        """日时段维度：late_night 剔除通道命名空间与社交标签；未装配则降级不裁剪。"""
        part = ctx.part_of_day()
        if part is None:
            logger.info("surface_part_of_day_degraded:ToolContext.world 未装配（TOOL-007）")
            return None
        if part not in LATE_NIGHT_PARTS:
            return None
        if defn.namespace in LATE_NIGHT_EXCLUDE_NAMESPACES:
            return f"{PART_OF_DAY_REASON_PREFIX}:{part}"
        if any(tag in LATE_NIGHT_EXCLUDE_TAGS for tag in defn.tags):
            return f"{PART_OF_DAY_REASON_PREFIX}:{part}"
        return None

    def _scene_reason(self, defn: ToolDefinition, ctx: ToolContext) -> str | None:
        """场景维度：工作型收紧（剔除 ambient），放松型放开；未知语气保守不裁剪（E14）。"""
        tone = ctx.scene_tone_bias()
        if tone is None:
            logger.info("surface_scene_degraded:ToolContext.scene 未装配（TOOL-007）")
            return None
        if tone not in known_tone_biases():
            logger.warning("surface_unknown_tone_bias:%s（保守：不做场景维度裁剪）", tone)
            return None
        excluded_tags = SCENE_EXCLUDE_TAGS_BY_TONE.get(tone, ())
        if excluded_tags and any(tag in excluded_tags for tag in defn.tags):
            return f"{SCENE_REASON_PREFIX}:{tone}"
        return None

    def _relationship_reason(self, defn: ToolDefinition, ctx: ToolContext) -> str | None:
        """关系阶段维度：阶段低于 friend 剔除亲密标签；未装配 / 未知阶段不裁剪。"""
        stage = ctx.relationship_stage()
        if stage is None:
            logger.info("surface_relationship_degraded:ToolContext.relationship 未装配（TOOL-007）")
            return None
        rank = relationship_stage_rank(stage)
        if rank is None:
            logger.warning("surface_unknown_relationship_stage:%s（保守：不做关系维度裁剪）", stage)
            return None
        if rank >= intimate_min_stage_rank():
            return None
        if INTIMATE_TAG in defn.tags:
            return f"{RELATIONSHIP_REASON_PREFIX}:{stage}"
        return None

    def _world_facts_reason(self, defn: ToolDefinition, ctx: ToolContext) -> str | None:
        """世界可用性维度（预读事实，TOOL-007 §4.4）：装配态 `world_enabled=False`
        时剔除整个 `world` 命名空间（理由 `world_disabled`）；未装配（None）降级不裁剪。"""
        if ctx.world_facts_enabled() is not False:
            return None
        if defn.namespace == WORLD_NAMESPACE:
            return WORLD_FACTS_REASON
        return None

    def _world_reason(self, defn: ToolDefinition, ctx: ToolContext) -> str | None:
        """世界可用性维度（配置态）：world_enabled=False 剔除 world 命名空间（V9 world_gate 同款）。"""
        if ctx.world_enabled():
            return None
        if defn.namespace == WORLD_NAMESPACE:
            return WORLD_REASON
        return None

    @staticmethod
    def _tripped(registry: ToolRegistry, tool_id: str) -> bool:
        record = registry.health(tool_id).get(tool_id)
        return bool(record is not None and record.tripped)


class ToolSurfaceResolver:
    """工具面解析器：候选全集 → 六维过滤 → 排序 → 截断 → 哈希。

    `settings` 缺省（None）时取 `ToolContext.settings`——投影只认调用方预读的快照。
    """

    def __init__(self, registry: ToolRegistry | None, settings: Any = None) -> None:
        self.registry = registry
        self.settings = settings
        self.policy = ToolSurfacePolicy(registry)

    def resolve(self, run_kind: str, ctx: ToolContext) -> ToolSurface:
        """按 Run Profile 与语境投影工具面；注册表缺失（总闸 off）返回空面（E1）。"""
        if self.registry is None:
            return _empty_surface(run_kind, ctx, self._max_tools(None, ctx))
        rule = self.policy.policy_for(run_kind)
        max_tools = self._max_tools(rule, ctx)
        excluded: list[dict[str, Any]] = []
        kept: list[tuple[int, str]] = []
        for definition in sorted(self.registry.list(), key=lambda item: item.id):
            reason = self.policy.should_exclude(definition, ctx, rule)
            if reason is not None:
                excluded.append({"tool_id": definition.id, "reason": reason})
                continue
            kept.append((definition.priority, definition.id))
        kept.sort(key=lambda item: (item[0], item[1]))
        tool_ids = tuple(tool_id for _, tool_id in kept)
        if len(tool_ids) > max_tools:
            excluded.extend(
                {"tool_id": tool_id, "reason": SURFACE_LIMIT_REASON}
                for tool_id in tool_ids[max_tools:]
            )
            tool_ids = tool_ids[:max_tools]
        return ToolSurface(
            run_kind=run_kind,
            tool_ids=tool_ids,
            excluded=tuple(excluded),
            surface_hash=surface_hash(run_kind, ctx, rule, max_tools, tool_ids),
        )

    def _max_tools(self, rule: SurfaceRule | None, ctx: ToolContext) -> int:
        """上限：规则覆盖 > resolver 显式设置 > `ToolContext.settings` 全局默认。"""
        if rule is not None and rule.max_tools is not None:
            return int(rule.max_tools)
        settings = self.settings if self.settings is not None else ctx.settings
        return int(
            getattr(settings, "v24_tool_surface_max_tools", DEFAULT_SURFACE_MAX_TOOLS)
        )


@dataclass(frozen=True)
class ToolSelection:
    """选择结果 + 可复现原因（P0-2）：`reason` 见 `SELECTION_REASON_*`，`candidates` 为排序后全序。"""

    binding: ToolBinding | None
    reason: str
    recipient: str = ""
    candidates: tuple[str, ...] = ()


def delivery_recipient(intent: ActionIntent) -> str:
    """外部投递收件人：`intent.params` 里首个非空字符串收件人键的值（纯函数、零 IO）。

    同时支持 `intent` 为 `None` 或 `params` 非映射的退化输入——一律视为"无收件人"。
    """
    params = getattr(intent, "params", None)
    if not isinstance(params, Mapping):
        return ""
    for key in RECIPIENT_PARAM_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class ToolSelector:
    """意图 → 工具绑定：ACTION_TOOL_MAP → 工具面交集 → 排序取首（收件人感知，见 `select_with_reason`）。"""

    def __init__(
        self,
        registry: ToolRegistry | None,
        *,
        tool_map: Mapping[str, Sequence[str]] | None = None,
        capability_map: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self.registry = registry
        self.tool_map = dict(ACTION_TOOL_MAP if tool_map is None else tool_map)
        self.capability_map = dict(
            ACTION_CAPABILITY_MAP if capability_map is None else capability_map
        )

    def select(self, intent: ActionIntent, surface: ToolSurface | None) -> ToolBinding | None:
        """交集为空返回 None（工具不可用，等价 V9 `capability_unavailable`）。"""
        return self.select_with_reason(intent, surface).binding

    def select_with_reason(
        self, intent: ActionIntent, surface: ToolSurface | None
    ) -> ToolSelection:
        """选择结果 + 可读原因（P0-2）：纯函数、零 IO、确定（同输入同输出）。

        候选排序分两种：
        - **外部投递收件人感知**（`SELECTION_REASON_CHANNEL_RECIPIENT`）：同一 `action_type`
          的候选集里同时含 `channel.*` 与其它候选，且意图参数携带非空收件人键时，
          `namespace == "channel"` 的候选整体前置——`channel.*` 是"真发出去"的那一个，
          否则旗舰通道工具会被 priority 更小的本地工具永久压住（选择器按 priority 升序取首）。
        - **原 priority + tool_id 字典序**（`SELECTION_REASON_PRIORITY_ORDER`）：其余情况，
          与 TOOL-004 交付态逐字节一致。
        """
        if self.registry is None or surface is None or not surface.tool_ids:
            return ToolSelection(None, SELECTION_REASON_NO_CANDIDATE)
        available = set(surface.tool_ids)
        candidates = [tool_id for tool_id in self.tool_map.get(intent.action_type, ()) if tool_id in available]
        if not candidates:
            candidates = self._fallback_candidates(intent, available)
        if not candidates:
            return ToolSelection(None, SELECTION_REASON_NO_CANDIDATE)
        recipient = delivery_recipient(intent)
        channel_first = bool(recipient) and self._mixes_channel_and_others(candidates)
        ordered = sorted(
            candidates,
            key=lambda tool_id: (0 if channel_first and self._is_channel(tool_id) else 1,)
            + self._order_key(tool_id),
        )
        reason = (
            SELECTION_REASON_CHANNEL_RECIPIENT if channel_first else SELECTION_REASON_PRIORITY_ORDER
        )
        logger.debug(
            "surface_tool_selected:%s recipient=%s candidates=%s",
            ordered[0],
            recipient,
            list(ordered),
        )
        binding = self.registry.resolve(ordered[0])
        if binding is None:
            logger.warning(
                "surface_tool_unresolvable:%s（声明缺失，判为不可用）", ordered[0]
            )
        return ToolSelection(
            binding, reason, recipient=recipient, candidates=tuple(ordered)
        )

    def _is_channel(self, tool_id: str) -> bool:
        definition = self.registry.get(tool_id)
        return definition is not None and definition.namespace == CHANNEL_NAMESPACE

    def _mixes_channel_and_others(self, candidates: Sequence[str]) -> bool:
        """候选集是否"既有通道候选又有非通道候选"（只有一个候选时谈不上优先级）。"""
        namespaces = {
            definition.namespace
            for tool_id in candidates
            if (definition := self.registry.get(tool_id)) is not None
        }
        return CHANNEL_NAMESPACE in namespaces and len(namespaces) > 1

    def _fallback_candidates(self, intent: ActionIntent, available: set[str]) -> list[str]:
        """ACTION_TOOL_MAP 未覆盖时的旧映射兜底：按 (capability, action) 在面上寻回（E8）。"""
        mapped = self.capability_map.get(intent.action_type)
        if mapped is None or len(mapped) < 2:
            return []
        capability, action = mapped[0], mapped[1]
        return [
            tool_id
            for tool_id in sorted(available)
            if (definition := self.registry.get(tool_id)) is not None
            and definition.capability == capability
            and definition.action == action
        ]

    def _order_key(self, tool_id: str) -> tuple[int, str]:
        definition = self.registry.get(tool_id)
        priority = definition.priority if definition is not None else 100
        return (priority, tool_id)


def surface_hash(
    run_kind: str,
    ctx: ToolContext,
    rule: SurfaceRule | None,
    max_tools: int,
    tool_ids: Sequence[str],
) -> str:
    """sha1(规范化输入 + tool_ids)[:16]：同输入同输出（可复现锚点）。"""
    payload = {
        "run_kind": run_kind,
        "source": ctx.source,
        "world": _pick(ctx.world, _HASH_WORLD_KEYS),
        "scene": _pick(ctx.scene, _HASH_SCENE_KEYS),
        "relationship": _pick(ctx.relationship, _HASH_RELATIONSHIP_KEYS),
        "world_enabled": ctx.world_enabled(),
        "rule": (
            None
            if rule is None
            else {
                "run_kind": rule.run_kind,
                "exclude_namespaces": list(rule.exclude_namespaces),
                "exclude_tags": list(rule.exclude_tags),
                "exclude_side_effects": list(rule.exclude_side_effects),
                "max_tools": rule.max_tools,
                "reason": rule.reason,
            }
        ),
        "max_tools": max_tools,
        "tool_ids": list(tool_ids),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def _pick(source: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys}


def _empty_surface(run_kind: str, ctx: ToolContext, max_tools: int) -> ToolSurface:
    return ToolSurface(
        run_kind=run_kind,
        tool_ids=(),
        excluded=(),
        surface_hash=surface_hash(run_kind, ctx, None, max_tools, ()),
    )
