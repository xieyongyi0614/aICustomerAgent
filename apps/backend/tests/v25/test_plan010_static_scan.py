"""PLAN-010 Step 7：边界守卫与零迁移静态断言。

Task Detail §8 Step 7 的三条静态红线（§10.2 / §10.3）：

1. `revision_listener.py` 零 `goal_repository` 写入 / 零工具注册表调用 / 零计划表写入。
2. 不在 `foreground` 关键路径：计划反思仍在 `reflection_check` 步与后台节拍里
   （本版本 Planning 侧反思接线**只有一处**）。
3. 零迁移：不建表 / 列 / 索引 / CHECK；`insights` 类型与 `scope` 值集未扩；
   `background_jobs.job_type` 未扩（复用既有 `goal_planning`）。
"""

import io
import re
import tokenize
from pathlib import Path

from app.core.settings import get_settings
from app.models.reflection import (
    EVIDENCE_CHANNEL_PLAN,
    InsightScope,
    InsightType,
)
from app.repositories import goal_repository
from app.services.planning import goal_contract
from app.services.planning import revision_listener as listener_mod
from app.services.reflection import evidence as reflection_evidence

from . import _plan_scan as scan
from . import plan010_support as support

MIGRATION_HEAD = "0047"

LISTENER_PATH = scan.PLANNING_PACKAGE_DIR / "revision_listener.py"
EVIDENCE_PATH = support.repo_root() / "app" / "services" / "reflection" / "evidence.py"
REFLECTION_DIR = EVIDENCE_PATH.parent

INSIGHT_TYPE_VALUES = (
    "belief",
    "preference",
    "pattern",
    "capability_note",
    "usage_preference",
    "interaction_calibration",
)

INSIGHT_SCOPE_VALUES = ("user", "relationship", "world")

REFLECTION_CONSUMERS = (
    "app/services/development/policy.py",
    "app/services/relationship_narrative.py",
    "app/services/world/event_bridge.py",
)


def _plan_section_source() -> str:
    return EVIDENCE_PATH.read_text(encoding="utf-8").split("# --- PLAN-010", 1)[1]


def _tokens(source: str):
    return list(tokenize.generate_tokens(io.StringIO(source).readline))


def _app_sources() -> list[Path]:
    return [
        path
        for path in (support.repo_root() / "app").rglob("*.py")
        if "__pycache__" not in path.parts
    ]


class TestListenerBoundary:
    """§10.2：监听器的唯一写副作用是 `enqueue_planning`。"""

    def test_no_goal_repository_writes(self):
        calls = scan.goal_repository_call_names(LISTENER_PATH)
        assert calls == {"get_goal", "list_active_plans"}
        assert calls & set(goal_contract.PLANNING_WRITE_FUNCTION_NAMES) == set()
        assert calls.isdisjoint(
            {"create_plan", "set_plan_status", "set_plan_rejection", "update_plan_progress"}
        )

    def test_no_orm_or_session_surface(self):
        text = scan.code_text(LISTENER_PATH)
        for fragment in scan.FORBIDDEN_CODE_FRAGMENTS:
            assert fragment not in text, fragment
        for name in scan.FORBIDDEN_CODE_NAMES:
            assert name not in text, name
        assert "SessionLocal" not in text
        assert not scan.import_from_names(LISTENER_PATH).get("app.core.db")

    def test_no_sql_literals(self):
        assert (
            scan.literal_violations(LISTENER_PATH, scan.FORBIDDEN_SQL_LITERAL_FRAGMENTS)
            == []
        )

    def test_no_tool_registry_or_health_surface(self):
        imports = scan.imported_modules(LISTENER_PATH)
        assert not [module for module in imports if "tool" in module]
        text = scan.code_text(LISTENER_PATH)
        for token in (
            "ToolRegistry",
            "get_tool_registry",
            "ToolHealthTracker",
            "health",
            "trip",
            "disable",
            "surface",
        ):
            assert token not in text, token

    def test_the_only_planning_side_effect_is_enqueue_planning(self):
        text = scan.code_text(LISTENER_PATH)
        assert text.count("goal_planning.enqueue_planning") == 1
        assert text.count("goal_planning.TRIGGER_REPLAN") == 1
        assert "enqueue_job" not in text
        assert "background_job_repository" not in text

    def test_no_second_priority_algorithm_or_step_reordering(self):
        assert scan.sort_key_sources(LISTENER_PATH) == []
        assert "compute_priority" not in scan.code_text(LISTENER_PATH)

    def test_no_prompt_or_llm_surface(self):
        text = scan.code_text(LISTENER_PATH)
        for token in (
            "_build_messages",
            "build_structured_chain",
            "ChatPromptTemplate",
            "HumanMessage",
            "SystemMessage",
            "llm_gateway",
            "get_llm",
        ):
            assert token not in text, token
        imports = scan.imported_modules(LISTENER_PATH)
        for prefix in ("app.chains", "langchain", "app.core.llm_factory"):
            assert not [module for module in imports if module.startswith(prefix)]


class TestEvidenceBoundary:
    """§10.2 / §6.2 D3：证据是**投影**——计划通道零写入、零新表。"""

    def test_the_plan_section_only_reads(self):
        section = _plan_section_source()
        text = "".join(
            token.string
            for token in _tokens(section)
            if token.type not in (tokenize.COMMENT, tokenize.STRING)
        )
        for fragment in scan.FORBIDDEN_CODE_FRAGMENTS:
            assert fragment not in text, fragment
        for name in ("GoalRow", "GoalPlanRow"):
            assert name not in text, name
        assert "goal_repository.list_active_plans" in text
        assert "goal_repository.list_plans" in text
        for write_call in (
            "goal_repository.create_plan",
            "goal_repository.set_plan_status",
            "goal_repository.update_plan_progress",
        ):
            assert write_call not in text, write_call

    def test_no_new_evidence_table_is_introduced(self):
        from app.core.db import Base

        assert sorted(
            name for name in Base.metadata.tables if "evidence" in name
        ) == ["evidence_links"]
        assert sorted(
            name for name in Base.metadata.tables if name.startswith("plan")
        ) == []

    def test_the_plan_channel_uses_the_existing_upper_bounds(self):
        assert reflection_evidence.TOOL_EVIDENCE_WINDOW_DAYS == 7
        assert reflection_evidence.TOOL_EVIDENCE_MAX_MEMBERS == 12
        assert reflection_evidence.TOOL_EVIDENCE_RECORD_SCAN_LIMIT == 200
        source = EVIDENCE_PATH.read_text(encoding="utf-8")
        plan_section = source.split("# --- PLAN-010", 1)[1]
        assert "= 7" not in plan_section
        assert "= 12" not in plan_section
        assert "= 200" not in plan_section

    def test_the_plan_channel_does_not_touch_the_reflector(self):
        """§5.5：`reflector` 的 Insight 产出路径零改动（计划窗经 `insight_types` 复用既有类型闸）。"""
        reflector_path = REFLECTION_DIR / "reflector.py"
        text = reflector_path.read_text(encoding="utf-8")
        assert "PLAN_WINDOW" not in text
        assert "plan_evidence" not in text


class TestUniqueWiring:
    """§10.3：本版本 Planning 侧反思接线只有 `PlanningRevisionListener` 一处。"""

    def test_exactly_four_insight_created_registrations_repo_wide(self):
        registrations: list[str] = []
        for path in _app_sources():
            if "register_insight_created_listener(" in path.read_text(encoding="utf-8"):
                registrations.append(
                    path.relative_to(support.repo_root()).as_posix()
                )
        assert sorted(registrations) == sorted(
            [
                *REFLECTION_CONSUMERS,
                "app/services/planning/revision_listener.py",
                "app/services/reflection/lifecycle.py",
            ]
        )

    def test_the_listener_is_the_only_planning_side_reflection_consumer(self):
        assert "register_insight_created_listener" in LISTENER_PATH.read_text(
            encoding="utf-8"
        )
        others = [
            path.name
            for path in scan.planning_modules()
            if path.name != "revision_listener.py"
            and "register_insight_created_listener" in path.read_text(encoding="utf-8")
        ]
        assert others == []

    def test_existing_three_consumers_are_untouched_by_this_task(self):
        for relative in REFLECTION_CONSUMERS:
            text = (support.repo_root() / relative).read_text(encoding="utf-8")
            assert "plan" not in text.split("def on_insight_created", 1)[1][:1500].lower()
            assert "PLAN_WINDOW" not in text

    def test_only_main_registers_the_listener(self):
        importers: list[str] = []
        for path in _app_sources():
            if path == LISTENER_PATH:
                continue
            if "services.planning.revision_listener" in path.read_text(encoding="utf-8"):
                importers.append(path.relative_to(support.repo_root()).as_posix())
        assert importers == ["app/main.py"]

    def test_registration_is_gated_and_sits_in_the_lifespan(self):
        source = (support.repo_root() / "app" / "main.py").read_text(encoding="utf-8")
        assert source.count("register_plan_revision_listener()") == 1
        block = source.split("register_plan_revision_listener()", 1)[0].rsplit(
            "if get_settings()", 1
        )[1]
        assert "v25_plan_reflection_enabled" in block
        assert "self._enabled" not in block


class TestStagePosition:
    """I10：计划反思不在 `foreground` 关键路径（仍在反思步与后台节拍）。"""

    def test_the_reflection_check_step_still_drives_the_trigger(self):
        life_loop = (
            support.repo_root() / "app" / "application" / "life_loop.py"
        ).read_text(encoding="utf-8")
        step = life_loop.split("def _step_reflection_check(", 1)[1].split(
            "\ndef ", 1
        )[0]
        assert "reflection_triggers.trigger_for_user(" in step

    def test_plan_evidence_is_reachable_only_through_the_shared_aggregation(self):
        callers = []
        for path in _app_sources():
            text = path.read_text(encoding="utf-8")
            if "aggregate_plan_evidence(" in text and path != EVIDENCE_PATH:
                callers.append(path.relative_to(support.repo_root()).as_posix())
        assert callers == []
        assert "aggregate_plan_evidence(" in EVIDENCE_PATH.read_text(encoding="utf-8")

    def test_the_listener_runs_from_the_reflection_job_not_from_a_request_path(self):
        reflector = (REFLECTION_DIR / "reflector.py").read_text(encoding="utf-8")
        assert "notify_insight_created_listeners(" in reflector
        assert "register_executor" in reflector
        for path in _app_sources():
            relative = path.relative_to(support.repo_root()).as_posix()
            if relative.startswith(("app/api/", "app/channels/")):
                assert "revision_listener" not in path.read_text(encoding="utf-8")

    def test_the_sub_flag_keeps_the_whole_channel_dark_by_default(self):
        settings = get_settings()
        assert settings.v25_plan_reflection_enabled is False
        assert reflection_evidence.plan_evidence_enabled(settings) is False
        assert listener_mod.get_revision_listener() is not None


class TestZeroMigration:
    """I12 / §10.3：迁移链头 0046；值集与 job_type 未扩。"""

    def test_migration_chain_head_is_still_0047(self):
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        numbered = sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert f"{max(numbered):04d}" == MIGRATION_HEAD
        assert max(numbered) == 47

    def test_insight_type_and_scope_value_sets_are_unexpanded(self):
        from typing import get_args

        assert tuple(get_args(InsightType)) == INSIGHT_TYPE_VALUES
        assert tuple(get_args(InsightScope)) == INSIGHT_SCOPE_VALUES
        assert EVIDENCE_CHANNEL_PLAN == "plan"

    def test_insights_check_constraints_are_unexpanded(self):
        from app.core.db import InsightRow

        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in InsightRow.__table__.constraints
            if constraint.name and constraint.name.startswith("ck_insights")
        }
        assert sorted(checks) == [
            "ck_insights_invalidated_reason",
            "ck_insights_scope",
            "ck_insights_status",
            "ck_insights_type",
        ]
        for value in INSIGHT_TYPE_VALUES:
            assert value in checks["ck_insights_type"]
        for value in INSIGHT_SCOPE_VALUES:
            assert value in checks["ck_insights_scope"]

    def test_background_job_type_is_not_expanded(self):
        """重规划 job 复用既有 `goal_planning`（零新 job_type）。"""
        assert listener_mod.STEP_NAME == "plan_revision_listener"
        from app.services import goal_planning

        assert goal_planning.JOB_TYPE_PLANNING == "goal_planning"
        from app.core.db import BackgroundJobRow

        checks = sorted(
            constraint.name
            for constraint in BackgroundJobRow.__table__.constraints
            if constraint.name
        )
        assert checks == ["ck_background_jobs_status"]
        migrations = (
            Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        )
        for path in migrations.glob("*.py"):
            assert "ck_background_jobs_job_type" not in path.read_text(encoding="utf-8")

    def test_no_new_column_or_index_is_referenced_by_the_module(self):
        text = scan.code_text(LISTENER_PATH)
        for token in ("evidence_refs_json", "Index", "CheckConstraint", "metadata"):
            assert token not in text, token

    def test_the_planning_package_does_not_declare_new_tables(self):
        from app.core.db import Base

        assert sorted(name for name in Base.metadata.tables if name.startswith("plan")) == []
        assert listener_mod.LEDGER_LIMIT == 500
