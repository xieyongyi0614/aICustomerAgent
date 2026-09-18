"""TOOL-009 §4.3/§6.1：只读反哺信号与消费侧接线（decision_pipeline / autonomy_policy）。

覆盖：接口形状（只有读方法）、工具身份还原、缺省无 Insight 时行为不变、
interest 维软信号与自治候选收缩理由。
"""

from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.services import autonomy_policy
from app.services import decision_pipeline
from app.services.reflection import tool_feed
from app.services.reflection import triggers
from tests.v24.tool009_support import (
    TOOL_REMINDER,
    TOOL_WEATHER,
    USER,
    seed_insight,
)

NOW = datetime(2026, 9, 14, 12, 0, 0)


@pytest.fixture
def tool_reflection_on(v24_tool_env):
    v24_tool_env(
        TOOL_SYSTEM_ENABLED=True,
        TOOL_REFLECTION_ENABLED=True)
    triggers.reset_trigger_state()
    yield
    triggers.reset_trigger_state()
    get_settings.cache_clear()


# --- 反哺接口：只读信号 ------------------------------------------------------


def test_interest_signal_reads_tool_insights_with_tool_ids(
    db_session_factory, tool_reflection_on
):
    seed_insight(
        db_session_factory,
        "ins-tool009-cap",
        insight_type="capability_note",
        statement="最近天气接口不稳定，先别急着查",
        confidence=0.72,
        scope="world",
        tool_ids=(TOOL_WEATHER,),
    )
    seed_insight(
        db_session_factory,
        "ins-tool009-pattern",
        insight_type="pattern",
        statement="用户最近持续处于工作压力中",
        confidence=0.9,
        scope="user",
        tool_ids=(TOOL_WEATHER,),
    )
    signal = tool_feed.interest_signal(USER)
    assert [item["type"] for item in signal] == ["capability_note"]
    assert signal[0]["tool_ids"] == [TOOL_WEATHER]
    assert signal[0]["insight_id"] == "ins-tool009-cap"
    assert signal[0]["confidence"] == pytest.approx(0.72)


def test_feed_is_empty_without_flag_or_insights(db_session_factory, tool_reflection_on):
    assert tool_feed.interest_signal(USER) == []
    assert tool_feed.autonomy_signal(USER) == {}


def test_feed_is_disabled_when_sub_flag_off(db_session_factory, v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True)
    seed_insight(
        db_session_factory,
        "ins-tool009-off",
        insight_type="capability_note",
        tool_ids=(TOOL_WEATHER,),
    )
    assert tool_feed.is_enabled(get_settings()) is False
    assert tool_feed.interest_signal(USER) == []


def test_autonomy_signal_has_notes_and_unreliable_capabilities(
    db_session_factory, tool_reflection_on
):
    seed_insight(
        db_session_factory,
        "ins-tool009-cap2",
        insight_type="capability_note",
        statement="最近天气接口不稳定",
        tool_ids=(TOOL_WEATHER,),
    )
    signal = tool_feed.autonomy_signal(USER)
    assert signal["count"] == 1
    assert signal["notes"] == ["能力自省：最近天气接口不稳定"]
    assert signal["unreliable_capabilities"] == ["最近天气接口不稳定"]


def test_inactive_insight_is_not_fed(db_session_factory, tool_reflection_on):
    seed_insight(
        db_session_factory,
        "ins-tool009-old",
        insight_type="capability_note",
        tool_ids=(TOOL_WEATHER,),
    )
    with db_session_factory() as session:
        from app.core.db import InsightRow

        row = session.get(InsightRow, "ins-tool009-old")
        row.status = "superseded"
        session.commit()
    assert tool_feed.interest_signal(USER) == []


def test_tool_ids_of_insights_ignores_memory_evidence(db_session_factory, tool_reflection_on):
    from app.core.db import EvidenceLinkRow

    seed_insight(
        db_session_factory,
        "ins-tool009-mixed",
        insight_type="capability_note",
        tool_ids=(TOOL_WEATHER,),
    )
    with db_session_factory() as session:
        session.add(
            EvidenceLinkRow(
                id="evl-mixed-mem",
                insight_id="ins-tool009-mixed",
                memory_id="mem-1",
                weight=0.5,
                created_at=NOW,
            )
        )
        session.commit()
    assert tool_feed.tool_ids_of_insights(["ins-tool009-mixed"]) == {
        "ins-tool009-mixed": [TOOL_WEATHER]
    }
    assert tool_feed.tool_ids_of_insights([]) == {}


def test_feed_degrades_on_read_error(db_session_factory, tool_reflection_on, monkeypatch, caplog):
    import logging

    from app.services.reflection import lifecycle as reflection_lifecycle

    def _boom(*args, **kwargs):
        raise RuntimeError("insights 表不可读")

    monkeypatch.setattr(reflection_lifecycle, "list_active_insights", _boom)
    with caplog.at_level(logging.ERROR, logger="app.services.reflection.tool_feed"):
        assert tool_feed.interest_signal(USER) == []
    assert "读取失败" in caplog.text


# --- 消费侧：decision_pipeline interest 维 ----------------------------------


class _Snapshot:
    def __init__(self, focus=None, topics=()):
        self.current_focus = focus
        self.interest_focus = list(topics)


def _candidate(tool_id: str | None = None):
    return decision_pipeline.Candidate(
        "capability", None, None, {"tool_id": tool_id} if tool_id else {}
    )


def test_interest_default_is_unchanged():
    """缺省（无 Insight）时 interest 维与 V2.3.0 逐字节一致。"""
    assert decision_pipeline._interest(_candidate(), None) == 0.0
    snapshot = _Snapshot()
    assert decision_pipeline._interest(_candidate(TOOL_WEATHER), snapshot) == 0.0

    class _Focus:
        goal_id = "g-1"

    focus_snapshot = _Snapshot(focus=_Focus())
    focused = decision_pipeline.Candidate("goal_compile", None, "g-1", {"type": "闲聊"})
    assert decision_pipeline._interest(focused, focus_snapshot) == 0.6

    topic_snapshot = _Snapshot(topics=[type("T", (), {"topic": "闲聊"})()])
    topic_candidate = decision_pipeline.Candidate(
        "goal_compile", None, None, {"type": "闲聊"}
    )
    assert decision_pipeline._interest(topic_candidate, topic_snapshot) == 0.4


def test_capability_note_lowers_interest_only_for_matching_tool(
    db_session_factory, tool_reflection_on
):
    seed_insight(
        db_session_factory,
        "ins-tool009-lower",
        insight_type="capability_note",
        statement="天气接口不可靠",
        confidence=0.7,
        tool_ids=(TOOL_WEATHER,),
    )
    signal = tool_feed.interest_signal(USER)
    assert [item["type"] for item in signal] == ["capability_note"]

    class _Focus:
        goal_id = "g-1"

    matched = decision_pipeline.Candidate("capability", None, "g-1", {"tool_id": TOOL_WEATHER})
    other = decision_pipeline.Candidate("capability", None, "g-1", {"tool_id": TOOL_REMINDER})
    base = decision_pipeline._interest(matched, _Snapshot(focus=_Focus()))
    lowered = decision_pipeline._interest(matched, _Snapshot(focus=_Focus()), signal)
    untouched = decision_pipeline._interest(other, _Snapshot(focus=_Focus()), signal)
    assert base == 0.6
    assert lowered == pytest.approx(0.39)
    assert untouched == 0.6
    silence = decision_pipeline.Candidate("silence", None, None)
    assert decision_pipeline._interest(silence, _Snapshot(focus=_Focus()), signal) == (
        decision_pipeline._interest(silence, _Snapshot(focus=_Focus()))
    )


def test_usage_preference_raises_interest(db_session_factory, tool_reflection_on):
    seed_insight(
        db_session_factory,
        "ins-tool009-boost",
        insight_type="usage_preference",
        statement="用户喜欢我提前一天提醒",
        confidence=1.0,
        scope="user",
        tool_ids=(TOOL_REMINDER,),
    )
    signal = tool_feed.interest_signal(USER)
    candidate = _candidate(TOOL_REMINDER)
    assert decision_pipeline._interest(candidate, _Snapshot(), signal) == pytest.approx(0.1)
    assert decision_pipeline._interest(candidate, _Snapshot(), None) == 0.0


def test_run_pipeline_threads_tool_insights(db_session_factory, tool_reflection_on):
    seed_insight(
        db_session_factory,
        "ins-tool009-pipeline",
        insight_type="capability_note",
        statement="天气接口不可靠",
        confidence=0.7,
        tool_ids=(TOOL_WEATHER,),
    )
    signal = tool_feed.interest_signal(USER)
    without = decision_pipeline.run_pipeline(
        capabilities=[TOOL_WEATHER], chat_response=True, now=NOW
    )
    with_signal = decision_pipeline.run_pipeline(
        capabilities=[TOOL_WEATHER],
        chat_response=True,
        now=NOW,
        tool_insights=signal,
    )
    def _interest_of(result):
        return next(
            item["scores"]["interest"]
            for item in result.audit["candidates"]
            if item.get("tool_id") == TOOL_WEATHER
        )

    assert _interest_of(without) == 0.0
    assert _interest_of(with_signal) == 0.0  # 无 snapshot → interest 维不臆造信号


# --- 消费侧：autonomy_policy --------------------------------------------------


def _signal():
    from app.models.autonomy import TriggerSignal

    return TriggerSignal(
        type="conversation_inactivity",
        user_id=USER,
        detected_at=NOW,
        dedupe_key=f"conversation_inactivity:{USER}:1",
    )


def _snapshot(**overrides):
    values = {
        "intimacy": 0.6,
        "mood": "calm",
        "selected_goal_type": "user_care",
        "current_activity": "",
        "attempt_count": 0,
        "generating": False,
    }
    values.update(overrides)
    return autonomy_policy.PolicySnapshot(**values)


def test_autonomy_default_reason_unchanged():
    default = autonomy_policy.evaluate(_signal(), _snapshot(), now=NOW)
    with_empty = autonomy_policy.evaluate(
        _signal(), _snapshot(tool_insights={}), now=NOW
    )
    assert default == with_empty


def test_autonomy_appends_tool_insight_notes():
    verdict = autonomy_policy.evaluate(
        _signal(),
        _snapshot(
            tool_insights={
                "notes": ["能力自省：天气接口不稳定"],
                "unreliable_capabilities": ["天气接口不稳定"],
            }
        ),
        now=NOW,
    )
    assert "能力自省：天气接口不稳定" in verdict.reason
    assert verdict.decision == "act"


def test_autonomy_notes_do_not_change_decision():
    base = autonomy_policy.evaluate(_signal(), _snapshot(), now=NOW)
    with_notes = autonomy_policy.evaluate(
        _signal(), _snapshot(tool_insights={"notes": ["使用偏好：少发提醒"]}), now=NOW
    )
    assert base.decision == with_notes.decision
    assert base.intention == with_notes.intention
    assert base.goal_id == with_notes.goal_id


def test_autonomy_notes_are_bounded_to_sixty_chars():
    notes = ["能力自省：" + "很长的描述" * 20]
    verdict = autonomy_policy.evaluate(
        _signal(), _snapshot(tool_insights={"notes": notes}), now=NOW
    )
    assert len(verdict.reason) <= 60
    assert verdict.reason.startswith("触发")


def test_collect_tool_insights_degrades_to_empty(db_session_factory, v24_tool_env, monkeypatch):
    from app.application import autonomy_engine

    v24_tool_env(TOOL_SYSTEM_ENABLED=True)
    assert autonomy_engine.collect_tool_insights(USER) == {}
    v24_tool_env(
        TOOL_SYSTEM_ENABLED=True,
        TOOL_REFLECTION_ENABLED=True)
    seed_insight(
        db_session_factory,
        "ins-tool009-autonomy",
        insight_type="capability_note",
        statement="天气接口不可靠",
        tool_ids=(TOOL_WEATHER,),
    )
    payload = autonomy_engine.collect_tool_insights(USER)
    assert payload["count"] == 1
    assert payload["insights"][0]["tool_ids"] == [TOOL_WEATHER]


def test_evidence_link_namespace_roundtrip():
    from app.services.reflection import evidence as reflection_evidence

    evidence_id = reflection_evidence.tool_evidence_id(TOOL_WEATHER, "act-1", 0)
    assert evidence_id == f"tool:{TOOL_WEATHER}:act-1:0"
    assert reflection_evidence.tool_id_of_evidence_id(evidence_id) == TOOL_WEATHER
    assert reflection_evidence.tool_id_of_evidence_id("") is None
    assert reflection_evidence.tool_id_of_evidence_id("tool:") is None
