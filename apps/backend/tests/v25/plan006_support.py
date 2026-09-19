"""PLAN-006 单测共享构造：真实工具面 / 六闸门探针 / 五段短路探针 / 台账写探针。

只做构造与探测，不做断言（与 `plan004_support.py` / `plan005_support.py` 同款纪律）。
三条纪律：

1. **真实面优先**：T1~T4 与执行链用例一律经真实 `ToolSurfaceResolver` 与真实
   `ToolRegistry` 取面，不手搓 `tool_ids`——PLAN-006 要验证的是**既有投影的消费结果**
   （手搓面只服务 PLAN-003 的闸门单测）。
2. **探针不改语义**：六闸门与五段短路的探针只在**真实代码路径的读取点**记一笔
   （记录型标量 / 记录型代理），被探测对象仍是既有实现，判定逻辑一行未改。
3. **注册表隔离**：内置声明在注册期快照可用性（`channel_tools_enabled` 决定
   `channel.feishu.send` 的代码态），故凡需要「通道工具在声明面」的用例必须重建注册表
   单例——由 `tools_on` / `planning_gates_on` / `action_chain_on` 三个开关夹具统一承担
   （`tests/v24/conftest.py` 同款手法，跨目录夹具不能复用，故在此重声明）。

两个 `RUN_KIND_*` 常量按原样再导出：用例侧统一以 `support.RUN_KIND_*` 取（不另立字面量）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
)
from app.core.settings import get_settings
from app.models.goal import SubGoalSpec
from app.models.tool import ToolSurface
from app.repositories import action_repository
from app.services.action.planner import GateSnapshot
from app.services.action.registry import get_capability_registry
from app.services.tool import registry as tool_registry_module
from app.services.tool.context import ToolContext
from app.services.tool.executor import ToolExecutor
from app.services.tool.normalizer import ObservationNormalizer
from app.services.tool.permission import ToolPermissionGate
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.surface import ToolSurfaceResolver
from app.services.tool.validator import ParamValidator

NOW = datetime(2026, 9, 16, 12, 0, 0)
USER = "plan6-user"
GOAL_ID = "plan6-goal"

REMINDER_CREATE = "builtin.reminder.create"
REMINDER_CANCEL = "builtin.reminder.cancel"
MEMORY_SAVE = "builtin.memory.save"
NOTIFICATION_SEND = "builtin.notification.send"
SEARCH_QUERY = "builtin.search.query"
ENV_QUERY = "world.env.query"
CHANNEL_SEND = "channel.feishu.send"

UNRESOLVABLE_TOOL = "world.object.teleport"

ON_SURFACE_TOOL = REMINDER_CREATE

FROZEN_FUTURE = NOW + timedelta(hours=2)

GATE_ORDER: tuple[str, ...] = (
    "ambiguous_params",
    "capability_unavailable",
    "duplicate",
    "quota_exceeded",
    "effect_already_satisfied",
)
"""五闸门的固定判定序（`planner.evaluate_gates` 的短路序，Task Detail §4.2.3）。"""

NAMED_GATE_CHECKS: tuple[str, ...] = ("_check_g3", "_check_g4", "_check_g6")
"""六闸门中**具名函数**的三道（其余三道是 `evaluate_gates` 内的内联判定）。"""

GATE_LABEL_BY_CHECK: dict[str, str] = {
    "_check_g3": "capability_unavailable",
    "_check_g4": "duplicate",
    "_check_g6": "effect_already_satisfied",
}
"""具名闸门函数 → 日志刻度名（取自 §4.2.3 的闸门表；`_check_g6` 亦承载 `target_not_found`）。"""

SEGMENT_ORDER: tuple[str, ...] = (
    "resolve",
    "permission",
    "validate",
    "invoke",
    "normalize",
)
"""`ToolExecutor.run` 的五段短路固定序（Task Detail §4.2.4）。"""


# --- 夹具 ---------------------------------------------------------------------


def reset_tool_registry(monkeypatch) -> None:
    """注册表单例归零（声明期 Flag 快照不跨用例泄漏）；`monkeypatch` 负责用例后还原。"""
    monkeypatch.setattr(tool_registry_module, "_registry", None)
    get_settings.cache_clear()


@pytest.fixture
def isolated_tool_registry(monkeypatch):
    """工具注册表单例隔离：用例前归零、用例后还原（声明期 Flag 快照不跨用例泄漏）。"""
    reset_tool_registry(monkeypatch)
    yield tool_registry_module
    get_settings.cache_clear()


@pytest.fixture
def tools_on(monkeypatch, override_settings):
    """规划期开关面 + 通道可用（需要「通道工具在声明面」的用例显式开启）。

    `feishu_enabled` 的必填配置一并注入：通道可用性是 `channel.feishu.send` 声明态的唯一来源
    （`builtin._channel_status` 读注册期快照），缺配置即 `disabled`，T4 的语义就落不到
    run_profile / part_of_day 维度上。凭据是测试占位值，不接入真实飞书
    （AGENTS.md：密钥只从环境读，不入库不入源码）。
    """
    reset_tool_registry(monkeypatch)
    override_settings(
        plan_tool_required="true",
        feishu_enabled="true",
        feishu_app_id="plan6-app",
        feishu_app_secret="plan6-secret",
        feishu_verification_token="plan6-token",
        feishu_encrypt_key="plan6-encrypt",
        world_enabled="false",
        observability_persist_enabled="false")
    return True


@pytest.fixture
def planning_gates_on(monkeypatch, override_settings):
    """规划期闸门用例的开关面（编排常开 + 工具总闸 on，世界/记忆/反思关闭）。"""
    reset_tool_registry(monkeypatch)
    override_settings(
        plan_tool_required="true",
        world_enabled="false",
        observability_persist_enabled="false")
    return True


@pytest.fixture
def action_chain_on(monkeypatch, override_settings):
    """执行链用例的开关面：行动总闸 + 工具四子闸全开（校验 / 权限 / 观测 / 记忆）。

    同时开保留的策略位 `plan_tool_required`：Step 6 的两层校验对照（规划期弱校验 vs
    执行期强校验）需要规划期真的做弱校验，否则对照不成立。
    """
    reset_tool_registry(monkeypatch)
    override_settings(
        action_max_active_per_user="5",
        plan_tool_required="true",
        world_enabled="false",
        action_memory_policy_enabled="false",
        observability_persist_enabled="false",
        action_outbox_enabled="false")
    return True


@pytest.fixture
def repo_write_probe(monkeypatch):
    """`action_repository` 写面探针（L3 的「零 DB 写」可判定化）。"""
    probe = RepoWriteProbe()
    original_save = action_repository.save_record
    original_outbox = action_repository.save_record_with_outbox

    def _save(record):
        probe.records.append((record.id, record.status))
        return original_save(record)

    def _save_with_outbox(record, outbox_payload, idempotency_key):
        probe.outbox.append(idempotency_key)
        return original_outbox(record, outbox_payload, idempotency_key)

    monkeypatch.setattr(action_repository, "save_record", _save)
    monkeypatch.setattr(action_repository, "save_record_with_outbox", _save_with_outbox)
    return probe


# --- 工具面 -------------------------------------------------------------------


def builtin_registry() -> ToolRegistry:
    """全量内置声明注册表（10 条；`channel.feishu.send` 的代码态随通道可用性派生）。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def tool_context(
    *,
    now: datetime | None = NOW,
    run_kind: str = RUN_KIND_AUTONOMOUS_TICK,
    part_of_day: str | None = None,
    settings=None,
) -> ToolContext:
    """面解析用的 `ToolContext`：日时段经世界事实注入（`part_of_day` 维度的唯一输入面）。"""
    world = {} if part_of_day is None else {"part_of_day": part_of_day}
    return ToolContext(
        user_id=USER,
        now=now,
        settings=settings if settings is not None else get_settings(),
        run_kind=run_kind,
        world=world,
    )


def resolve_surface(
    registry: ToolRegistry | None = None,
    *,
    run_kind: str = RUN_KIND_AUTONOMOUS_TICK,
    ctx: ToolContext | None = None,
    settings=None,
) -> ToolSurface:
    """真实面投影（零桩）：`ToolSurfaceResolver` 的同输入同输出产物。"""
    resolved_settings = settings if settings is not None else get_settings()
    resolved_ctx = ctx if ctx is not None else tool_context(run_kind=run_kind, settings=resolved_settings)
    resolved_registry = registry if registry is not None else builtin_registry()
    return ToolSurfaceResolver(resolved_registry, resolved_settings).resolve(
        run_kind, resolved_ctx
    )


def excluded_reason(surface: ToolSurface, tool_id: str) -> str | None:
    """该工具在面上被剔除的理由（`None` 表示在面上或未知工具）。"""
    for entry in surface.excluded:
        if entry.get("tool_id") == tool_id:
            return None if entry.get("reason") is None else str(entry["reason"])
    return None


def spec(index: int = 1, *, tool_id: str | None = None, kind: str = "tool", **overrides) -> SubGoalSpec:
    """工具步构造器：默认与 `builtin.reminder.create` 绑定的 `create_reminder` 一步。"""
    capability = overrides.pop("capability", "create_reminder")
    payload = {
        "index": index,
        "description": f"步骤{index}",
        "capability": capability,
        "params": overrides.pop("params", {"content": "该休息了"}),
        "criteria": overrides.pop(
            "criteria", {"type": "action_succeeded", "capability": capability}
        ),
        "tool_id": tool_id,
        "kind": kind,
    }
    payload.update(overrides)
    return SubGoalSpec.model_validate(payload)


class RegistryReadProbe:
    """闸门 5 的只读证据（D1）：记录对注册表的每一次调用名。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.calls: list[str] = []

    def resolve(self, tool_id: str):
        self.calls.append("resolve")
        return self.registry.resolve(tool_id)

    def __getattr__(self, name: str):
        self.calls.append(name)
        return getattr(self.registry, name)


def registry_snapshot(registry: ToolRegistry) -> tuple:
    """注册表只读快照（声明 / 生命周期 / 健康度 / 运行期禁用四层，与顺序无关地可比）。"""
    return (
        tuple((item.id, item.status) for item in registry.list()),
        tuple(sorted(registry.runtime_disabled_ids())),
        tuple(
            (tool_id, health.model_dump(mode="json"))
            for tool_id, health in registry.health().items()
        ),
        tuple(
            (descriptor.tool_id, descriptor.status)
            for descriptor in registry.describe(enabled_only=False)
        ),
    )


# --- 五闸门探针 ---------------------------------------------------------------


class RecordedCount(int):
    """`snapshot.active_count` 的记录型整数：在 `>=` 读取点记一笔。"""

    def __new__(cls, value: int, log: list[str], name: str):
        instance = super().__new__(cls, value)
        instance.log = log
        instance.name = name
        return instance

    def __ge__(self, other) -> bool:
        self.log.append(self.name)
        return int(self) >= other


class RecordedIntent:
    """`evaluate_gates` 的鸭子类型入参：在 `confidence` 读取点记一笔。

    `evaluate_gates` 只消费 `confidence` / `action_type` / `params` / `dedupe_key` 四个字段，
    故探针无需伪装完整 `ActionIntent`；**真实 `ActionIntent`** 的端到端路径另有用例覆盖
    （`test_plan006_chain.py` 的具名闸门函数探针走的就是真实意图与真实快照）。
    """

    def __init__(
        self,
        log: list[str],
        *,
        action_type: str,
        params: dict,
        dedupe_key: str,
        confidence: str,
    ) -> None:
        self.log = log
        self.action_type = action_type
        self.params = params
        self.dedupe_key = dedupe_key
        self._confidence = confidence

    @property
    def confidence(self) -> str:
        self.log.append("ambiguous_params")
        return self._confidence


class GateOrderProbe:
    """五闸门读取点探针：在**每一段的真实读取点**记一笔，不替换任何判定逻辑。

    五闸门在真实源码里是 `evaluate_gates` 内的五段短路——三道具名函数
    （`_check_g3` / `_check_g4` / `_check_g6`）与两道内联判定（`ambiguous_params` /
    `quota_exceeded`）。内联两段没有独立函数可打桩，故用记录型标量
    在它们的唯一读取点取证；具名三段经 `install_named_gates` 包一层同刻度记录。探针不改判定
    （`evaluate_gates` 与三个 `_check_*` 的判断本体一行未动），只把五段的**经过事实**变成可断言序列。
    """

    def __init__(self) -> None:
        self.log: list[str] = []

    def install_named_gates(self, monkeypatch) -> None:
        """把三道具名闸门函数的调用点并入同一份日志（刻度合成五闸门全序）。"""
        from app.services.action import planner

        for check_name, label in GATE_LABEL_BY_CHECK.items():
            original = getattr(planner, check_name)

            def _spy(*args, _original=original, _label=label, **kwargs):
                self.log.append(_label)
                return _original(*args, **kwargs)

            monkeypatch.setattr(planner, check_name, _spy)

    def settings(
        self, *, max_active: int = 5, dedupe_hours: int = 24
    ) -> SimpleNamespace:
        return SimpleNamespace(
            action_max_active_per_user=max_active,
            action_dedupe_window_hours=dedupe_hours,
        )

    def snapshot(
        self,
        *,
        registry=None,
        active_count: int = 0,
        max_active: int = 5,
        world_available: bool = True,
        records: list[dict] | None = None,
        active_object_names: list[str] | None = None,
        active_reminder_titles: list[str] | None = None,
    ) -> GateSnapshot:
        return GateSnapshot(
            settings=self.settings(max_active=max_active),
            registry=registry if registry is not None else get_capability_registry(),
            records=list(records or []),
            active_count=RecordedCount(active_count, self.log, "quota_exceeded"),
            world_available=world_available,
            active_object_names=list(active_object_names or []),
            active_reminder_titles=list(active_reminder_titles or []),
            now=NOW,
        )

    def intent(
        self,
        *,
        action_type: str = "create_reminder",
        params: dict | None = None,
        dedupe_key: str = "plan:plan6-goal:1:1",
        confidence: str = "confident",
    ) -> RecordedIntent:
        return RecordedIntent(
            self.log,
            action_type=action_type,
            params=params if params is not None else {"content": "该休息了"},
            dedupe_key=dedupe_key,
            confidence=confidence,
        )


# --- 五段短路探针 -------------------------------------------------------------


class SegmentLog:
    """五段短路与六闸门的调用序记录（同一份列表，供两类断言共用）。"""

    def __init__(self) -> None:
        self.log: list[str] = []


class _RegistryProxy:
    """`resolve` 段探针：`ToolExecutor._is_unavailable` 的注册表读取点记一笔。"""

    def __init__(self, registry: ToolRegistry, log: SegmentLog) -> None:
        self.registry = registry
        self.log = log

    def get(self, tool_id: str):
        self.log.log.append("resolve")
        return self.registry.get(tool_id)

    def __getattr__(self, name: str):
        return getattr(self.registry, name)


class _PermissionGateProxy:
    """`permission` 段探针：`ToolPermissionGate.evaluate` 的唯一调用点记一笔。"""

    def __init__(self, gate: ToolPermissionGate, log: SegmentLog) -> None:
        self.gate = gate
        self.log = log

    def evaluate(self, definition, invocation, snapshot):
        self.log.log.append("permission")
        return self.gate.evaluate(definition, invocation, snapshot)

    def build_snapshot(self, user_id, now, settings=None):
        return self.gate.build_snapshot(user_id, now, settings)

    def __getattr__(self, name: str):
        return getattr(self.gate, name)


class _ValidatorProxy:
    """`validate` 段探针：`ParamValidator.validate` 的唯一调用点记一笔。"""

    def __init__(self, validator: ParamValidator, log: SegmentLog) -> None:
        self.validator = validator
        self.log = log

    def validate(self, definition, params, ctx):
        self.log.log.append("validate")
        return self.validator.validate(definition, params, ctx)

    def __getattr__(self, name: str):
        return getattr(self.validator, name)


class _NormalizerProxy:
    """`normalize` 段探针：`ObservationNormalizer.normalize` 的唯一调用点记一笔。"""

    def __init__(self, normalizer: ObservationNormalizer, log: SegmentLog) -> None:
        self.normalizer = normalizer
        self.log = log

    def normalize(self, definition, raw, meta):
        self.log.log.append("normalize")
        return self.normalizer.normalize(definition, raw, meta)

    def __getattr__(self, name: str):
        return getattr(self.normalizer, name)


class _CapabilityExecutorProxy:
    """`invoke` 段探针（也是「是否触达能力」的唯一判据）：`run` 的调用点记一笔。"""

    def __init__(self, executor, log: SegmentLog) -> None:
        self.executor = executor
        self.log = log

    async def run(self, step, ctx):
        self.log.log.append("invoke")
        return await self.executor.run(step, ctx)

    def __getattr__(self, name: str):
        return getattr(self.executor, name)


def instrumented_executor(
    registry: ToolRegistry,
    capability_executor,
    settings,
    log: SegmentLog,
    *,
    health=None,
) -> ToolExecutor:
    """**真实** `ToolExecutor`，只把五段各自的入口包一层记录（判定逻辑零改动）。"""
    return ToolExecutor(
        _RegistryProxy(registry, log),
        _CapabilityExecutorProxy(capability_executor, log),
        settings=settings,
        validator=_ValidatorProxy(ParamValidator(), log),
        normalizer=_NormalizerProxy(ObservationNormalizer(), log),
        health=health,
        permission_gate=_PermissionGateProxy(ToolPermissionGate(settings), log),
    )


def executor_class_factory(log: SegmentLog):
    """`action_engine.ToolExecutor` 的替身工厂：形状与引擎的构造点逐参数一致。"""

    def _factory(registry, capability_executor, *, settings=None, health=None):
        return instrumented_executor(
            registry, capability_executor, settings, log, health=health
        )

    return _factory


class RepoWriteProbe:
    """`action_repository` 写面记录：`records` 是 `(record_id, status)`，`outbox` 是幂等键。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self.outbox: list[str] = []

    @property
    def total(self) -> int:
        return len(self.records) + len(self.outbox)

    def distinct_record_ids(self) -> set[str]:
        return {record_id for record_id, _status in self.records}
