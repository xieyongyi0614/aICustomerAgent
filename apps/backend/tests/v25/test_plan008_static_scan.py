"""PLAN-008 Step 5 / Step 6 静态扫描：G-WORLD 四条护栏 + 关系域零直写 + 零迁移（I1 / I2 / I7 / I10）。

覆盖 Task Detail §9.2 I1 / I2 / I10、§10.1 G-WORLD、§10.3 零迁移；对应 §8 Step 5 与 Step 6 的静态半边。

四条扫描（§8 Step 5.1~5.4）

| # | 断言 | 判定面 |
|---|---|---|
| 1 | 零 `world_repository` 导入 | 全包 `imported_modules` 面（G-WORLD 的原文） |
| 2 | 零 `world_engine` 写函数调用 | `world_engine.<attr>` 属性面 ⊆ `WORLD_READ_ENTRIES` 只读白名单 |
| 3 | 零 `character_state` / `personality_state` / `relationship_*` 写入 | 代码 token 面 + 导入面 + `goal_repository` 白名单（PLAN-001 复核） |
| 4 | 零 `WorldIntentSubmitter` 调用 | 代码 token 面 + 导入面（运行时断言见 `test_plan008_intent.py`） |

**G-WORLD 的读白名单是「只读」而非「全禁」**：九段世界事实装配必须读世界（§4.2.1），故断言形态为
`world_engine` 属性集合 ⊆ `context.WORLD_READ_ENTRIES`（五项只读入口），而不是「零 `world_engine`
引用」。写函数（`create_*` / `move_*` / `set_*` / `advance_time` / `ensure_world` / `run_*` /
`seed_*` / `expire_*` / `trigger_*` / `consume_object` / `discard_object` / `record_*` / `merge_*`）
一个都不在白名单内，且另有 §8 Step 5.2 的写面逐名断言。

**零迁移（I10）**：迁移链头仍为 `0046`；`world_events.type` 无 CHECK 值域（`sa.String()`），
故「值域未扩」的可判定形态是「事件类型产出集合未变」（`{goal_completed, interest_emerged}`，
见 `test_plan008_broadcast.py`）+「本任务零新增迁移文件」。
"""

import re
from pathlib import Path

from app.models.observability import DecisionKind
from app.repositories import goal_repository
from app.services.planning import context as plan_context
from app.services.planning import goal_contract

from . import _plan_scan as scan
from . import plan008_support as support

MIGRATION_HEAD = "0049"

RELATIONSHIP_WRITE_MODULE_PREFIXES = (
    "app.repositories.relationship",
    "app.services.action.relationship_bridge",
)

CHARACTER_DOMAIN_FORBIDDEN_TOKENS = (
    "character_state",
    "personality_state",
    "relationship_state",
    "relationship_events",
    "relationship_repository",
    "relationship_event_repository",
    "relationship_bridge",
    "commit_relationship_update",
)

WORLD_WRITE_ATTRIBUTE_NAMES = frozenset(support.WORLD_WRITE_FACE) | {
    "ensure_world",
    "build_time_context",
    "get_location_context",
    "get_full_state",
    "snapshot",
    "restore_snapshot",
    "run_debug_tick",
    "build_debug_simulation",
    "build_debug_plan",
    "build_debug_situations",
    "event_quota_drop_snapshot",
    "reset_event_quota_drop_snapshot",
    "get_available_consumables",
}
"""`world_engine` 中**不在**只读白名单内的成员（写面 + 写能力包装 + debug 面）。

后两者虽非「状态写入」，但均非 §4.2.1 的九段读入口，一律不得在装配路径出现（白名单之外的
一律禁止，避免「顺手多读一个」演化成隐性契约）。
"""

WORLD_WRITE_TOKEN_NAMES: tuple[str, ...] = support.WORLD_WRITE_FACE + ("ensure_world",)
"""token 面扫描用的写动词子集（`code_text` 无分隔符，故只收**不会与既有词形撞车**的名字：
`advance_time` / `trigger_due_events` 等全部命中词表，而 `snapshot` 类 debug 名会与
`PlanProbeSnapshot` 撞车，故只走属性面断言）。"""


class TestGWorldStaticScan:
    """§8 Step 5.1 / 5.2：零 `world_repository` 导入；零世界写函数调用。"""

    def test_no_world_repository_import_anywhere_in_the_package(self):
        offenders = {
            path.name: sorted(
                module
                for module in scan.imported_modules(path)
                if "world_repository" in module
            )
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}

    def test_no_world_repository_token_in_executable_code(self):
        offenders = {
            path.name: scan.code_violations(path, ("world_repository",))
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}

    def test_world_engine_attributes_stay_within_the_read_allowlist(self):
        used: dict[str, list[str]] = {}
        for path in support.planning_modules():
            names = support.world_engine_attributes_in(path)
            extra = sorted(names - set(plan_context.WORLD_READ_ENTRIES))
            if extra:
                used[path.name] = extra
        assert used == {}

    def test_world_write_functions_are_never_named(self):
        offenders: dict[str, list[str]] = {}
        for path in support.planning_modules():
            hits = sorted(
                support.world_engine_attributes_in(path) & WORLD_WRITE_ATTRIBUTE_NAMES
            )
            if hits:
                offenders[path.name] = hits
        assert offenders == {}

    def test_no_world_write_token_in_executable_code(self):
        forbidden = WORLD_WRITE_TOKEN_NAMES
        offenders = {
            path.name: scan.code_violations(path, forbidden)
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}

    def test_read_allowlist_excludes_every_write_entry(self):
        assert set(plan_context.WORLD_READ_ENTRIES) & WORLD_WRITE_ATTRIBUTE_NAMES == set()
        assert len(plan_context.WORLD_READ_ENTRIES) == 5

    def test_scanner_catches_a_synthetic_world_write(self, tmp_path):
        """扫描器自测：合成违规必须被抓到（否则断言退化为空断言）。"""
        sample = tmp_path / "_synthetic_world_violation.py"
        sample.write_text(
            "import json\n"
            "from app.application import world_engine\n"
            "from app.repositories import world_repository\n"
            "\n"
            "def leak(user_id):\n"
            "    world_engine.create_event(user_id, 'reminder', 'x')\n"
            "    world_engine.ensure_world(user_id)\n"
            "    return world_repository.list_events('w')\n",
            encoding="utf-8",
        )
        assert "world_repository" in scan.code_violations(sample, ("world_repository",))
        names = support.world_engine_attributes_in(sample)
        assert names == {"create_event", "ensure_world"}
        assert names - set(plan_context.WORLD_READ_ENTRIES) == names
        assert names & WORLD_WRITE_ATTRIBUTE_NAMES == names


class TestCharacterDomainBoundary:
    """§8 Step 5.3 / §6.4 E1~E3：零 Character 域写面（含关系域）。"""

    def test_no_character_or_personality_state_writes(self):
        offenders = {
            path.name: scan.code_violations(
                path, ("character_state", "personality_state")
            )
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}

    def test_no_relationship_write_surface(self):
        offenders = {
            path.name: scan.code_violations(path, CHARACTER_DOMAIN_FORBIDDEN_TOKENS)
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}

    def test_relationship_modules_are_not_imported(self):
        offenders = {
            path.name: sorted(
                module
                for module in scan.imported_modules(path)
                if module.startswith(RELATIONSHIP_WRITE_MODULE_PREFIXES)
            )
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}

    def test_no_character_domain_table_literals(self):
        literals = ("character_state", "personality_state", "relationship_state", "relationship_events")
        offenders = {
            path.name: scan.literal_violations(path, literals)
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}

    def test_goal_status_write_face_is_still_the_declared_one(self):
        """E5 复核（PLAN-001 已列，本任务复述）：`character_goals` 只经 `goal_repository` 状态写面。"""
        allowed = set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS)
        offenders = {
            path.name: sorted(scan.goal_repository_call_names(path) - allowed)
            for path in support.planning_modules()
            if scan.goal_repository_call_names(path) - allowed
        }
        assert offenders == {}
        assert set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS) >= {
            "set_status",
            "finish_goal",
        }


class TestIntentSurfaceScan:
    """§8 Step 5.4：零 `WorldIntentSubmitter` 调用（静态半边）。"""

    def test_package_holds_no_intent_submitter_token(self):
        tokens = (
            "WorldIntentSubmitter",
            "world_intent",
            "WORLD_INTENT_TOOL_ID",
            "world.intent.submit",
        )
        offenders = {
            path.name: scan.code_violations(path, tokens)
            for path in support.planning_modules()
        }
        assert {name: hits for name, hits in offenders.items() if hits} == {}


class TestZeroMigration:
    """I10 / §10.3：迁移链头 0046、零新表新列、`world_events.type` 值域未扩。"""

    def test_migration_chain_head_is_still_0049(self):
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        numbered = sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert f"{max(numbered):04d}" == MIGRATION_HEAD

    def test_world_events_columns_are_unchanged(self):
        """零新列：`world_events` 的列集合逐字冻结（广播复用既有 `type` / `payload` / `source`）。"""
        from app.core.db import Base

        assert [column.name for column in Base.metadata.tables["world_events"].columns] == [
            "id",
            "world_id",
            "type",
            "title",
            "importance",
            "status",
            "started_at",
            "due_at",
            "completed_at",
            "payload",
            "source",
            "idempotency_key",
            "created_at",
            "updated_at",
        ]

    def test_world_simulation_tables_are_unchanged(self):
        from app.core.db import Base

        assert {
            name
            for name in Base.metadata.tables
            if name == "worlds" or name.startswith("world_")
        } == {"worlds", "world_entities", "world_events", "world_snapshots"}

    def test_world_events_type_has_no_check_value_set(self):
        """`world_events.type` 是自由字符串列（值域由**产出集合**界定，无 CHECK 可扩）。"""
        models = (support.repo_root() / "app" / "models" / "world.py").read_text(
            encoding="utf-8"
        )
        assert "type: str" in models
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        offenders = [
            path.name
            for path in versions.glob("*.py")
            if "ck_world_events_type" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_decision_kind_value_set_is_unchanged(self):
        assert tuple(kind.value for kind in DecisionKind) == (
            "proactive_autonomy",
            "turn_goal",
            "turn_intention",
            "turn_behavior",
            "goal_lifecycle",
        )

    def test_planning_package_holds_no_new_module_for_world_integration(self):
        """§4.1.1：本任务**不新建模块**（增量接线于既有 `context.py` / `observer.py`）。

        PLAN-009 落地后按同一纪律收编 `memory_policy.py`（该任务新建记忆边界表模块）。
        """
        names = sorted(
            path.name
            for path in scan.PLANNING_PACKAGE_DIR.rglob("*.py")
            if "__pycache__" not in path.parts
        )
        assert names == [
            "__init__.py",
            "context.py",
            "decompose.py",
            "engine.py",
            "executor_bridge.py",
            "goal_contract.py",
            "memory_policy.py",
            "observer.py",
            "revision.py",
            "revision_listener.py",
            "scheduler.py",
        ]


class TestRelationshipBoundary:
    """Step 6（Q9）静态半边：关系域效果只经既有工具效果通道，计划层零直写。

    **Q9 评估结论（本任务内记录，留痕即验收记录）**

    > 计划完成 → `goal_completed` 世界事件（`source=character`）→ 既有世界事件链路；
    > **本版本不追加关系域信号**。理由：关系域写入面（`relationship_state` /
    > `relationship_events`）的扩张需与 V8.5 关系演进、V2.2 情绪通道一并评估（关系阶段的
    > 三层钳制、当日正负影响配额、`stage_hysteresis` 迟滞都由那两个系统独占），本任务单方面
    > 加一条「陪用户完成了一件事」的信号会绕过这两个系统的参数面。故推后续版本，本版本仅留痕。
    > 关系域变化的既有通道：行动记录 → `outbox_consumer` 关系段 →
    > `relationship_bridge.deliver_action_signal`（门控 `action_relationship_enabled`，
    > 判定输入 `ACTION_RELATIONSHIP_MAP`）。运行时断言见
    > `test_plan008_world_paths.py::TestRelationshipChannel`。
    """

    def test_planning_never_writes_the_relationship_domain(self):
        for path in support.planning_modules():
            assert scan.code_violations(path, support.RELATIONSHIP_WRITE_TOKENS) == [], path.name

    def test_relationship_bridge_is_not_reachable_from_planning(self):
        root = support.repo_root() / "app"
        importers = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
            and "relationship_bridge" in path.read_text(encoding="utf-8")
        }
        assert not {name for name in importers if name.startswith("services/planning")}

    def test_relationship_write_repositories_are_not_reachable_from_planning(self):
        forbidden = ("app.repositories.relationship_repository", "app.repositories.relationship_event_repository")
        for path in support.planning_modules():
            assert not [
                module
                for module in scan.imported_modules(path)
                if module.startswith(forbidden)
            ], path.name

    def test_character_state_repositories_are_not_reachable_from_planning(self):
        forbidden_prefixes = (
            "app.repositories.character_state",
            "app.repositories.personality",
            "app.repositories.state",
        )
        for path in support.planning_modules():
            assert not [
                module
                for module in scan.imported_modules(path)
                if module.startswith(forbidden_prefixes)
            ], path.name
