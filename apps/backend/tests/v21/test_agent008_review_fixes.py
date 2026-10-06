"""V2.1.0 评审修复回归守门（code-review.md 的 A1~A6 / C2~C5）。

覆盖：慢时钟调度接线（A1）、前台/后台共用决策管线（A2）、台账 profile 与执行
阶段一致（A3）、Rebalance 建议/应用分离（A4）、Ledger 多用户隔离（A5）、
后台 Run contextvar 复位（A6）、漂移限速不再「证据越多越不动」（C2）、
六维评分与逐闸留痕真实化（C3）、父层倒挂拒绝且保留既有同层嵌套（C4）、
低能量抑制生效（C5）、域层零感知依赖方向（AGENT-001 验收 7）、
v21 迁移链往返（0038~0043）。
"""

import ast
import pathlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core import timeutil
from app.application import agent_evolution_worker, agent_state_context
from app.application.agent_runtime.models import RunContext
from app.character.asuna import evolution as persona_evolution
from app.core.db import InsightRow
from app.repositories import (
    agent_metric_repository,
    conversation_repository,
    goal_repository,
    personality_state_repository,
)
from app.engines import decision as decision_pipeline
from app.services.development import evolution
from app.services.goal import stack as goal_stack

NOW = timeutil.ensure_aware(datetime(2026, 9, 13, 12, 0, 0))
USER = "review-fix-user"
OTHER = "review-fix-other"

DOMAIN_MODULES = (
    "app/services/memory",
    "app/services/reflection",
    "app/engines/relationship_signal.py",
    "app/services/relationship/milestone.py",
    "app/engines/relationship_evolution.py",
    "app/services/action",
    "app/services/character_action",
    "app/services/world",
)

RUNTIME_MODULES = ("app.application.agent_runtime", "app.application.agent_evolution_worker")


@pytest.fixture()
def v21_on():
    yield


def _insight(statement, user_id=USER, created_at=NOW):
    row = InsightRow(
        id=str(uuid4()),
        user_id=user_id,
        statement=statement,
        type="pattern",
        confidence=0.8,
        scope="user",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    with evolution.SessionLocal() as session:
        session.add(row)
        session.commit()
    return row.id


def _backdate(goal_id: str, created_at: datetime) -> None:
    from app.core.db import GoalRow

    with goal_repository.SessionLocal() as session:
        row = session.get(GoalRow, goal_id)
        row.created_at = created_at
        row.updated_at = created_at
        session.commit()


def _axis_current(user_id, axis):
    rows = {r.axis: r for r in personality_state_repository.get_all(user_id)}
    return rows[axis].current


class TestDependencyDirection:
    """AGENT-001 验收 7：域层零感知（域代码不得 import Runtime 模块）。"""

    def test_domain_modules_do_not_import_runtime(self):
        backend = pathlib.Path(__file__).resolve().parents[2]
        violations = []
        for entry in DOMAIN_MODULES:
            target = backend / entry
            files = (
                [target]
                if target.suffix == ".py"
                else sorted(target.rglob("*.py"))
            )
            for path in files:
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if any(node.module.startswith(m) for m in RUNTIME_MODULES):
                            violations.append(f"{path.name}:{node.lineno} → {node.module}")
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if any(alias.name.startswith(m) for m in RUNTIME_MODULES):
                                violations.append(f"{path.name}:{node.lineno} → {alias.name}")
        assert violations == [], f"域层出现 Runtime 依赖：{violations}"


class TestEvolutionWorkerWiring:
    """A1：慢时钟必须有生产调用方（Evolution/Evaluation 不再只是存在）。"""

    def test_tick_writes_metric_snapshot_and_personality_drift(
        self, db_session_factory, v21_on
    ):
        conversation_repository.get_or_create_conversation("evo-s1", USER)
        personality_state_repository.seed_if_absent(USER, persona_evolution.PERSONALITY_AXES)
        _insight("用户多次希望角色主动发起话题，角色开始敢于表达观点")

        stats = agent_evolution_worker.run_evolution_tick(NOW)

        assert stats["status"] == "ok" and stats["users"] == 1
        assert stats["snapshots"] == 1
        assert agent_metric_repository.list_recent(USER, limit=5)
        assert stats["personality"] >= 1
        assert _axis_current(USER, "assertiveness") > 0.30

    def test_tick_is_idempotent_for_metric_window(self, db_session_factory, v21_on):
        conversation_repository.get_or_create_conversation("evo-s2", USER)
        agent_evolution_worker.run_evolution_tick(NOW)
        agent_evolution_worker.run_evolution_tick(NOW)
        assert len(agent_metric_repository.list_recent(USER, limit=10)) == 1


class TestLedgerIsolation:
    """A5：Ledger 不得跨用户返回数据。"""

    def test_ledger_isolated_per_user(self, db_session_factory, v21_on):
        personality_state_repository.seed_if_absent(USER, persona_evolution.PERSONALITY_AXES)
        personality_state_repository.seed_if_absent(OTHER, persona_evolution.PERSONALITY_AXES)
        _insight("用户希望角色主动发起话题", user_id=USER)
        _insight("用户希望角色主动发起话题", user_id=OTHER)
        evolution.compile_personality(USER, NOW)
        evolution.compile_personality(OTHER, NOW)

        mine = evolution.ledger(USER, limit=50)

        assert mine, "本用户应有演化条目"
        assert all(e["user_id"] == USER for e in mine), "Ledger 泄漏了其他用户的数据"
        assert evolution.ledger("nobody", limit=50) == []

    def test_ledger_carries_before_after(self, db_session_factory, v21_on):
        personality_state_repository.seed_if_absent(USER, persona_evolution.PERSONALITY_AXES)
        _insight("角色温柔地安慰了用户，关系更亲近")
        evolution.compile_personality(USER, NOW)
        entries = [e for e in evolution.ledger(USER, limit=50) if e["change_kind"] == "personality"]
        assert entries
        assert entries[0]["summary"]["after"] is not None


class TestRebalanceSeparation:
    """A4：Evolution 只产建议，应用走 supply 审核侧出口。"""

    def test_propose_is_pure_read(self, db_session_factory, v21_on):
        goal = goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "过时低优先目标", 2, origin="insight"
        )
        _backdate(goal.id, NOW - timedelta(days=4))

        proposals = evolution.propose_rebalance(USER, NOW)

        assert [p["goal_id"] for p in proposals] == [goal.id]
        assert goal_repository.get_goal(goal.id).status == "active", "建议阶段不得写 goals"

    def test_apply_retires_through_goal_exit(self, db_session_factory, v21_on):
        goal = goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "过时低优先目标2", 2, origin="insight"
        )
        _backdate(goal.id, NOW - timedelta(days=4))

        retired = evolution.apply_rebalance(USER, evolution.propose_rebalance(USER, NOW), NOW)

        assert retired == [goal.id]
        assert goal_repository.get_goal(goal.id).failure_reason == "evolution_rebalance"

    def test_supply_stage_consumes_proposals(self, db_session_factory, v21_on):
        goal = goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "供给阶段消费目标", 2, origin="insight"
        )
        _backdate(goal.id, NOW - timedelta(days=4))

        run = RunContext(
            run_id="r-rebalance",
            user_id=USER,
            run_kind="autonomous_tick",
            trigger_type="schedule",
            reason="test",
            started_at=NOW,
        )
        detail = goal_stack.run_goal_stack_stage(USER, run, NOW)

        assert goal.id in detail["rebalance_retired"]
        assert goal_repository.get_goal(goal.id).status == "abandoned"


class TestDriftRateLimit:
    """C2：证据越多不应导致「永不漂移」；单窗口仍只允许一次。"""

    def test_many_evidences_still_drift(self, db_session_factory, v21_on):
        personality_state_repository.seed_if_absent(USER, persona_evolution.PERSONALITY_AXES)
        _insight("用户希望角色主动发起话题，敢于表达观点，也要更主动")

        applied = evolution.compile_personality(USER, NOW)

        assert [a["axis"] for a in applied] == ["assertiveness"]
        assert applied[0]["delta"] <= 0.05
        assert _axis_current(USER, "assertiveness") > 0.30

    def test_same_window_second_compile_blocked(self, db_session_factory, v21_on):
        personality_state_repository.seed_if_absent(USER, persona_evolution.PERSONALITY_AXES)
        _insight("用户鼓励角色主动发起话题")
        assert evolution.compile_personality(USER, NOW)
        before = _axis_current(USER, "assertiveness")
        _insight("角色再次敢于表达观点", created_at=NOW)
        assert [
            a for a in evolution.compile_personality(USER, NOW) if a["axis"] == "assertiveness"
        ] == []
        assert _axis_current(USER, "assertiveness") == before


class TestLowEnergySuppression:
    """C5：低能量抑制必须真正影响活跃层。"""

    def test_low_energy_suppresses_short_term(self, db_session_factory, v21_on):
        from app.core.db import CharacterStateRow

        goal_repository.create_hierarchical_goal(
            USER, "short_term", "world", "今晚问候用户", 4, origin="insight"
        )
        goal_repository.create_hierarchical_goal(
            USER, "long_term", "relationship", "成为信任的伙伴", 3, origin="insight"
        )
        with goal_repository.SessionLocal() as session:
            row = session.get(CharacterStateRow, USER)
            if row is None:
                row = CharacterStateRow(
                    user_id=USER,
                    mood="tired",
                    energy=0.05,
                    current_topic="",
                    inner_state="疲惫",
                    created_at=NOW,
                    updated_at=NOW,
                )
                session.add(row)
            row.energy = 0.05
            session.commit()

        stack = goal_stack.evaluate_stack(USER, NOW)

        assert stack.short_term is None
        assert stack.suppressed and "low_energy" in set(stack.suppressed.values())
        assert stack.primary() is stack.long_term

    def test_read_only_mode_does_not_retire(self, db_session_factory, v21_on):
        goal = goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "超窗但只读不退役", 3, origin="insight"
        )
        _backdate(goal.id, NOW - timedelta(days=4))

        goal_stack.evaluate_stack(USER, NOW, retire_overdue_enabled=False)

        assert goal_repository.get_goal(goal.id).status == "active"


class TestPipelineScoringAndGates:
    """C3：六维评分取自真实来源，逐闸留痕不得冒充通过。"""

    def _stack(self, goal_type="user_care"):
        stack = goal_stack.GoalStack()
        stack.short_term = SimpleNamespace(
            id="g1",
            type=goal_type,
            domain="personal",
            description="陪伴用户",
            priority=4,
            created_at=NOW,
        )
        return stack

    def test_six_dimensions_are_derived_not_constant(self):
        low = SimpleNamespace(
            energy=0.1, mood="tired", relationship={"tension": 0.8},
            current_focus=SimpleNamespace(action="", goal_id=None), interest_focus=[],
        )
        high = SimpleNamespace(
            energy=0.95, mood="happy", relationship={"tension": 0.0},
            current_focus=SimpleNamespace(action="", goal_id=None), interest_focus=[],
        )
        low_result = decision_pipeline.run_pipeline(stack=self._stack(), snapshot=low, now=NOW)
        high_result = decision_pipeline.run_pipeline(stack=self._stack(), snapshot=high, now=NOW)
        low_scores = {c["source"]: c["scores"] for c in low_result.audit["candidates"]}
        high_scores = {c["source"]: c["scores"] for c in high_result.audit["candidates"]}

        assert low_scores["goal_compile"]["state_fit"] != high_scores["goal_compile"]["state_fit"]
        assert low_scores["goal_compile"]["relationship_fit"] < 0.5
        assert low_scores["goal_compile"]["cost"] != low_scores["silence"]["cost"]

    def test_action_check_is_declared_delegated(self):
        result = decision_pipeline.run_pipeline(stack=self._stack(), now=NOW)
        for candidate in result.audit["candidates"]:
            gates = {k: v for gate in candidate["gates"] for k, v in gate.items() if k != "reason"}
            assert gates.get("action_check") == "delegated"

    def test_intention_goal_mismatch_rejected(self):
        result = decision_pipeline.run_pipeline(
            stack=self._stack("user_care"),
            trigger_intention="repair_rapport",
            trigger_goal_id="g1",
            now=NOW,
        )
        trigger = next(
            c for c in result.audit["candidates"] if c["source"] == "autonomy_trigger"
        )
        persona = next(
            gate for gate in trigger["gates"] if "persona_precheck" in gate
        )
        assert persona["persona_precheck"] == "rejected"
        assert persona["reason"] == "intention_goal_mismatch"
        assert not trigger["won"]

    def test_high_tension_blocks_social_candidate(self):
        snapshot = SimpleNamespace(
            energy=0.9, mood="calm", relationship={"tension": 0.9},
            current_focus=SimpleNamespace(action="", goal_id=None), interest_focus=[],
        )
        result = decision_pipeline.run_pipeline(
            stack=self._stack(), snapshot=snapshot, now=NOW
        )
        goal_candidate = next(
            c for c in result.audit["candidates"] if c["source"] == "goal_compile"
        )
        relationship_gate = next(
            gate for gate in goal_candidate["gates"] if "relationship_gate" in gate
        )
        assert relationship_gate["relationship_gate"] == "rejected"
        assert result.winner.source == "silence"


class TestForegroundSharedPipeline:
    """A2：前台 Run 必须走同一条五段管线并产出候选审计。"""

    def test_foreground_decision_uses_pipeline(self, db_session_factory, v21_on):
        from app.application import chat_pipeline

        conversation_repository.get_or_create_conversation("fg-s1", USER)
        run = RunContext(
            run_id="r-fg",
            user_id=USER,
            run_kind="foreground_chat",
            trigger_type="channel_message",
            reason="user_message",
            started_at=NOW,
        )
        intention = SimpleNamespace(intention="comfort_user", goal_id=None, degraded=False)
        goal = SimpleNamespace(goal=None)

        audit = chat_pipeline._run_foreground_decision(run, USER, intention, goal, NOW)

        assert audit is not None and audit["candidates"]
        sources = {c["source"] for c in audit["candidates"]}
        assert "chat_response" in sources and "silence" in sources
        assert run.data["decision"]["winner"] == "chat_response"
        assert run.data["decision"]["intention"] == "comfort_user"

    def test_foreground_without_run_context_has_no_pipeline(self, db_session_factory):
        from app.application import chat_pipeline

        intention = SimpleNamespace(intention="comfort_user", goal_id=None, degraded=False)
        assert chat_pipeline._run_foreground_decision(
            None, USER, intention, SimpleNamespace(goal=None), NOW
        ) is None


class TestParentLayerGuard:
    """C4：父层倒挂拒绝；V2.0.0 既有同层嵌套 Preserve。"""

    def test_inverted_parent_rejected(self, db_session_factory):
        short = goal_repository.create_hierarchical_goal(
            USER, "short_term", "world", "父层", 3
        )
        with pytest.raises(ValueError):
            goal_repository.create_hierarchical_goal(
                USER, "medium", "personal", "倒挂子层", 3, parent_id=short.id
            )

    def test_same_layer_nesting_preserved(self, db_session_factory):
        root = goal_repository.create_hierarchical_goal(
            USER, "short_term", "world", "同层根", 3
        )
        child = goal_repository.create_hierarchical_goal(
            USER, "short_term", "world", "同层子", 3, parent_id=root.id
        )
        assert child.parent_goal_id == root.id

    def test_invalid_origin_rejected(self, db_session_factory):
        with pytest.raises(ValueError):
            goal_repository.create_hierarchical_goal(
                USER, "medium", "personal", "非法来源", 3, origin="bogus"
            )

    def test_composite_origin_allowed(self, db_session_factory):
        record = goal_repository.create_hierarchical_goal(
            USER, "long_term", "relationship", "复合来源", 3,
            origin="relationship_pattern:warmth",
        )
        assert record.origin == "relationship_pattern:warmth"


class TestContextVarLifecycle:
    """A6：Run 结束必须复位快照 contextvar（前台与后台对称）。"""

    @pytest.mark.asyncio
    async def test_background_run_resets_snapshot(self, db_session_factory, v21_on, monkeypatch):
        from app.application import autonomy_engine, life_loop
        from app.services.autonomy import trigger as trigger_evaluator

        trigger_evaluator._followup_registry.clear()
        conversation_repository.get_or_create_conversation("cv-s1", USER)
        trigger_evaluator.register_followup(USER, NOW, "面试")

        async def fake_tick(user_ids=None, llm=None, now=None):
            return []

        monkeypatch.setattr(autonomy_engine, "tick", fake_tick)
        await life_loop.run_life_loop_tick(now=NOW)

        assert agent_state_context.get_snapshot() is None
        trigger_evaluator._followup_registry.clear()
        life_loop._maintenance_last.clear()


@pytest.mark.xdist_group("migration")
class TestMigrationChain:
    """迁移链已折叠为单迁移 0001：可升级 + 可回退 + 可再升级。"""

    def test_v21_chain_round_trip(self, tmp_path):
        from alembic import command
        from alembic.config import Config

        url = f"sqlite:///{(tmp_path / 'v21_chain.db').as_posix()}"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
