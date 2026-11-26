"""PLA-018 Agent Runtime Adoption & Background Cutover。

验证面（对齐 `docs/version/v4.0.0/tasks/PLA-018.md` §7）：

1. **单一路径**：生产入口 `run_autonomous_cycle` 无配置分支、全仓唯一实现体、
   编排体内零内联段序列（段序列唯一声明处为 `profiles.py`）。
2. **无回退位**：`_legacy_run_autonomous_cycle` / `legacy_cycle_runnable` 与
   `runtime_autonomous_cycle_enabled` 字段已于 2026-10-15 物理删除（等价性
   已由 PLA-018 验收沉淀，回退 = git revert）。
3. **不激活六段**：`stages/*` 仍为影子实现。
4. **零新增开关**：`*_enabled` 字段集合与基线一致。
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.application import life_loop
from app.application.agent_runtime import profiles
from app.application.agent_runtime import loop as loop_module
from app.application.agent_runtime import stages as stages_pkg
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.core.settings import Settings, get_settings
from app.repositories import conversation_repository, loop_run_repository
from app.services.life import budget as life_loop_budget
from app.services.autonomy import trigger as trigger_evaluator
from tests.v40.support import BASELINE_ENABLED_FLAGS

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
CONTROLLER = APP / "application" / "agent_runtime" / "controller.py"
PROFILES = APP / "application" / "agent_runtime" / "profiles.py"

NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "pla018-user"
SESSION = "pla018-s1"

KNOWN_STAGES = frozenset(loop_module.STAGE_TO_PHASE)
"""全仓已知阶段名（唯一映射表）；用于识别「内联段序列」字面量。"""


@pytest.fixture(autouse=True)
def _reset_budget():
    life_loop_budget.reset_cache()
    yield
    life_loop_budget.reset_cache()


@pytest.fixture()
def background_ready(override_settings):
    """后台 tick 可跑的最小环境（世界旁路关闭）。"""
    trigger_evaluator._followup_registry.clear()
    override_settings()
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


def _seed_conversation(user_id: str, session_id: str, *, age_minutes: int = 40) -> None:
    from app.core.db import Message

    conversation_repository.get_or_create_conversation(session_id, user_id)
    conversation_repository.save_message(session_id, "human", "在吗")
    conversation_repository.save_message(session_id, "ai", "在的")
    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=age_minutes)
        session.commit()


def _fake_tick(monkeypatch) -> None:
    async def fake_tick(user_ids=None, llm=None, now=None):
        return []

    monkeypatch.setattr(life_loop.autonomy_engine, "tick", fake_tick)


def _step_names(row) -> list[str]:
    return [s["step"] for s in row.steps if s.get("step") != "abort"]


def _stage_tuples(source: str) -> list[list[str]]:
    """源码中「元素全为已知段名」的字符串 tuple 字面量（长度 ≥ 3）。"""
    found: list[list[str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Tuple):
            continue
        values = [
            elt.value
            for elt in node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
        if len(values) >= 3 and set(values) <= KNOWN_STAGES:
            found.append(values)
    return found


class TestSingleOrchestrationPath:
    """AC1 / AC4：单一路径与段序列唯一声明处。"""

    pytestmark = pytest.mark.unit

    def test_production_entry_has_no_config_branch(self):
        func = next(
            node
            for node in ast.walk(ast.parse(CONTROLLER.read_text(encoding="utf-8")))
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "run_autonomous_cycle"
        )
        referenced = {
            node.attr if isinstance(node, ast.Attribute) else node.id
            for node in ast.walk(func)
            if isinstance(node, (ast.Attribute, ast.Name))
        }
        assert "runtime_autonomous_cycle_enabled" not in referenced
        assert "legacy_cycle_runnable" not in referenced

    def test_single_definition_of_production_entry(self):
        found = []
        for path in sorted(APP.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(
                    node, (ast.AsyncFunctionDef, ast.FunctionDef)
                ) and node.name == "run_autonomous_cycle":
                    found.append(path.relative_to(BACKEND).as_posix())
        assert found == ["app/application/agent_runtime/controller.py"]

    def test_no_inline_stage_sequence_in_orchestrator(self):
        assert _stage_tuples(CONTROLLER.read_text(encoding="utf-8")) == []
        assert _stage_tuples(PROFILES.read_text(encoding="utf-8"))


class TestShadowAndFlagBudget:
    """AC5 / AC6：六段仍为影子；零新增功能开关。"""

    pytestmark = pytest.mark.unit

    def test_six_stage_loop_still_shadow(self):
        assert get_settings().runtime_six_stage_loop_enabled is False
        assert stages_pkg.SHADOW_STAGE_IMPLEMENTATION is True
        assert loop_module.SHADOW_STAGE_METHODS is True

    def test_no_new_enabled_flag(self):
        actual = {name for name in Settings.model_fields if name.endswith("_enabled")}
        assert actual == set(BASELINE_ENABLED_FLAGS)
        assert not {name for name in BASELINE_ENABLED_FLAGS if name not in actual}


class TestCutoverEquivalence:
    """AC2 / AC3 / AC7：空转语义与维护步（等价性已由 PLA-018 验收沉淀）。"""

    pytestmark = pytest.mark.integration

    async def test_life_loop_tick_runs_via_agent_runtime(
        self, db_session_factory, background_ready, monkeypatch
    ):
        _seed_conversation(USER, SESSION)
        _fake_tick(monkeypatch)

        before = len(loop_run_repository.list_recent(user_id=USER))
        stats = await life_loop.run_life_loop_tick(now=NOW)
        rows = loop_run_repository.list_recent(user_id=USER)

        assert stats["user_cycles"] == 1
        assert len(rows) == before + 1
        assert rows[0].run_kind == RUN_KIND_AUTONOMOUS_TICK
        assert _step_names(rows[0]) == list(
            profiles.get_profile(RUN_KIND_AUTONOMOUS_TICK).stages
        )

    async def test_idle_short_circuit_zero_llm_zero_runs(
        self, db_session_factory, background_ready, monkeypatch
    ):
        _fake_tick(monkeypatch)
        await life_loop.run_life_loop_tick(now=NOW)
        before_runs = len(loop_run_repository.list_recent())
        before_calls = life_loop_budget.check_daily_budget(now=NOW).used_calls

        stats = await life_loop.run_life_loop_tick(now=NOW + timedelta(seconds=60))

        assert stats["idle"] is True
        assert stats["user_cycles"] == 0
        assert len(loop_run_repository.list_recent()) == before_runs
        assert life_loop_budget.check_daily_budget(now=NOW).used_calls == before_calls

    async def test_maintenance_steps_unchanged(
        self, db_session_factory, background_ready, monkeypatch
    ):
        _fake_tick(monkeypatch)

        stats = await life_loop.run_life_loop_tick(now=NOW)

        assert stats["maintenance"] == 7
        kinds = {r.kind for r in loop_run_repository.list_recent()}
        assert {"trigger_reconcile", "ledger_digest", "ledger_alert"} <= kinds
