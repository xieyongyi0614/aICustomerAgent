"""PLAN-001 ↔ PLAN-002 范围标记：本包内「已落地」与「仍不得预埋」的可判定分界。

这些断言是「只做本任务范围」红线（Task Detail §1.2 Non-Scope、§10.3「无代码骨架污染」）
的可执行形式，属**有意的契约变更留痕**：后续任务落地对应产物时必须**显式更新本模块**，
更新动作本身就是「范围越界已评审」的证据，而非本模块回归失败。

| 标记 | 归属 | 状态 |
|---|---|---|
| `v25_*` Flag 与参数 | PLAN-002 | ✅ 已落地（13 Flag + 14 参数，总闸默认 off） |
| `SubGoalSpec` 7 个新字段 | PLAN-002 | ✅ 已落地（19 字段快照） |
| `GoalPlanRecord` 4 个新字段 | PLAN-002 | ✅ 已落地（12 字段快照） |
| `CRITERION_FACT_SOURCES` 第四值 | PLAN-002 | ✅ 已落地（四值） |
| `app/models/plan.py` / `settings/plan.py` | PLAN-002 | ✅ 已落地 |
| 计划域装配 / 引擎模块（`context.py` / `engine.py`） | PLAN-003 | ✅ 已落地 |
| 计划域拆解模块（`decompose.py`） | PLAN-004 | ✅ 已落地 |
| 计划域调度 / 执行 / 观测 / 修订模块（四模块） | PLAN-005 | ✅ 已落地 |
| 重规划监听器（`revision_listener.py`） | PLAN-010 | ⛔ 仍不得预埋 |

PLAN-002 落地时的改动仅限本模块中「尚不存在」类断言翻转为「已存在」类断言 + 新增字段
快照（原计划见 PLAN-001 Task Detail 的标记表）。

PLAN-003 落地时按同一纪律改动本模块：`context.py` / `engine.py` 由「仍不得预埋」翻转为
「已落地」，`decompose.py` 与 PLAN-005 五模块维持「不得预埋」（计划面四函数进 `goal_repository`
调用白名单的留痕见 `goal_contract` 模块文档 §9）。

PLAN-004 落地时按同一纪律改动本模块：`decompose.py` 翻转为「已落地」，PLAN-005 五模块
**维持「不得预埋」**（拆解不调度 / 不执行 / 不观测 / 不修订——Task Detail §1.2 Non-Scope）。
同任务的角色资产放行面扩容（`app.character.asuna.action`）见
`test_plan001_static_scan.py::ALLOWED_CHARACTER_IMPORT_MODULES`。

PLAN-005 落地时按同一纪律改动本模块：`scheduler.py` / `executor_bridge.py` / `observer.py` /
`revision.py` 四者翻转为「已落地」，`revision_listener.py` **维持「不得预埋」**——反思监听器
是 PLAN-010 的产物（Task Detail §5.5 边界：本任务只定义 `insight_driven` 理由码与判定入口，
不读 Insight、不注册监听器），故本任务不预埋该模块。

PLAN-006 落地时按同一纪律改动本模块：**无模块翻转**（Task Detail §4.1.1 明确「本任务不新建
模块」，是对 PLAN-003 闸门 5/6 与 PLAN-005 执行桥的**契约补齐与断言加固**）。故本模块的
「已落地 / 不得预埋」分界保持不变，只新增一条**接口级**标记：闸门 5/6 的两个判定函数
（§6.1 冻结签名）以模块级纯函数形式落地于既有 `engine.py` 内，`revision_listener.py`
**维持「不得预埋」**。

PLAN-007 落地时按同一纪律改动本模块：同样**无模块翻转**（本任务对既有
`autonomy_policy.py` / `autonomy_engine.py` 做增量接线，`decision_pipeline.py` 零改动），
只新增一条**接口级**标记：`plan_facts` 的调制函数与装配函数落地于两个既有模块内
（§4.1.2 组件划分），`revision_listener.py` **维持「不得预埋」**。
同一落地的契约演进项：`PolicySnapshot.plan_facts` 由原定六键扩为**七键**
（新增标量 `current_action_type`，见 `autonomy_policy.PLAN_FACTS_KEYS` 的留痕）。

PLAN-008 落地时按同一纪律改动本模块：同样**无模块翻转**（§4.1.1 明确「本任务不新建模块」：
World 源九段补进既有 `context.py`、终态广播补进既有 `observer.py`，`world_engine` /
`world_repository` / `outbox_consumer` / `event_bridge` 零改动），只新增两条**接口级**标记：
World 读白名单 `WORLD_READ_ENTRIES` 与终态广播映射 `TERMINAL_BROADCAST_OUTCOMES`。
同一落地的契约演进项（两条，均属「逐段可降级」的直接后果）：

- `PLAN_DEGRADED_REASONS` 由六值扩为**十三值**：World 源由三段一体细化为九段逐段可降级，
  插入七条世界段标记（见 `context.WORLD_READ_ENTRIES` 与 `test_plan003_context.py`
  `TestDegradedRegistry` 的留痕）。
- `_WorldSource` 由三元组扩为**五字段**（新增 ① 时间上下文与逐段降级清单）：
  `_assemble_world` 的返回值由 `(source, degraded)` 收成单一载体（内部结构，非公开契约）。
"""

from pathlib import Path

from app.core.settings import Settings, get_settings
from app.models.goal import (
    CRITERION_FACT_SOURCES,
    GoalPlanRecord,
    SubGoalSpec,
)
from app.services.planning import goal_contract

PLAN_002_SETTINGS_FLAGS = (
    "v25_planning_enabled",
    "v25_plan_context_enabled",
    "v25_plan_step_binding_enabled",
    "v25_plan_scheduler_enabled",
    "v25_plan_execution_enabled",
    "v25_plan_observation_enabled",
    "v25_plan_revision_enabled",
    "v25_plan_memory_enabled",
    "v25_plan_reflection_enabled",
    "v25_plan_world_feedback_enabled",
    "v25_plan_autonomy_enabled",
    "v25_plan_tool_required",
    "v25_plan_debug_enabled",
)

PLAN_002_SETTINGS_PARAMS = (
    "v25_plan_max_steps",
    "v25_plan_max_depth",
    "v25_plan_step_max_attempts",
    "v25_plan_revision_budget",
    "v25_plan_ttl_hours",
    "v25_plan_step_cooldown_minutes",
    "v25_plan_observation_window_minutes",
    "v25_plan_context_memory_limit",
    "v25_plan_context_insight_limit",
    "v25_plan_llm_profile",
    "v25_plan_replan_min_confidence",
    "v25_plan_reflection_min_samples",
    "v25_plan_memory_importance_floor",
    "v25_plan_context_digest_enabled",
)

PLAN_002_SUB_GOAL_FIELDS = (
    "tool_id",
    "kind",
    "retry_policy",
    "on_failure",
    "expected_effects",
    "observation_keys",
    "binding_reason",
)

PLAN_002_GOAL_PLAN_FIELDS = (
    "trigger",
    "context_digest",
    "revision_of",
    "evidence_refs",
)

PLAN_005_LANDED_MODULES = (
    "scheduler.py",
    "executor_bridge.py",
    "observer.py",
    "revision.py",
)

PLAN_010_PENDING_MODULES = ("revision_listener.py",)

PLAN_003_LANDED_MODULES = ("context.py", "engine.py")

PLAN_004_LANDED_MODULES = ("decompose.py",)

PLAN_006_LANDED_INTERFACES = (
    "_evaluate_tool_resolvable",
    "_evaluate_tool_on_surface",
)
"""PLAN-006 §6.1 冻结的两个闸门判定接口（落于既有 `engine.py`，不新建模块）。"""

PLAN_007_POLICY_INTERFACES = (
    "_apply_plan_adjustments",
    "_intention_action_type",
)
"""PLAN-007 §6.3 的调制接口（落于既有 `autonomy_policy.py`，不新建模块）。"""

PLAN_007_ENGINE_INTERFACES = (
    "_collect_plan_facts",
    "_latest_active_plan",
    "_plan_schedule_context",
    "_blocked_steps",
    "_last_advanced_at",
)
"""PLAN-007 §6.2 的装配接口（落于既有 `autonomy_engine.py`，装配点唯一）。"""

PLAN_008_CONTEXT_INTERFACES = ("WORLD_READ_ENTRIES",)
"""PLAN-008 §6.1 的世界只读白名单（落于既有 `context.py`，九段装配的触达面）。"""

PLAN_008_OBSERVER_INTERFACES = ("TERMINAL_BROADCAST_OUTCOMES", "broadcast_goal_terminal")
"""PLAN-008 §6.3 的终态广播接口（落于既有 `observer.py`，迁移路径唯一调用点）。"""


def _backend_root() -> Path:
    return Path(goal_contract.__file__).parents[3]


def _planning_dir() -> Path:
    return Path(goal_contract.__file__).parent


def test_plan_002_settings_are_embedded_and_the_master_stays_off():
    settings = get_settings()
    declared = {name for name in Settings.model_fields if name.startswith("v25_")}
    assert declared == set(PLAN_002_SETTINGS_FLAGS) | set(PLAN_002_SETTINGS_PARAMS)
    assert len(PLAN_002_SETTINGS_FLAGS) == 13
    assert len(PLAN_002_SETTINGS_PARAMS) == 14
    assert settings.v25_planning_enabled is False
    assert settings.v25_plan_tool_required is True
    assert (_backend_root() / "app" / "core" / "settings" / "plan.py").exists()


def test_sub_goal_spec_carries_the_plan_002_fields_in_declared_order():
    fields = tuple(SubGoalSpec.model_fields)
    assert fields[:12] == (
        "index",
        "description",
        "capability",
        "params",
        "criteria",
        "depends_on",
        "parent_index",
        "status",
        "attempt_count",
        "last_observed_at",
        "last_attempt_at",
        "failure_note",
    )
    assert fields[12:] == PLAN_002_SUB_GOAL_FIELDS
    assert len(fields) == 19


def test_goal_plan_record_carries_the_plan_002_fields_in_declared_order():
    assert tuple(GoalPlanRecord.model_fields) == (
        "id",
        "goal_id",
        "version",
        "status",
        "sub_goals",
        "rejection_reason",
        "created_at",
        "updated_at",
    ) + PLAN_002_GOAL_PLAN_FIELDS


def test_plan_domain_model_module_is_present():
    assert (_backend_root() / "app" / "models" / "plan.py").exists()


def test_plan_execution_modules_are_landed():
    """PLAN-005 契约演进（原「不得预埋」翻转为「已落地」）：四模块存在。"""
    missing = [name for name in PLAN_005_LANDED_MODULES if not (_planning_dir() / name).exists()]
    assert missing == []


def test_plan_reflection_listener_stays_unplanted():
    """PLAN-010 的产物：本任务只定义 `insight_driven` 理由码，不预埋监听器。"""
    present = [name for name in PLAN_010_PENDING_MODULES if (_planning_dir() / name).exists()]
    assert present == []


def test_planning_engine_modules_are_landed():
    missing = [name for name in PLAN_003_LANDED_MODULES if not (_planning_dir() / name).exists()]
    assert missing == []


def test_plan_decompose_module_is_landed():
    missing = [name for name in PLAN_004_LANDED_MODULES if not (_planning_dir() / name).exists()]
    assert missing == []


def test_plan_006_lands_the_two_gate_predicates_without_a_new_module():
    """PLAN-006 产物面：两个闸门判定接口在位，且**没有**为工具治理新建模块。"""
    from app.services.planning import engine as engine_mod

    missing = [
        name for name in PLAN_006_LANDED_INTERFACES if not hasattr(engine_mod, name)
    ]
    assert missing == []
    assert not (_planning_dir() / "tool.py").exists()
    assert not (_planning_dir() / "tool_gate.py").exists()


def test_plan_007_lands_the_two_faces_without_a_new_module():
    """PLAN-007 产物面：调制 + 装配函数在位，且**没有**为自治集成新建模块。"""
    from app.application import autonomy_engine
    from app.services import autonomy_policy

    assert [
        name
        for name in PLAN_007_POLICY_INTERFACES
        if not hasattr(autonomy_policy, name)
    ] == []
    assert [
        name
        for name in PLAN_007_ENGINE_INTERFACES
        if not hasattr(autonomy_engine, name)
    ] == []
    assert not (_planning_dir() / "autonomy.py").exists()
    assert not (_planning_dir() / "autonomy_feed.py").exists()


def test_plan_007_packet_contract_is_seven_bounded_keys():
    """PLAN-007 的契约演进留痕：`plan_facts` 七键（原六键 + 当前步动作身份）。"""
    from app.services import autonomy_policy

    assert autonomy_policy.PLAN_FACTS_KEYS == (
        "active_goal_id",
        "plan_version",
        "current_step",
        "current_action_type",
        "steps_total",
        "blocked_steps",
        "last_advanced_at",
    )
    assert "plan_facts" in autonomy_policy.PolicySnapshot.__dataclass_fields__


def test_plan_008_lands_the_two_faces_without_a_new_module():
    """PLAN-008 产物面：世界只读白名单 + 终态广播接口在位，且**没有**为世界集成新建模块。"""
    from app.services.planning import context as context_mod
    from app.services.planning import observer as observer_mod

    assert [
        name for name in PLAN_008_CONTEXT_INTERFACES if not hasattr(context_mod, name)
    ] == []
    assert [
        name for name in PLAN_008_OBSERVER_INTERFACES if not hasattr(observer_mod, name)
    ] == []
    assert not (_planning_dir() / "world.py").exists()
    assert not (_planning_dir() / "world_integration.py").exists()
    assert not (_planning_dir() / "world_broadcast.py").exists()


def test_plan_008_degraded_registry_adds_only_world_segment_codes():
    """PLAN-008 的契约演进留痕：`degraded` 值集扩七条世界段标记，其余逐字不变。"""
    from app.services.planning import context as context_mod

    codes = context_mod.PLAN_DEGRADED_REASONS
    assert len(codes) == 13
    assert codes[0] == "world_disabled"
    assert codes[1:8] == (
        "world_time_unavailable",
        "world_environment_unavailable",
        "world_location_unavailable",
        "world_objects_unavailable",
        "world_events_unavailable",
        "world_brief_unavailable",
        "world_context_unavailable",
    )
    assert codes[8:] == (
        "scene_unavailable",
        "situation_unavailable",
        "memory_unavailable",
        "reflection_unavailable",
        "surface_unavailable",
    )


def test_planning_package_holds_only_landed_modules():
    modules = sorted(
        path.name for path in _planning_dir().rglob("*.py") if "__pycache__" not in path.parts
    )
    assert modules == [
        "__init__.py",
        "context.py",
        "decompose.py",
        "engine.py",
        "executor_bridge.py",
        "goal_contract.py",
        "observer.py",
        "revision.py",
        "scheduler.py",
    ]


def test_plan_002_fourth_criterion_source_is_embedded():
    assert CRITERION_FACT_SOURCES == ("world", "state", "memory", "tool")
