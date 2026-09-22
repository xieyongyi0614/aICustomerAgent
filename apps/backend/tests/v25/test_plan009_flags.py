"""PLAN-009 Step 6：门控与回归（语义反转：记忆通道常开 / 零迁移 / 三模块零改动）。

覆盖 Task Detail §9.2 I5 / I7 / I8 / I10、§9.3 S9、§10.3 零迁移；对应 §8 Step 6。
v25 去门控（批次 6）：记忆子闸与总闸已删，原「off 零写入」两用例的前提不存在，
按纪律退役；`plan_memory_importance_floor` 策略生效用例保留（去开关注入）。
"""

import re
from pathlib import Path

from tests.support.schema_pins import MIGRATION_HEAD
import pytest

from app.repositories import goal_repository
from app.services import memory_policy as policy_gate
from app.services.planning import memory_policy as plan_memory_policy
from app.services.planning import observer as observer_mod
from app.services.tool import memory_policy as tool_memory_policy

from . import _plan_scan as scan
from . import plan009_support as support
from .plan009_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    planning_memory_on,
)


MEMORIES_COLUMNS = (
    "id",
    "user_id",
    "content",
    "type",
    "importance",
    "character_id",
    "confidence",
    "source",
    "status",
    "superseded_by",
    "last_accessed_at",
    "expires_at",
    "created_at",
    "updated_at",
    "embedding",
    "salience",
    "last_reinforced_at",
    "last_decayed_at",
    "forgotten_at",
    "merge_chain",
    "source_ref",
    "visibility",
)

MEMORY_SOURCE_VALUES = ("user_stated", "user_derived", "ai_inferred")

MEMORY_TYPE_VALUES = (
    "user_preference",
    "user_fact",
    "important_event",
    "relationship_event",
    "experience",
    "relationship_fact",
    "commitment",
    "milestone_event",
    "behavior_pattern",
)

PLAN_DEDUPE_KEY = "plan:plan9-goal:1:1"


class TestFlagGating:
    """I10 / S9 语义反转：记忆通道恒投递；`plan is None` / 投递失败仍零写入（D10）。"""

    def test_delivery_returns_none_without_a_plan(
        self, db_session_factory, planning_memory_on, make_goal, monkeypatch
    ):
        probe = support.install_delivery_probe(monkeypatch)
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        assert observer_mod.deliver_goal_terminal_memory(goal, None, "completed") is None
        assert probe.order == []

    def test_the_hook_sits_on_the_terminal_transition_path_only(self):
        source = support.module_path("observer.py").read_text(encoding="utf-8")
        assert source.count("deliver_goal_terminal_memory(") == 2
        transition = source.split("def _transition(", 1)[1]
        assert "deliver_goal_terminal_memory(" in transition
        settle_body = source.split("def settle(", 1)[1].split("def _transition(", 1)[0]
        assert "deliver_goal_terminal_memory(" not in settle_body


class TestImportanceFloorParameter:
    """§8 Step 6.2：`plan_memory_importance_floor` 生效于失败 / 放弃类。"""

    @pytest.mark.parametrize(
        "event_kind", ("plan_failed", "plan_abandoned")
    )
    def test_a_raised_floor_lifts_the_deposited_importance(
        self, db_session_factory, make_goal, override_settings, event_kind, monkeypatch
    ):
        probe = support.install_delivery_probe(monkeypatch)
        override_settings(
            plan_memory_importance_floor="0.9",
            world_enabled="false",
            observability_persist_enabled="false")
        goal = make_goal(description=support.FAILED_DESCRIPTION)
        plan = support.plan(goal_id=goal.id)
        outcome = "failed" if event_kind == "plan_failed" else "abandoned"

        observer_mod.deliver_goal_terminal_memory(goal, plan, outcome)

        assert probe.saved[0]["importance"] == 0.9

    def test_the_floor_never_lowers_the_completed_importance(self):
        assert plan_memory_policy.PLAN_COMPLETED_IMPORTANCE == 0.7
        assert plan_memory_policy.PLAN_MEMORY_FLOOR_EVENT_KINDS == (
            "plan_failed",
            "plan_abandoned",
        )


class TestZeroMigration:
    """I8 / §10.3：迁移链头 0046、`memories` 列集与值集未变、零新迁移文件。"""

    def test_migration_chain_head_matches_pin(self):
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        numbered = sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert f"{max(numbered):04d}" == MIGRATION_HEAD

    def test_memories_columns_are_frozen(self):
        from app.core.db import Base

        assert tuple(
            column.name for column in Base.metadata.tables["memories"].columns
        ) == MEMORIES_COLUMNS

    def test_memories_check_constraints_are_unexpanded(self):
        """`memories` 的 CHECK 约束名集合逐字冻结（值集未扩 = 零新 COLUMN/CHECK 迁移）。"""
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        constraints = sorted(
            {
                name
                for path in versions.glob("*.py")
                for name in re.findall(r"ck_memories\w*", path.read_text(encoding="utf-8"))
            }
        )
        assert constraints == ["ck_memories_memory_type", "ck_memories_type"]

    def test_memory_type_and_source_value_sets_are_unexpanded(self):
        from typing import get_args

        from app.models.memory import MemorySource, MemoryType

        assert tuple(get_args(MemorySource)) == MEMORY_SOURCE_VALUES
        assert tuple(get_args(MemoryType)) == MEMORY_TYPE_VALUES
        assert plan_memory_policy.PLAN_COMPLETED_IMPORTANCE == 0.7
        used_types = {
            row["memory_type"]
            for row in plan_memory_policy.PLAN_MEMORY_BOUNDARY_TABLE.values()
            if row.get("memory_type")
        }
        used_sources = {
            row["source"]
            for row in plan_memory_policy.PLAN_MEMORY_BOUNDARY_TABLE.values()
            if row.get("source")
        }
        assert used_types <= set(MEMORY_TYPE_VALUES)
        assert used_sources <= set(MEMORY_SOURCE_VALUES)

    def test_no_new_table_or_column_is_introduced_by_the_module(self):
        from app.core.db import Base

        planning_tables = {
            name for name in Base.metadata.tables if name.startswith("plan")
        }
        assert planning_tables == set()
        code = scan.code_text(support.module_path("memory_policy.py"))
        assert "plan_id" not in code


class TestFrozenContracts:
    """I5 / I7：`memory_policy` / `memory2` / `services/tool/memory_policy.py` 零改动。"""

    def test_memory_policy_rule_codes_and_reasons_are_frozen(self):
        repo_root = support.repo_root()
        text = (repo_root / "app" / "services" / "memory_policy.py").read_text(
            encoding="utf-8"
        )
        for anchor in (
            '"R1", "AI 推测不入库"',
            '"R2", "本轮被 suppress 指令阻断"',
            '"R3", "用户要求遗忘，转隐私执行"',
            '"R4", "一次性信息"',
            '"R5", "置信度过低"',
            '"R6", "重要性过低"',
            '"R7", "与既有记忆完全重复"',
            '"R8", "含未消解指代"',
        ):
            assert anchor in text
        assert policy_gate.DECISION_SAVE == "save"
        assert policy_gate.DECISION_DISCARD == "discard"
        assert policy_gate.DECISION_PRIVACY == "privacy"

    def test_r1_still_discards_ai_inferred(self):
        from app.models.memory import MemoryCandidate

        candidate = MemoryCandidate(
            action="save", type="important_event", content="完成了一件事", source="ai_inferred"
        )
        report = policy_gate.apply_policy([candidate])
        assert [outcome.rule for outcome in report.discarded] == ["R1"]

    def test_the_goal_completion_ingest_signature_is_unchanged(self):
        from app.services.memory2 import ingest as ingest_mod

        text = Path(ingest_mod.__file__).read_text(encoding="utf-8")
        assert (
            "def ingest_from_goal_completion(user_id: str, goal_id: str, description: str)"
            in text
        )
        assert 'content=f"完成了目标：{description}"' in text
        assert 'source_kind="ai_inferred"' in text
        assert 'source_id=f"{goal_id}:completed"' in text

    def test_tool_memory_policy_module_is_frozen(self):
        text = (
            support.repo_root() / "app" / "services" / "tool" / "memory_policy.py"
        ).read_text(encoding="utf-8")
        for anchor in (
            "MEMORY_CONTENT_MAX_CHARS = 120",
            "FAILED_IMPORTANCE_FLOOR = 0.6",
            'DEFAULT_MEMORY_TYPE = "important_event"',
            'DEFAULT_SOURCE = "user_derived"',
            "DEPOSIT_SKIP = \"skip\"",
        ):
            assert anchor in text
        assert tool_memory_policy.MEMORY_CONTENT_MAX_CHARS == 120
        assert tool_memory_policy.FAILED_IMPORTANCE_FLOOR == 0.6
