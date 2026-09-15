"""V2.4.0 工具结果记忆分层（TOOL-008 / architecture.md §7.4、§8.3）。

边界表把 V9 行动记忆的 `action_type` 键泛化为 `memory_policy_key`，并落地三条硬纪律：
读类工具强制不沉淀、`ext.api.*` 默认不沉淀、`user.*` 默认不沉淀。
`classify` 的六步短路中 ①② 优先于边界表配置——硬纪律不可被配置绕过。

`row_for` / `classify` / `to_candidates` / `has_memory_effect` 均为纯函数（零 IO）；
写入侧只经既有 `memory_policy` R1~R8（零豁免）与 `memory_repository`，
本模块不新增记忆表、不扩记忆类型域；内容由 `TOOL_MEMORY_TEMPLATES` 渲染，
无模板或渲染缺参返回空串，调用方据此跳过沉淀（不写半成品内容）。

**边界表 importance 档与政策阈值的既有落差（保持现状，属预期）**：

- 0.5 档（`builtin.reminder.cancel` / `world.object.create`）在默认
  `memory_importance_threshold = 0.6` 下被 **R6 拒收**——档位取自文档 §2.2 表，本模块不
  上调，也不为工具通道破例；部署侧下调阈值即可放行，行为由配置单点决定。
- `source = "ai_inferred"` 的行（`builtin.notification.send` / `channel.feishu.send`）被
  **R1 拒收**：AI 推测不入库是政策硬规则，与档位无关。
- 模板文案不得含未消解人称代词（R8 会拒收），`TOOL_MEMORY_TEMPLATES` 的措辞受此约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.character.asuna.action import REMINDER_BIRTHDAY_KEYWORDS
from app.character.asuna.tool import render
from app.models.action import ActionRecord
from app.models.memory import MemoryCandidate
from app.models.tool import ToolDefinition

DEPOSIT_SKIP = "skip"

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"

DELIVERABLE_STATUSES: tuple[str, ...] = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_TIMEOUT)

REASON_READ_ONLY = "read_only_tool"
REASON_UNTRUSTED_SOURCE = "untrusted_source"
REASON_NO_POLICY_ROW = "no_policy_row"
REASON_POLICY_SKIP = "policy_skip"
REASON_POLICY_DECLINED = "policy_declined"
REASON_POLICY_DEPOSIT = "policy_deposit"

READ_SIDE_EFFECT = "read"

UNTRUSTED_NAMESPACES: tuple[str, ...] = ("ext.api", "user")

UNTRUSTED_KEY_PREFIXES: dict[str, str] = {"ext.api.": "ext.api", "user.": "user"}

MEMORY_CONTENT_MAX_CHARS = 120
FAILED_IMPORTANCE_FLOOR = 0.6
DEFAULT_CONFIDENCE = 0.8
DEFAULT_MEMORY_TYPE = "important_event"
DEFAULT_IMPORTANCE = 0.5
DEFAULT_SOURCE = "user_derived"

BIRTHDAY_WEIGHTED_KEYS: tuple[str, ...] = ("builtin.reminder.create",)
BIRTHDAY_KEYWORD_PARAM = "content"
BIRTHDAY_PROMOTED_TYPE = "user_fact"
BIRTHDAY_PROMOTED_IMPORTANCE = 0.8

BOUNDARY_TABLE: dict[str, dict[str, Any]] = {
    "builtin.reminder.create": {
        "deposit": True,
        "memory_type": "important_event",
        "importance": 0.7,
        "source": "user_derived",
    },
    "builtin.reminder.cancel": {
        "deposit": True,
        "memory_type": "important_event",
        "importance": 0.5,
        "source": "user_derived",
    },
    "builtin.memory.save": {"deposit": DEPOSIT_SKIP, "source": "user_stated"},
    "world.object.create": {
        "deposit": True,
        "memory_type": "user_preference",
        "importance": 0.5,
        "source": "user_derived",
    },
    "world.object.move": {"deposit": False},
    "world.object.use": {"deposit": False},
    "world.env.query": {"deposit": False},
    "builtin.search.query": {"deposit": False},
    "builtin.notification.send": {
        "deposit": True,
        "memory_type": "important_event",
        "importance": 0.6,
        "source": "ai_inferred",
    },
    "channel.feishu.send": {
        "deposit": True,
        "memory_type": "important_event",
        "importance": 0.6,
        "source": "ai_inferred",
    },
}

BOUNDARY_PREFIX_TABLE: dict[str, dict[str, Any]] = {
    "ext.api.": {"deposit": False},
    "user.": {"deposit": False},
}


@dataclass(frozen=True)
class MemoryDecision:
    """分类决策（§4.1）：`deposit` 为 True / False / "skip"，其余字段仅沉积路径有值。"""

    deposit: bool | str
    reason: str
    memory_type: str | None = None
    importance: float | None = None
    source: str | None = None
    template_key: str | None = None


def tool_id_of(record: ActionRecord) -> str | None:
    """行动记录的首个工具 id（工具路径由 TOOL-003 写入 `steps[].tool_id`）。"""
    for step in record.steps:
        tool_id = step.get("tool_id")
        if tool_id:
            return str(tool_id)
    return None


def policy_key_for(record: ActionRecord, defn: ToolDefinition | None = None) -> str | None:
    """边界表查询键：声明的 `memory_policy_key` 优先，取不到则退回 `tool_id`。"""
    if defn is not None:
        return defn.memory_policy_key or defn.id
    return tool_id_of(record)


def namespaces_for(key: str | None, defn: ToolDefinition | None = None) -> frozenset[str]:
    """命名空间候选集：声明与键前缀两处独立取证，任一命中不信命名空间即拒。"""
    namespaces: set[str] = set()
    if defn is not None:
        namespaces.add(defn.namespace)
    if key:
        for prefix, namespace in UNTRUSTED_KEY_PREFIXES.items():
            if key.startswith(prefix):
                namespaces.add(namespace)
                break
        else:
            namespaces.add(key.split(".")[0])
    return frozenset(namespaces)


def is_read_only(defn: ToolDefinition | None) -> bool:
    """硬纪律①判定：`side_effects ⊆ {read}`；空集视为无写事实声明，按读类保守处理。"""
    if defn is None:
        return False
    return set(defn.side_effects) <= {READ_SIDE_EFFECT}


def delivery_status(record: ActionRecord) -> str:
    """投递态：`succeeded` / `failed` / `timeout` / 其余未执行态（原样回传状态值）。"""
    status = str(record.status)
    if status == STATUS_TIMEOUT:
        return STATUS_TIMEOUT
    if status not in (STATUS_SUCCEEDED, STATUS_FAILED):
        return status
    if status == STATUS_FAILED:
        if record.gate_reason:
            return "unexecuted"
        if _step_failure_kind(record) == STATUS_TIMEOUT:
            return STATUS_TIMEOUT
    return status


def has_memory_effect(record: ActionRecord) -> bool:
    """幂等：`effects` 中已登记 `kind == "memory"` 则跳过重复投递（V9 既有泛化）。"""
    result = record.result or {}
    for effect in result.get("effects", []):
        if effect.get("kind") == "memory":
            return True
    return False


def _step_failure_kind(record: ActionRecord) -> str | None:
    for step in record.steps:
        result = step.get("result") or {}
        kind = result.get("failure_kind") or (result.get("payload") or {}).get(
            "failure_kind"
        )
        if kind:
            return str(kind)
    return None


def _birthday_weighted(record: ActionRecord) -> bool:
    content = str(record.params.get(BIRTHDAY_KEYWORD_PARAM, ""))
    return any(keyword in content for keyword in REMINDER_BIRTHDAY_KEYWORDS)


def _shape(
    decision: MemoryDecision, record: ActionRecord, key: str, failed: bool
) -> tuple[str, float, str]:
    memory_type = decision.memory_type or DEFAULT_MEMORY_TYPE
    importance = (
        DEFAULT_IMPORTANCE if decision.importance is None else decision.importance
    )
    source = decision.source or DEFAULT_SOURCE
    if key in BIRTHDAY_WEIGHTED_KEYS and _birthday_weighted(record):
        memory_type = BIRTHDAY_PROMOTED_TYPE
        importance = max(importance, BIRTHDAY_PROMOTED_IMPORTANCE)
    if failed:
        memory_type = DEFAULT_MEMORY_TYPE
        importance = max(importance, FAILED_IMPORTANCE_FLOOR)
    return memory_type, importance, source


class ToolMemoryPolicy:
    """工具记忆边界表：行查询 + 六步分类 + 候选构造（纯函数、零 IO）。"""

    def __init__(
        self,
        rows: dict[str, dict[str, Any]] | None = None,
        prefix_rows: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._rows = dict(BOUNDARY_TABLE if rows is None else rows)
        self._prefix_rows = dict(
            BOUNDARY_PREFIX_TABLE if prefix_rows is None else prefix_rows
        )

    def row_for(self, policy_key: str) -> dict[str, Any] | None:
        """精确键优先，其次最长前缀（`ext.api.*` / `user.*`）；未知键返回 `None`。"""
        row = self._rows.get(policy_key)
        if row is not None:
            return dict(row)
        for prefix in sorted(self._prefix_rows, key=len, reverse=True):
            if policy_key.startswith(prefix):
                return dict(self._prefix_rows[prefix])
        return None

    def classify(
        self, record: ActionRecord, defn: ToolDefinition | None = None
    ) -> MemoryDecision:
        """六步短路：①② 硬纪律优先于边界表配置（配置不可违背）。"""
        key = policy_key_for(record, defn)
        if is_read_only(defn):
            return MemoryDecision(False, REASON_READ_ONLY)
        if namespaces_for(key, defn) & set(UNTRUSTED_NAMESPACES):
            return MemoryDecision(False, REASON_UNTRUSTED_SOURCE)
        row = None if key is None else self.row_for(key)
        if row is None:
            return MemoryDecision(False, REASON_NO_POLICY_ROW)
        template_key = row.get("template_key") or key
        if row.get("deposit") == DEPOSIT_SKIP:
            return MemoryDecision(
                DEPOSIT_SKIP,
                REASON_POLICY_SKIP,
                source=row.get("source"),
                template_key=template_key,
            )
        if not row.get("deposit"):
            return MemoryDecision(False, REASON_POLICY_DECLINED)
        return MemoryDecision(
            True,
            REASON_POLICY_DEPOSIT,
            memory_type=str(row.get("memory_type", DEFAULT_MEMORY_TYPE)),
            importance=float(row.get("importance", DEFAULT_IMPORTANCE)),
            source=str(row.get("source", DEFAULT_SOURCE)),
            template_key=template_key,
        )

    def to_candidates(
        self, record: ActionRecord, defn: ToolDefinition | None = None
    ) -> list[MemoryCandidate]:
        """行动记录 → 0..1 条记忆候选（单行动单记忆）；未执行态与拒沉淀键返回空列表。"""
        status = delivery_status(record)
        if status not in DELIVERABLE_STATUSES:
            return []
        decision = self.classify(record, defn)
        if decision.deposit is not True:
            return []
        key = decision.template_key or policy_key_for(record, defn) or ""
        failed = status in (STATUS_FAILED, STATUS_TIMEOUT)
        content = render(key, record.params, failed=failed)
        if not content:
            return []
        memory_type, importance, source = _shape(decision, record, key, failed)
        return [
            MemoryCandidate(
                action="save",
                type=memory_type,
                content=content[:MEMORY_CONTENT_MAX_CHARS],
                importance=importance,
                confidence=DEFAULT_CONFIDENCE,
                source=source,
            )
        ]

    def has_memory_effect(self, record: ActionRecord) -> bool:
        return has_memory_effect(record)


_DEFAULT_POLICY = ToolMemoryPolicy()


def get_tool_memory_policy() -> ToolMemoryPolicy:
    """模块级默认边界表（纯数据，无环境依赖，无重置语义）。"""
    return _DEFAULT_POLICY
