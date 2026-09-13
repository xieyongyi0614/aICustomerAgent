"""AGENT-001 Profile Registry 与 LLM Gateway 单测。

覆盖：Profile 注册表形状与未知 run_kind 拒绝、能力注册表对 CallSite 全覆盖、
四问裁决矩阵（全局熔断 / run 级账户 / 前台软硬模式）、answer 降档与拒绝。
"""

from datetime import datetime

import pytest

from app.application.agent_runtime import llm_gateway, profiles
from app.application.agent_runtime.llm_gateway import GatewayDeniedError
from app.application.agent_runtime.models import RunContext
from app.models.observability import CallSite
from app.services import life_loop_budget

NOW = datetime(2026, 9, 13, 12, 0, 0)


def _run(run_kind="autonomous_tick", llm_calls=0):
    return RunContext(
        run_id="run-1",
        user_id="u1",
        run_kind=run_kind,
        trigger_type="schedule",
        reason="test",
        started_at=NOW,
        llm_calls=llm_calls,
    )


class TestProfileRegistry:
    def test_three_profiles_declared(self):
        for run_kind in ("foreground_chat", "autonomous_tick", "event_driven"):
            spec = profiles.get_profile(run_kind)
            assert spec.run_kind == run_kind
            assert spec.stages

    def test_autonomous_tick_matches_life_loop_pipeline(self):
        spec = profiles.get_profile("autonomous_tick")
        assert spec.stages == (
            "perception", "state_update", "goal_check", "goal_supply",
            "goal_advance", "memory_retrieval", "reflection_check",
            "decision", "world_experience",
        )
        assert spec.llm_capable == frozenset({"decision"})
        assert spec.critical == frozenset({"decision"})

    def test_unknown_run_kind_rejected(self):
        with pytest.raises(ValueError):
            profiles.get_profile("rogue_profile")

    def test_snapshot_shape(self):
        snap = profiles.snapshot_profile("foreground_chat")
        assert snap["run_kind"] == "foreground_chat"
        assert snap["budget_tier"] == "foreground"
        assert "reply_generation" in snap["critical"]


class TestCapabilityRegistry:
    def test_all_call_sites_registered(self):
        for site in CallSite:
            spec = llm_gateway.get_capability(site.value)
            assert spec.name == site.value

    def test_unknown_capability_rejected(self):
        with pytest.raises(ValueError):
            llm_gateway.get_capability("rogue_llm")

    def test_budget_types_partitioned(self):
        assert llm_gateway.get_capability("answer").budget_type == "foreground"
        assert llm_gateway.get_capability("proactive").budget_type == "background"


class TestAcquireMatrix:
    def test_background_run_budget_exhausted_denies(self, override_settings):
        override_settings(V2_LIFE_LOOP_CYCLE_LLM_BUDGET="1")
        run = _run(llm_calls=1)
        grant = llm_gateway.acquire("u1", "proactive", run, now=NOW)
        assert grant.granted is False
        assert grant.reason == "run_budget_exhausted"

    def test_foreground_soft_mode_accounts_without_denial(self, override_settings):
        override_settings(V21_FOREGROUND_RUN_LLM_BUDGET="0")
        run = _run(run_kind="foreground_chat")
        grant = llm_gateway.acquire("u1", "answer", run, now=NOW)
        assert grant.granted is True
        assert grant.degraded is True
        assert run.degraded is True

    def test_foreground_enforced_mode_denies(self, override_settings):
        override_settings(
            V21_FOREGROUND_RUN_LLM_BUDGET="0",
            V21_FOREGROUND_GATEWAY_ENFORCED="true",
        )
        grant = llm_gateway.acquire("u1", "answer", _run("foreground_chat"), now=NOW)
        assert grant.granted is False
        assert grant.reason == "run_budget_exhausted"

    def test_event_run_denies_all_llm(self):
        grant = llm_gateway.acquire("u1", "proactive", _run("event_driven"), now=NOW)
        assert grant.granted is False

    def test_global_circuit_background_denies(self, monkeypatch, override_settings):
        override_settings(V2_LIFE_LOOP_ENABLED="true")
        monkeypatch.setattr(life_loop_budget, "is_degraded", lambda **kwargs: True)
        grant = llm_gateway.acquire("u1", "proactive", _run(), now=NOW)
        assert grant.granted is False
        assert grant.reason == "quota_circuit_open"

    def test_global_circuit_foreground_soft_by_default(
        self, monkeypatch, override_settings
    ):
        override_settings(V2_LIFE_LOOP_ENABLED="true")
        monkeypatch.setattr(life_loop_budget, "is_degraded", lambda **kwargs: True)
        run = _run("foreground_chat")
        grant = llm_gateway.acquire("u1", "answer", run, now=NOW)
        assert grant.granted is True and grant.degraded is True
        assert run.degraded is True

    def test_global_circuit_foreground_enforced_denies(
        self, monkeypatch, override_settings
    ):
        override_settings(
            V2_LIFE_LOOP_ENABLED="true",
            V21_FOREGROUND_GATEWAY_ENFORCED="true",
        )
        monkeypatch.setattr(life_loop_budget, "is_degraded", lambda **kwargs: True)
        grant = llm_gateway.acquire("u1", "answer", _run("foreground_chat"), now=NOW)
        assert grant.granted is False

    def test_account_turn_decisions_increments_four(self):
        run = _run("foreground_chat")
        llm_gateway.account_turn_decisions(run)
        assert run.llm_calls == 4


class TestResolveAnswerLlm:
    def test_normal_grant_returns_original(self, override_settings):
        override_settings(V21_FOREGROUND_RUN_LLM_BUDGET="8")
        run = _run("foreground_chat")
        sentinel = object()
        assert llm_gateway.resolve_answer_llm(run, sentinel, now=NOW) is sentinel

    def test_degraded_with_light_profile_downgrades(self, override_settings):
        override_settings(
            V21_FOREGROUND_RUN_LLM_BUDGET="0",
            V21_LIGHT_LLM_PROFILE="longcat",
        )
        run = _run("foreground_chat")
        sentinel = object()
        resolved = llm_gateway.resolve_answer_llm(run, sentinel, now=NOW)
        assert resolved is not sentinel
        assert run.degraded is True

    def test_enforced_denial_without_light_raises(self, override_settings):
        override_settings(
            V21_FOREGROUND_RUN_LLM_BUDGET="0",
            V21_FOREGROUND_GATEWAY_ENFORCED="true",
        )
        with pytest.raises(GatewayDeniedError):
            llm_gateway.resolve_answer_llm(_run("foreground_chat"), object(), now=NOW)
