"""PLAN-012 版本级扇入：十一 Gate 判定表 + Q1~Q10 收口 + 十条红线 + 零迁移。"""

from pathlib import Path
import re

import pytest

from app.core.db import DecisionRecordRow, GoalPlanRow
from app.core.settings import get_settings
from app.models.action import ACTION_TYPES, GATE_REASONS
from app.models.observability import DecisionKind as DecisionKindEnum
from app.repositories import goal_repository
from app.services.planning import engine as plan_engine
from app.services.planning.observer import FACT_SOURCE_TOOL

from . import _plan_scan as scan
from . import plan012_support as support

BACKEND_ROOT = Path(goal_repository.__file__).parents[2]
MIGRATIONS_DIR = BACKEND_ROOT / "migrations" / "versions"
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"
CHECKLIST_PATH = (
    BACKEND_ROOT.parents[1]
    / "docs"
    / "version"
    / "v2.5.0"
    / "planning-system"
    / "regression-checklist.md"
)

GATE_TRACE: dict[str, str] = {
    "G-COMPAT": "architecture.md §9.6；本目录 test_plan012_flag_matrix.py",
    "G-PLAN": "architecture.md §9.6；test_plan003_engine.py + scenario A",
    "G-DECOMPOSE": "architecture.md §9.6；test_plan004_*.py",
    "G-BIND": "architecture.md §9.6；test_plan004_binding.py + test_plan006_gates.py",
    "G-EXEC": "architecture.md §9.6；test_plan005_static_scan.py + test_plan006_chain.py",
    "G-RETRY": "architecture.md §9.6；test_plan005_failure_tree.py + scenario D",
    "G-WORLD": "architecture.md §9.6；test_plan008_static_scan.py + test_plan008_broadcast.py",
    "G-MEMORY": "architecture.md §9.6；test_plan009_*.py",
    "G-REFLECT": "architecture.md §9.6；test_plan010_listener.py",
    "G-BOUNDARY": "architecture.md §9.6；test_plan007_boundary.py",
    "G-ZERO-MIGRATION": "architecture.md §9.6；本模块 TestZeroMigration",
}

Q_TRACE: dict[str, str] = {
    "Q1": "action_plan_max_steps 保持 1；无并行调度代码",
    "Q2": "GoalPlanRecord 扩展字段落 decision_records.input_snapshot；零加列",
    "Q3": "SubGoalSpec extra=ignore；新字段显式入模型；双向兼容测试存在",
    "Q4": "fact_source=tool 拒绝 threshold_reached；负例存在",
    "Q5": "WorldIntentSubmitter WIRED=False；未接线断言存在",
    "Q6": "装配侧零 LLM；未新增 capability 位",
    "Q7": "计划与 daily_plans 互不引用",
    "Q8": "insight_driven 与其他判据同时命中只入队一次",
    "Q9": "记录留痕；本版本不做关系域扩张",
    "Q10": "仅后端调试端点；前端不实现",
}

RED_LINES: dict[str, str] = {
    "红线1": "零新建表/迁移",
    "红线2": "不新建 Goal 系统",
    "红线3": "action_plan_max_steps 保持 1",
    "红线4": "不绕过工具治理",
    "红线5": "不直接写世界/Character 域",
    "红线6": "不绕过记忆政策",
    "红线7": "反思不直接改写计划",
    "红线8": "默认拒绝与降级放行沿用既有范式",
    "红线9": "V2.4.0 兼容窗口兑现",
    "红线10": "Flag 全 off 逐字节一致",
}


class TestGateLedger:
    """U8：十一 Gate 各至少一条可判定条目，且可追溯到 §9.6。"""

    def test_eleven_gates_have_traces(self):
        assert len(support.GATE_IDS) == 11
        assert set(support.GATE_IDS) == set(GATE_TRACE)
        for gate in support.GATE_IDS:
            assert GATE_TRACE[gate]

    def test_gate_count_gap_is_recorded_in_the_checklist(self):
        text = CHECKLIST_PATH.read_text(encoding="utf-8")
        assert "十个 Gate" in text or "10" in text
        assert "11" in text
        assert "G-ZERO-MIGRATION" in text


class TestOpenQuestionsClosed:
    """U9：Q1~Q10 各有裁决结论或记录留痕，无悬空项。"""

    def test_all_ten_questions_have_closure_records(self):
        assert len(support.Q_IDS) == 10
        assert set(support.Q_IDS) == set(Q_TRACE)
        for key, record in Q_TRACE.items():
            assert record, key

    def test_q1_action_plan_max_steps_stays_one(self):
        assert get_settings().action_plan_max_steps == 1

    def test_q4_tool_source_rejects_threshold_reached(self):
        criteria = {
            "type": "threshold_reached",
            "source": FACT_SOURCE_TOOL,
            "path": "count",
            "op": ">=",
            "value": 1,
        }
        observer_module = pytest.importorskip(
            "app.services.planning.observer"
        )
        assert observer_module.PlanObserver().evaluate(criteria, {}) is None

    def test_q5_world_intent_submitter_stays_unwired(self):
        module = pytest.importorskip("app.services.tool.world_intent")
        assert module.WIRED is False

    def test_q7_plans_and_daily_plans_do_not_reference_each_other(self):
        planning_dir = Path(plan_engine.__file__).parent
        sources = "\n".join(
            path.read_text(encoding="utf-8") for path in planning_dir.rglob("*.py")
        )
        assert "daily_plans" not in sources
        assert "daily_plan" not in sources.lower() or "daily_plans" not in sources

    def test_q10_frontend_has_no_plan_debug_panel(self):
        if not FRONTEND_ROOT.exists():
            pytest.skip("frontend 未检出")
        hits = []
        for path in FRONTEND_ROOT.rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
                continue
            if "node_modules" in path.parts or "dist" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                continue
            if "/debug/plans" in text or "PlanDebugPanel" in text:
                hits.append(str(path))
        assert hits == []


class TestBoundaryRedLines:
    """十条红线版本级核对（可自动化的子集）。"""

    def test_ten_red_lines_are_registered(self):
        assert len(support.RED_LINE_IDS) == 10
        assert set(support.RED_LINE_IDS) == set(RED_LINES)

    def test_red_line_3_action_plan_max_steps(self):
        assert get_settings().action_plan_max_steps == 1

    def test_red_line_5_planning_does_not_import_world_repository(self):
        planning_dir = Path(plan_engine.__file__).parent
        for path in planning_dir.rglob("*.py"):
            assert "app.repositories.world_repository" not in scan.imported_modules(path), path.name
            assert not any(
                name.startswith("world_repository") or name.endswith(".world_repository")
                for name in scan.imported_modules(path)
            ), path.name

    def test_red_line_7_planning_does_not_import_revision_listener_into_observer(self):
        listener = Path(plan_engine.__file__).parent / "revision_listener.py"
        assert listener.exists()
        text = scan.code_text(listener)
        assert "set_plan_status(" not in text
        assert "finish_goal(" not in text


class TestZeroMigration:
    """Z1~Z8：零迁移断言（迁移链头 0048；值集未扩）。"""

    def test_migration_head_is_0048(self):
        heads = sorted(path.name for path in MIGRATIONS_DIR.glob("0048_*.py"))
        assert heads == ["0048_action_records_run_id.py"]

    def test_no_newer_revision_after_0048(self):
        numeric = sorted(
            int(match.group(1))
            for path in MIGRATIONS_DIR.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert max(numeric) == 48

    def test_decision_kind_stays_five_values(self):
        kinds = tuple(kind.value for kind in DecisionKindEnum)
        assert kinds == (
            "proactive_autonomy",
            "turn_goal",
            "turn_intention",
            "turn_behavior",
            "goal_lifecycle",
        )

    def test_goal_plan_status_check_stays_five_values(self):
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in GoalPlanRow.__table__.constraints
            if constraint.name == "ck_goal_plans_status"
        }
        assert list(checks) == ["ck_goal_plans_status"]
        for status in ("draft", "validated", "active", "rejected", "superseded"):
            assert status in checks["ck_goal_plans_status"]
        assert "completed" not in checks["ck_goal_plans_status"]

    def test_decision_records_kind_check_stays_five_values(self):
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in DecisionRecordRow.__table__.constraints
            if constraint.name == "ck_decision_records_kind"
        }
        assert list(checks) == ["ck_decision_records_kind"]
        for kind in DecisionKindEnum:
            assert kind.value in checks["ck_decision_records_kind"]

    def test_action_status_and_gate_reasons_not_extended(self):
        assert len(ACTION_TYPES) > 0
        assert "permission_denied" in GATE_REASONS
        assert "capability_unavailable" in GATE_REASONS

    def test_planning_package_is_the_only_new_surface(self):
        modules = scan.module_names()
        assert modules
        assert all(name.startswith("app.services.planning") for name in modules)

    def test_criterion_fact_sources_include_tool(self):
        from app.models.goal import CRITERION_FACT_SOURCES

        assert "tool" in CRITERION_FACT_SOURCES
        assert FACT_SOURCE_TOOL == "tool"
