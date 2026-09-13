"""WS-013/WS-014：事件升级白名单、自治素材与决策日程感知测试。"""

from datetime import date, datetime

import pytest

from app.application import world_engine
from app.application.agent_runtime import trigger_router
from app.core.settings import get_settings
from app.repositories import world_repository
from app.services import decision_pipeline, goal_planning
from app.services.world import event_impact

pytestmark = pytest.mark.xdist_group("ws013")


@pytest.fixture
def detection_flags(monkeypatch):
    for key, value in {
        "V23_WORLD_SIMULATION_ENABLED": "true",
        "V23_EVENT_DETECTION_ENABLED": "true",
        "V23_DAILY_LIFE_ENABLED": "true",
        "V23_TIME_ADVANCE_ENABLED": "true",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_whitelist_unchanged_without_v23(monkeypatch):
    monkeypatch.setenv("V23_WORLD_SIMULATION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        whitelist = trigger_router.escalation_whitelist()
        assert "user_condition" not in whitelist
        assert "reminder" not in whitelist
    finally:
        get_settings.cache_clear()


def test_whitelist_merges_v23_types(monkeypatch, detection_flags):
    whitelist = trigger_router.escalation_whitelist()
    assert "user_condition" in whitelist
    assert "weather_change" in whitelist
    assert "calendar_event" in whitelist


def test_escalation_gate_evaluates_merged_whitelist(monkeypatch, detection_flags):
    assert trigger_router.evaluate_event_escalation("goal_completed") is True
    assert trigger_router.evaluate_event_escalation("alien") is False


def test_collect_facts_enriched_with_impacts(db_session_factory, detection_flags):
    user = "ws013-facts"
    world_repository.ensure_world(user)
    world_engine.create_event(
        user,
        event_type="user_condition",
        title="用户感冒了",
        importance="high",
        source="user_evidence",
        status="active",
        payload={"kind": "detected", "intensity": 4, "dimension": "health", "summary": "用户感冒了"},
    )
    facts = world_engine.collect_facts(user)
    assert "impacts" in facts
    assert facts["impacts"]
    assert facts["impacts"][0]["event_type"] in ("user_condition", "reminder")
    top = facts["impacts"][0]
    assert top["urgency"] in ("none", "low", "medium", "high")


def test_collect_facts_basic_without_v23(db_session_factory, monkeypatch):
    monkeypatch.setenv("V23_WORLD_SIMULATION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        user = "ws013-off"
        world_repository.ensure_world(user)
        facts = world_engine.collect_facts(user)
        assert "impacts" not in facts
        assert "current_block" not in facts
    finally:
        get_settings.cache_clear()


def test_world_affordance_candidates_from_impacts():
    impacts = [
        {
            "event_id": "e1",
            "event_type": "weather_change",
            "urgency": "low",
            "care_relevance": 0.7,
            "topic_value": 0.4,
            "goal_opportunity": {
                "domain": "user_care",
                "type": "remind_weather",
                "hint": "提醒用户添衣",
                "layer": "short_term",
            },
        },
        {
            "event_id": "e2",
            "event_type": "time_marker",
            "urgency": "none",
            "care_relevance": 0.1,
            "topic_value": 0.3,
            "goal_opportunity": None,
        },
    ]
    candidates = decision_pipeline.collect_candidates(world_impacts=impacts)
    sources = [c.source for c in candidates]
    assert "world_affordance" in sources
    affordance = next(c for c in candidates if c.source == "world_affordance")
    assert affordance.payload["type"] == "remind_weather"


def test_pipeline_prefers_care_candidate_over_silence():
    impacts = [
        {
            "event_id": "e1",
            "event_type": "user_condition",
            "urgency": "high",
            "care_relevance": 0.9,
            "topic_value": 0.6,
            "goal_opportunity": {
                "domain": "user_care",
                "type": "care_health",
                "hint": "关心用户身体",
                "layer": "short_term",
            },
        }
    ]
    result = decision_pipeline.run_pipeline(world_impacts=impacts)
    assert result.winner is not None
    assert result.winner.source == "world_affordance"


def test_timing_schedule_signal():
    candidate = decision_pipeline.Candidate("world_affordance", None, None, {"type": "chat"})
    schedule_busy = {"current_block": {"activity": "工作学习"}}
    relaxed = decision_pipeline._timing(candidate, None, schedule_busy)
    normal = decision_pipeline._timing(candidate, None)
    assert relaxed == 0.35
    assert normal == 0.5


def test_timing_care_exempt_from_busy_penalty():
    candidate = decision_pipeline.Candidate(
        "world_affordance",
        None,
        None,
        {
            "type": "care_health",
            "impact": {"urgency": "high", "care_relevance": 0.9},
        },
    )
    schedule_busy = {"current_block": {"activity": "工作学习"}}
    assert decision_pipeline._timing(candidate, None, schedule_busy) == 0.5


def test_goal_planning_candidates_from_impacts():
    facts = {
        "impacts": [
            {
                "event_id": "e1",
                "event_type": "weather_change",
                "urgency": "low",
                "care_relevance": 0.7,
                "topic_value": 0.4,
                "goal_opportunity": {
                    "domain": "user_care",
                    "type": "remind_clothing",
                    "hint": "提醒添衣",
                    "layer": "short_term",
                },
            },
            {
                "event_id": "e2",
                "event_type": "time_marker",
                "urgency": "none",
                "care_relevance": 0.1,
                "topic_value": 0.2,
                "goal_opportunity": None,
            },
        ]
    }
    candidates = goal_planning.collect_candidates("ws014-goal", facts)
    world_candidates = [c for c in candidates if c["origin"] == "world_event"]
    assert any("提醒添衣" in c["description"] for c in world_candidates)
    assert all(c["layer"] == "short_term" for c in world_candidates)
