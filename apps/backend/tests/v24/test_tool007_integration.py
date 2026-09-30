"""TOOL-007 §6.2：`_build_snapshot` 世界事实注入与零 diff 断言。

覆盖：装配接入（WorldContextBuilder → ToolContext）、工具面投影消费预读事实、
`world_engine` / `outbox_consumer` 源码零 diff、维护步序列零改动、
世界域与角色域表结构零改动。
"""

import ast
import hashlib
from pathlib import Path

import pytest

from app.application import action_engine, world_engine
from app.core.db import Base
from app.models.action import ActionIntent
from app.services.action.planner import GateSnapshot, assemble_plan, resolve_surface
from app.services.tool import registry as tool_registry
from app.services.tool import world_context as world_context_module
from app.services.tool.context import WORLD_ENABLED_KEY, ToolContext
from app.services.tool.surface import WORLD_FACTS_REASON
from app.services.tool.world_context import WorldContextBuilder, apply_world_facts
from tests.v24.tool007_support import (
    NOW,
    USER,
    seed_all,
    tool_context,
    world_settings,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

FROZEN_SOURCES: dict[str, str] = {
    # 再冻结（2026-09-28）：CAS 门控去掉（固化常开）+ 删除 world_interpreter_enabled /
    # world_memory_bridge_enabled / world_household_autoseed_enabled / world_enabled
    # （四者固化常开，门控点展开）。原 3bdcd4f4 在首次改动前已 stale。
    # services 归位声明（2026-09-30，批次 2）：`character_assets` → `engines/character`
    # 导入路径变更 —— 非 TOOL-007 改脏。原值 c57307c7。
    "app/application/world_engine.py": "f0ba90cbbdb068473a7890cd0c4c1e55d7f13eee17f04ab53c365e9a19c251fa",
    "app/application/outbox_consumer.py": "f6de9c06247820c39b9db9b41f07216c7764c037ff961030662a297ea0ec2dc1",
}
"""V2.4.0 TOOL-007 冻结摘要：世界模拟与 outbox 消费路径**零 diff**（改则本测试失败）。

`app/application/life_loop.py` 已从本表撤下（P2-1 在 `has_due` 调用侧合法新增到期口径排除），
其语义面由 `_maintenance_steps()` / `test_action_retry_substeps_unchanged` 持有——
冻结整文件哈希会把正常演进判成违规。
"""

EXPECTED_MAINTENANCE_STEPS: tuple[str, ...] = (
    "world_maintenance",
    "world_simulation",
    "action_retry",
    "action_schedule",
    "outbox_consume",
    "trigger_reconcile",
    "ledger_digest",
    "ledger_alert",
)
"""维护步序列（`_run_maintenance` 内按源码顺序的调度 kind）。
`action_expire`（TOOL-005 过期确认清理挂接点所在函数）是 `action_retry` 条目的子步，
见 `EXPECTED_ACTION_RETRY_SUBSTEPS`。`action_schedule` 为 v26 消费入口裁决（F.13）：
挂维护步、不进 autonomous_tick Profile。"""

EXPECTED_ACTION_RETRY_SUBSTEPS: tuple[str, ...] = ("action_retry", "action_expire")

WORLD_TABLES: dict[str, tuple[str, ...]] = {
    "worlds": (
        "id", "user_id", "name", "time_mode", "sim_time", "sim_last_advanced_at", "sim_rate",
        "current_location", "environment", "notes", "created_at", "updated_at",
        "owner_type", "owner_id",
    ),
    "world_entities": (
        "id", "world_id", "name", "aliases", "category", "location_id", "state", "quantity",
        "unit", "consumable", "properties", "status", "last_action_at", "created_at", "updated_at",
    ),
    "world_events": (
        "id", "world_id", "type", "title", "importance", "status", "started_at", "due_at",
        "completed_at", "payload", "source", "idempotency_key", "created_at", "updated_at",
    ),
    "world_snapshots": ("id", "world_id", "label", "state", "created_at"),
    "daily_plans": (
        "id", "user_id", "plan_date", "seq", "part_of_day", "start_minutes", "end_minutes",
        "activity", "location_id", "variability_source", "status", "routine_version", "note",
        "created_at", "updated_at",
    ),
    "user_situations": (
        "id", "user_id", "dimension", "summary", "intensity", "status", "source", "evidence",
        "detected_at", "valid_until", "updated_at",
    ),
}

CHARACTER_TABLES: dict[str, tuple[str, ...]] = {
    "character_state": (
        "user_id", "mood", "energy", "current_topic", "inner_state", "intensity", "cause",
        "last_event_at", "created_at", "updated_at",
    ),
    "relationship_state": (
        "user_id", "intimacy", "trust", "familiarity", "respect", "comfort", "tension", "stage",
        "conflict_status", "neglect_active", "last_interaction_at", "version", "created_at",
        "updated_at",
    ),
    "personality_state": (
        "id", "user_id", "character_id", "axis", "baseline", "current", "bound_min", "bound_max",
        "source_insight_id", "version", "updated_at", "created_at",
    ),
}


@pytest.fixture(autouse=True)
def _pin_action_engine_clock(monkeypatch):
    """`_build_snapshot` 无 `now` 形参，内部经 `action_engine._now()` 读真实墙钟。

    夹具的 `daily_plans` 按 `tool007_support.NOW` 的日期落键，故此处把该时间源钉到 `NOW`
    （测试侧 seam，不改生产签名），使 `current_block` 等日期派生事实不随真实日期滚更失配。
    """
    monkeypatch.setattr(action_engine, "_now", lambda: NOW)


# --- `_build_snapshot` 装配接入 ---------------------------------------------


def test_build_snapshot_degrades_when_preread_crashes(db_session_factory, monkeypatch, override_settings):
    override_settings()
    monkeypatch.setattr(
        world_context_module.WorldContextBuilder,
        "build",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("preread down")),
    )
    snapshot = action_engine._build_snapshot(USER, world_settings())
    assert snapshot.tool_context is None


def test_build_snapshot_survives_missing_world(db_session_factory, override_settings):
    override_settings()
    snapshot = action_engine._build_snapshot(USER, world_settings())
    assert snapshot.tool_context is not None
    assert snapshot.tool_context.world["world_enabled"] is True
    assert snapshot.tool_context.world["location"] is None
    assert world_engine.get_world(USER) is None


# --- 预读事实进入执行上下文（身份字段以执行上下文为准） ----------------------


def test_tool_context_for_execution_keeps_identity_and_takes_world_facts(db_session_factory, override_settings):
    override_settings()
    from app.services.action.registry import ExecutionContext

    preloaded = tool_context(
        world={"world_enabled": True, "location": "home.kitchen"},
        inventory=["牛奶"],
    )
    execution_ctx = ExecutionContext(
        user_id=USER, character_id="asuna", record_id="rec-9", now=NOW, settings=world_settings()
    )
    merged = action_engine._tool_context_for_execution(execution_ctx, preloaded)
    assert merged.record_id == "rec-9"
    assert merged.world["location"] == "home.kitchen"
    assert merged.inventory == ["牛奶"]
    assert merged.world_facts_enabled() is True


def test_tool_context_for_execution_without_preload_stays_empty():
    from app.services.action.registry import ExecutionContext

    execution_ctx = ExecutionContext(
        user_id=USER, character_id="asuna", record_id="rec-10", now=NOW, settings=world_settings()
    )
    merged = action_engine._tool_context_for_execution(execution_ctx, None)
    assert merged.world == {} and merged.inventory == []
    assert merged.world_facts_assembled() is False


# --- 工具面投影消费预读事实 --------------------------------------------------


def _snapshot_with_tool_context(tool_ctx: ToolContext, settings) -> GateSnapshot:
    snapshot = GateSnapshot(settings=settings, registry=None, now=NOW)
    snapshot.world_available = True
    snapshot.tool_context = tool_ctx
    return snapshot


def test_resolve_surface_uses_preloaded_world_facts(db_session_factory, monkeypatch, override_settings):
    override_settings()
    seed_all()
    settings = world_settings()
    snapshot = _snapshot_with_tool_context(
        action_engine._build_snapshot(USER, settings).tool_context, settings
    )
    surface = resolve_surface(snapshot)
    registry = tool_registry.get_tool_registry()
    assert registry is not None
    world_ids = {item.id for item in registry.list(namespace="world")}
    assert world_ids & set(surface.tool_ids)


def test_resolve_surface_trims_world_when_facts_disabled(monkeypatch, override_settings):
    override_settings()
    settings = world_settings()
    facts = {
        "world": {WORLD_ENABLED_KEY: False},
        "inventory": [],
        "situations": [],
        "scene": {},
        "relationship": {},
    }
    ctx = apply_world_facts(ToolContext(user_id=USER, now=NOW, settings=settings), facts)
    surface = resolve_surface(_snapshot_with_tool_context(ctx, settings))
    reasons = {item["tool_id"]: item["reason"] for item in surface.excluded}
    registry = tool_registry.get_tool_registry()
    assert registry is not None
    world_ids = {item.id for item in registry.list(namespace="world")}
    assert all(reasons[tool_id] == WORLD_FACTS_REASON for tool_id in world_ids)


def test_assemble_plan_uses_preloaded_facts_for_tool_choice(db_session_factory, monkeypatch, override_settings):
    override_settings(
        )
    seed_all()
    settings = world_settings()
    snapshot = action_engine._build_snapshot(USER, settings)
    intent = ActionIntent(
        action_type="move_object",
        confidence="confident",
        params={"object": "苹果", "location": "厨房"},
        dedupe_key="tool007:assemble",
    )
    plan = assemble_plan(intent, snapshot, NOW)
    assert plan is not None
    assert plan.steps[0].capability == "world_action"
    assert plan.steps[0].action == "move"


# --- §6.2 零 diff 断言 -------------------------------------------------------


@pytest.mark.parametrize("relative,digest", sorted(FROZEN_SOURCES.items()))
def test_frozen_sources_have_zero_diff(relative, digest):
    """世界模拟与 outbox 消费路径零 diff（TOOL-007 硬约束）。

    摘要比对前做**行尾归一（LF）**：CRLF 检出不应造成假失败（P2-4）。
    """
    data = (BACKEND_ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == digest, (
        f"{relative} 被修改：世界模拟 / outbox 消费器在本任务内必须零 diff"
    )


def test_outbox_consumer_has_no_tool_dependency():
    """消费器零改动且对工具层无感知：不 import 任何 `app.services.tool` 模块。"""
    source = (BACKEND_ROOT / "app/application/outbox_consumer.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not [name for name in imported if name.startswith("app.services.tool")]
    assert not [name for name in imported if name.startswith("app.models.tool")]


def _maintenance_steps() -> tuple[str, ...]:
    """从 `life_loop._run_maintenance` 源码按序抽取维护步名（AST，非正则）。"""
    source = (BACKEND_ROOT / "app/application/life_loop.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    steps: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != "_run_maintenance":
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            if name in ("_mark_maintenance", "_record_maintenance_run"):
                if call.args and isinstance(call.args[0], ast.Constant):
                    steps.append((call.lineno, str(call.args[0].value)))
    ordered = [name for _, name in sorted(steps)]
    deduped: list[str] = []
    for name in ordered:
        if not deduped or deduped[-1] != name:
            deduped.append(name)
    return tuple(deduped)


def test_maintenance_step_sequence_is_unchanged():
    """维护步序列：含 F.13 裁决新增的 action_schedule 挂载点。"""
    assert _maintenance_steps() == EXPECTED_MAINTENANCE_STEPS


def test_action_retry_substeps_unchanged():
    """action 维护子步序列零改动（`action_expire` 内挂接 TOOL-005 过期清理，顺序不变）。"""
    source = (BACKEND_ROOT / "app/application/life_loop.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    substeps = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in EXPECTED_ACTION_RETRY_SUBSTEPS
    ]
    assert tuple(dict.fromkeys(substeps)) == EXPECTED_ACTION_RETRY_SUBSTEPS


@pytest.mark.parametrize("table,columns", sorted(WORLD_TABLES.items()))
def test_world_domain_tables_unchanged(table, columns):
    assert tuple(column.name for column in Base.metadata.tables[table].columns) == columns


@pytest.mark.parametrize("table,columns", sorted(CHARACTER_TABLES.items()))
def test_character_domain_tables_unchanged(table, columns):
    assert tuple(column.name for column in Base.metadata.tables[table].columns) == columns


def test_no_new_tables_in_metadata():
    """零新建表：本任务不新增任何迁移/表（含"为 WorldIntent 建表"这一反模式）。

    计数随版本演进推进（当前 44：FEISHU-010 的 `feishu_dedupe_ledger`）。
    """
    from tests.support.schema_pins import SCHEMA_TABLE_COUNT

    assert set(WORLD_TABLES) <= set(Base.metadata.tables)
    assert len(Base.metadata.tables) == SCHEMA_TABLE_COUNT


def test_world_engine_has_no_tool_layer_dependency():
    """世界引擎对工具层无感知（反向依赖不存在）：零 diff 的语义补充。"""
    source = (BACKEND_ROOT / "app/application/world_engine.py").read_text(encoding="utf-8")
    assert "services.tool" not in source
    assert "models.tool" not in source
    assert "deferred_world_op" not in source


def test_preread_reads_are_read_only_module_functions():
    """预读只调只读函数：world_context 中出现的 world_engine 调用全部命中只读白名单。"""
    source = (BACKEND_ROOT / "app/services/tool/world_context.py").read_text(encoding="utf-8")
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "world_engine"
    }
    assert called
    assert all(name.startswith(("get_", "list_", "build_", "find_")) for name in called)
