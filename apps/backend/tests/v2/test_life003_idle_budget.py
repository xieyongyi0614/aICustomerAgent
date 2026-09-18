"""LIFE-003 Idle 与预算控制测试。

覆盖：Idle 四条件短路（0 LLM、0 run 行）、日配额熔断（调用/token 闸）、
用量查询失败保守模式、预算缓存与跨日恢复、degraded 下 decision skip
（trigger 留 pending）、周期步骤预算、loop_runs budget_state 记账。
"""

from datetime import datetime, timedelta

import pytest

from app.application import life_loop
from app.character.asuna import PERSISTENT_GOALS
from app.core.db import LlmCallRecordRow
from app.repositories import (
    conversation_repository,
    llm_call_repository,
    loop_run_repository,
    trigger_registry_repository as trigger_repo,
)
from app.services import life_loop_budget, trigger_evaluator

NOW = datetime(2026, 9, 7, 12, 0, 0)
USER = "life-budget-user"
SESSION = "lb-s1"


@pytest.fixture(autouse=True)
def _reset_budget_cache():
    life_loop_budget.reset_cache()
    yield
    life_loop_budget.reset_cache()


@pytest.fixture()
def life_loop_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings( world_enabled="false")
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


def _prefill_llm_calls(db_session_factory, count=1, tokens=100, created_at=None):
    created_at = created_at or NOW
    with db_session_factory() as session:
        for i in range(count):
            session.add(
                LlmCallRecordRow(
                    id=f"llm-{created_at.timestamp():.0f}-{i}",
                    call_site="proactive",
                    status="ok",
                    latency_ms=10.0,
                    input_tokens=tokens,
                    output_tokens=tokens,
                    created_at=created_at,
                )
            )
        session.commit()


def _stub_tick(monkeypatch):
    async def fake_tick(user_ids=None, llm=None, now=None):
        return []

    monkeypatch.setattr(life_loop.autonomy_engine, "tick", fake_tick)


class TestBudgetState:
    def test_empty_usage_ok(self, db_session_factory):
        state = life_loop_budget.check_daily_budget(now=NOW)
        assert state.status == "ok"
        assert state.used_calls == 0

    def test_over_call_limit_degraded(self, db_session_factory, override_settings):
        override_settings(v2_life_loop_daily_llm_call_budget="2")
        _prefill_llm_calls(db_session_factory, count=2)
        state = life_loop_budget.check_daily_budget(now=NOW)
        assert state.status == "degraded"
        assert state.reason == "over_call_limit"
        assert life_loop_budget.is_degraded(now=NOW) is True

    def test_over_token_limit_degraded(self, db_session_factory, override_settings):
        override_settings(
            v2_life_loop_daily_llm_call_budget="0",
            v2_life_loop_daily_llm_token_budget="100",
        )
        _prefill_llm_calls(db_session_factory, count=1, tokens=100)
        state = life_loop_budget.check_daily_budget(now=NOW)
        assert state.status == "degraded"
        assert state.reason == "over_token_limit"

    def test_usage_query_failure_conservative(
        self, db_session_factory, monkeypatch, override_settings
    ):
        override_settings(v2_life_loop_daily_llm_call_budget="10")

        def boom(cutoff):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            llm_call_repository, "aggregate_usage_since", boom, raising=True
        )
        state = life_loop_budget.check_daily_budget(now=NOW)
        assert state.status == "degraded"
        assert state.reason == "usage_query_failed_conservative"
        assert state.call_limit == 8  # 10 × 0.8 保守收紧

    def test_cache_hit_within_ttl(self, db_session_factory, monkeypatch):
        calls = {"n": 0}
        real = llm_call_repository.aggregate_usage_since

        def counting(cutoff):
            calls["n"] += 1
            return real(cutoff)

        monkeypatch.setattr(llm_call_repository, "aggregate_usage_since", counting)
        life_loop_budget.check_daily_budget(now=NOW)
        life_loop_budget.check_daily_budget(now=NOW + timedelta(seconds=10))
        assert calls["n"] == 1
        life_loop_budget.check_daily_budget(now=NOW + timedelta(seconds=120))
        assert calls["n"] == 2

    def test_next_day_recovers(self, db_session_factory, override_settings):
        override_settings(v2_life_loop_daily_llm_call_budget="1")
        _prefill_llm_calls(db_session_factory, count=1)
        assert life_loop_budget.check_daily_budget(now=NOW).status == "degraded"
        next_day = NOW + timedelta(days=1)
        assert life_loop_budget.check_daily_budget(now=next_day).status == "ok"


class TestIdle:
    @pytest.mark.asyncio
    async def test_idle_skips_entire_cycle(self, db_session_factory, life_loop_on):
        await life_loop.run_life_loop_tick(now=NOW)  # 首轮 reconcile 到期
        before = len(loop_run_repository.list_recent())
        stats = await life_loop.run_life_loop_tick(now=NOW + timedelta(seconds=60))
        assert stats["idle"] is True
        assert stats["user_cycles"] == 0
        assert len(loop_run_repository.list_recent()) == before

    @pytest.mark.asyncio
    async def test_seven_day_idle_zero_llm(self, db_session_factory, life_loop_on):
        """7 天空转（压缩时钟）：Idle 期间 LLM 调用为 0，总量 ≤ 日预算（E-LIFE-03）。"""
        for hour in range(0, 24 * 7, 2):
            stats = await life_loop.run_life_loop_tick(
                now=NOW + timedelta(hours=hour)
            )
            if hour > 0:
                assert stats["idle"] is True
        assert llm_call_repository.aggregate_usage_since(NOW)["calls"] == 0

    @pytest.mark.asyncio
    async def test_quiet_hours_user_cycles_zero_llm_within_budget(
        self, db_session_factory, life_loop_on, override_settings
    ):
        """7 天全静音时段：周期持续运行但 verdict=ignore，0 LLM。"""
        override_settings(
            autonomy_quiet_hours_start="00:00", autonomy_quiet_hours_end="23:59"
        )
        from app.character.asuna import PERSISTENT_GOALS
        from app.repositories import goal_repository

        goal_repository.seed_goals(USER, PERSISTENT_GOALS)
        conversation_repository.get_or_create_conversation(SESSION, USER)
        conversation_repository.save_message(SESSION, "human", "我去忙了")
        from app.core.db import Message

        with conversation_repository.SessionLocal() as session:
            for row in session.query(Message).all():
                row.created_at = NOW - timedelta(minutes=40)
            session.commit()
        for hour in range(0, 24 * 7, 2):
            stats = await life_loop.run_life_loop_tick(
                now=NOW + timedelta(hours=hour)
            )
            assert stats["aborted"] == 0
        assert llm_call_repository.aggregate_usage_since(NOW)["calls"] == 0


class TestBudgetGate:
    @pytest.mark.asyncio
    async def test_degraded_skips_decision_and_keeps_trigger_pending(
        self, db_session_factory, life_loop_on, override_settings, monkeypatch
    ):
        override_settings(v2_life_loop_daily_llm_call_budget="1")
        _prefill_llm_calls(db_session_factory, count=1)
        _stub_tick(monkeypatch)
        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_evaluator.register_followup(
            USER, NOW - timedelta(minutes=1), "下午面试"
        )

        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["user_cycles"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert run.status == "done"
        decision = next(s for s in run.steps if s["step"] == "decision")
        assert decision["status"] == "skipped"
        assert decision["skip_reason"] == "quota_circuit_open"
        assert run.budget_state.get("status") == "degraded"
        assert trigger_repo.list_recent(USER)[0].status == "pending"

    @pytest.mark.asyncio
    async def test_cycle_step_budget_skips_decision(
        self, db_session_factory, life_loop_on, override_settings, monkeypatch
    ):
        override_settings(v2_life_loop_cycle_llm_budget="0")
        _stub_tick(monkeypatch)
        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_evaluator.register_followup(
            USER, NOW - timedelta(minutes=1), "下午面试"
        )
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["user_cycles"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        decision = next(s for s in run.steps if s["step"] == "decision")
        assert decision["status"] == "skipped"
        assert decision["skip_reason"] == "step_budget"

    @pytest.mark.asyncio
    async def test_budget_ok_decision_runs_and_accounted(
        self, db_session_factory, life_loop_on, monkeypatch
    ):
        _stub_tick(monkeypatch)
        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_evaluator.register_followup(
            USER, NOW - timedelta(minutes=1), "下午面试"
        )
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["user_cycles"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        decision = next(s for s in run.steps if s["step"] == "decision")
        assert decision["status"] == "ok"
        assert decision.get("llm_capable") is True
        assert run.budget_state.get("status") == "ok"
        assert run.llm_call_count == 0  # stub tick 无真实 LLM 调用
