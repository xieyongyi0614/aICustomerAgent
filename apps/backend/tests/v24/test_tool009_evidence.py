"""TOOL-009 §6.1/§6.3：三个工具效能证据窗、门槛判定、数据来源纪律与异常降级。

覆盖：窗口一/二/三各达门槛与未达门槛、`passes_tool_gate` 三规则、E1~E4 / E7~E10、
数据全部来自 `action_records` 投影（零导入零调用工具注册表 / 健康度）。
"""

import logging
from datetime import datetime, timedelta

import pytest

from app.character.asuna import evaluation as asuna_evaluation
from app.services.memory2 import sources as memory_sources
from app.services.reflection import evidence as reflection_evidence
from tests.v24.tool009_support import (
    OTHER_USER,
    SESSION,
    TOOL_REMINDER,
    TOOL_SEARCH,
    TOOL_WEATHER,
    USER,
    ScriptedLLM,
    StubTrace,
    seed_human_message,
    seed_tool_series,
)

NOW = datetime(2026, 9, 14, 12, 0, 0)

WINDOW_USAGE = asuna_evaluation.TOOL_WINDOW_USAGE_EFFECT
WINDOW_RATE = asuna_evaluation.TOOL_WINDOW_ACTION_SUCCESS_RATE
WINDOW_FEEDBACK = asuna_evaluation.TOOL_WINDOW_USER_FEEDBACK

EVIDENCE_LOGGER = "app.services.reflection.evidence"


# --- 窗口一：工具使用效果 ----------------------------------------------------


def test_usage_window_aggregates_by_tool_id(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        now=NOW,
        step_hours=13,
    )
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=1,
        status="succeeded",
        failure_kind=None,
        now=NOW,
        step_hours=13,
        record_prefix="act009-ok",
    )
    usage = reflection_evidence.aggregate_tool_usage(USER, now=NOW, window_days=7)
    entry = usage[TOOL_WEATHER]
    assert entry["success_count"] == 1
    assert entry["failure_count"] == 3
    assert entry["timeout_count"] == 0
    assert entry["executions"] == 4
    assert entry["group_kind"] == "tool_id"
    assert entry["span_hours"] == pytest.approx(26.0)
    assert entry["first_used_at"] < entry["last_used_at"]


def test_usage_window_below_threshold_for_single_failure(db_session_factory):
    """E2：单次失败（样本 1）未达门槛，不产 Insight（防单点噪声）。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=1,
        status="failed",
        now=NOW,
        step_hours=13,
    )
    usage = reflection_evidence.aggregate_tool_usage(USER, now=NOW)
    thresholds = asuna_evaluation.thresholds_for(WINDOW_USAGE)
    assert reflection_evidence.passes_tool_gate(usage[TOOL_WEATHER], thresholds) is False
    assert "samples" in reflection_evidence.tool_gate_reasons(
        usage[TOOL_WEATHER], thresholds
    )
    package = reflection_evidence.aggregate_tool_evidence(USER, now=NOW)
    assert package.windows == []
    assert package.passing == 0
    assert usage[TOOL_WEATHER]["sample_observations"] == []


def test_gate_rejects_insufficient_span(db_session_factory):
    """样本数达标但时间跨度不足（同日爆发）→ 判不过（span 规则）。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=4,
        status="failed",
        now=NOW,
        step_hours=1.0,
        record_prefix="act009-span",
    )
    usage = reflection_evidence.aggregate_tool_usage(USER, now=NOW)
    thresholds = asuna_evaluation.thresholds_for(WINDOW_USAGE)
    assert usage[TOOL_WEATHER]["span_hours"] < thresholds["min_span_hours"]
    assert reflection_evidence.passes_tool_gate(usage[TOOL_WEATHER], thresholds) is False
    assert "span" in reflection_evidence.tool_gate_reasons(
        usage[TOOL_WEATHER], thresholds
    )


def test_usage_window_keeps_bounded_observation_digest(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_SEARCH,
        count=3,
        status="succeeded",
        failure_kind=None,
        now=NOW,
        step_hours=13,
    )
    from tests.v24.tool009_support import seed_record, tool_record

    for index in range(3):
        seed_record(
            db_session_factory,
            tool_record(
                TOOL_SEARCH,
                record_id=f"act009-obs-{index}",
                status="succeeded",
                observed_at=NOW - timedelta(hours=13 * (3 - index)),
                observations={
                    "total": index,
                    "top": "x" * 80,
                    "extra": "y",
                    "more": "z",
                },
            ),
        )
    usage = reflection_evidence.aggregate_tool_usage(USER, now=NOW)
    samples = usage[TOOL_SEARCH]["sample_observations"]
    assert len(samples) <= reflection_evidence.TOOL_EVIDENCE_OBSERVATION_PAIRS
    for sample in samples:
        assert "more" not in sample
        assert "x" * 41 not in sample
        assert len(sample) < 200


# --- 窗口二：Action 成功率 ---------------------------------------------------


def test_success_rate_groups_by_tool_and_action_type(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        now=NOW,
        step_hours=13,
    )
    rate = reflection_evidence.aggregate_success_rate(USER, now=NOW)
    tool_entry = rate["tool_id:ext.api.weather.current"]
    assert tool_entry["group_kind"] == "tool_id"
    assert tool_entry["total"] == 3
    assert tool_entry["failed"] == 3
    assert tool_entry["failure_kinds"] == {"transient": 3}
    assert tool_entry["window_days"] == reflection_evidence.TOOL_EVIDENCE_WINDOW_DAYS
    assert tool_entry["failure_rate"] == 1.0
    action_entry = rate["action_type:query_environment"]
    assert action_entry["total"] == 3


def test_failure_kinds_are_counted_independently(db_session_factory):
    """E3：同 tool_id 但 failure_kind 各异 → 各 kind 独立成组、独立判门槛。"""
    for index, kind in enumerate(("transient", "timeout", "permanent", "unavailable")):
        seed_tool_series(
            db_session_factory,
            tool_id=TOOL_SEARCH,
            count=1,
            status="failed",
            failure_kind=kind,
            now=NOW - timedelta(hours=13 * (4 - index)),
            step_hours=13,
            record_prefix=f"act009-{kind}",
        )
    rate = reflection_evidence.aggregate_success_rate(USER, now=NOW)
    thresholds = asuna_evaluation.thresholds_for(WINDOW_RATE)
    for kind in ("transient", "timeout", "permanent", "unavailable"):
        entry = rate[f"failure_kind:{TOOL_SEARCH}|{kind}"]
        assert entry["total"] == 1
        assert entry["failed"] == 1
        assert reflection_evidence.passes_tool_gate(entry, thresholds) is False
    tool_entry = rate[f"tool_id:{TOOL_SEARCH}"]
    assert tool_entry["total"] == 4
    assert reflection_evidence.passes_tool_gate(tool_entry, thresholds) is True


def test_success_rate_gate_requires_failures(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_SEARCH,
        count=3,
        status="succeeded",
        failure_kind=None,
        now=NOW,
        step_hours=13,
    )
    rate = reflection_evidence.aggregate_success_rate(USER, now=NOW)
    thresholds = asuna_evaluation.thresholds_for(WINDOW_RATE)
    entry = rate[f"tool_id:{TOOL_SEARCH}"]
    assert entry["total"] == 3
    assert reflection_evidence.passes_tool_gate(entry, thresholds) is False
    assert "failures" in reflection_evidence.tool_gate_reasons(entry, thresholds)


# --- 窗口三：用户反馈 --------------------------------------------------------


def test_feedback_window_detects_negative_followup(db_session_factory):
    """E7：工具失败后用户下一轮表达不满 → 负反馈；与窗口二各自独立计数。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        now=NOW,
        step_hours=13,
    )
    seed_human_message(
        db_session_factory, "这不对吧，怎么又失败了", created_at=NOW - timedelta(hours=2)
    )
    feedback = reflection_evidence.aggregate_user_feedback(USER, now=NOW)
    entry = feedback[TOOL_WEATHER]
    assert entry["executions"] == 3
    assert entry["followup_negative"] == 3
    assert entry["silence_after"] == 0
    package = reflection_evidence.aggregate_tool_evidence(USER, now=NOW)
    passing_kinds = {window.window_kind for window in package.windows}
    assert WINDOW_RATE in passing_kinds
    assert WINDOW_FEEDBACK in passing_kinds


def test_feedback_window_counts_silence_without_negative(db_session_factory):
    """E8：工具失败但用户下一轮无任何消息 → 计入 silence_after，不误判负反馈。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        user_id=OTHER_USER,
        session_id="conv-tool009-silent",
        now=NOW,
        step_hours=30,
    )
    feedback = reflection_evidence.aggregate_user_feedback(OTHER_USER, now=NOW)
    entry = feedback[TOOL_WEATHER]
    assert entry["executions"] == 3
    assert entry["silence_after"] == 3
    assert entry["followup_negative"] == 0


def test_feedback_window_ignores_young_silence(db_session_factory):
    """E8 防误判：刚执行的工具（未老于沉默门槛）不计沉默。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        user_id=OTHER_USER,
        session_id="conv-tool009-young",
        now=NOW,
        step_hours=1.0,
        record_prefix="act009-young",
    )
    feedback = reflection_evidence.aggregate_user_feedback(
        OTHER_USER, now=NOW, window_days=7
    )
    entry = feedback[TOOL_WEATHER]
    assert entry["executions"] == 3
    assert entry["silence_after"] == 0


def test_feedback_window_neutral_message_counts_neither(db_session_factory):
    """E10：N 轮内用户消息极性中性 → 不计正也不计负（避免噪声）。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_REMINDER,
        count=3,
        status="succeeded",
        failure_kind=None,
        user_id=OTHER_USER,
        session_id="conv-tool009-neutral",
        now=NOW,
        step_hours=13,
        record_prefix="act009-neutral",
    )
    seed_human_message(
        db_session_factory,
        "嗯",
        created_at=NOW - timedelta(hours=2),
        conversation_id="conv-tool009-neutral",
    )
    feedback = reflection_evidence.aggregate_user_feedback(OTHER_USER, now=NOW)
    entry = feedback[TOOL_REMINDER]
    assert entry["followup_neutral"] == 3
    assert entry["followup_negative"] == 0
    assert entry["followup_positive"] == 0


def test_feedback_window_positive_message_is_not_negative(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_REMINDER,
        count=3,
        status="succeeded",
        failure_kind=None,
        user_id=OTHER_USER,
        session_id="conv-tool009-positive",
        now=NOW,
        step_hours=13,
        record_prefix="act009-pos",
    )
    seed_human_message(
        db_session_factory,
        "谢谢你，辛苦了",
        created_at=NOW - timedelta(hours=1),
        conversation_id="conv-tool009-positive",
    )
    feedback = reflection_evidence.aggregate_user_feedback(OTHER_USER, now=NOW)
    entry = feedback[TOOL_REMINDER]
    assert entry["followup_positive"] == 3
    assert entry["followup_negative"] == 0
    assert entry["revoked_after"] == 0


def test_feedback_window_detects_revoke_after_cancel_action(db_session_factory):
    """E9：用户撤销了工具产生的效果（cancel 记录）→ 计入 revoked_after。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_REMINDER,
        count=3,
        status="succeeded",
        failure_kind=None,
        user_id=OTHER_USER,
        session_id=SESSION,
        now=NOW,
        step_hours=13,
        record_prefix="act009-rv",
    )
    from tests.v24.tool009_support import seed_record, tool_record

    seed_record(
        db_session_factory,
        tool_record(
            TOOL_REMINDER,
            record_id="act009-rv-cancel",
            user_id=OTHER_USER,
            status="succeeded",
            action_type="cancel_reminder",
            source="cancel",
            observed_at=NOW - timedelta(hours=1),
        ),
    )
    feedback = reflection_evidence.aggregate_user_feedback(OTHER_USER, now=NOW)
    entry = feedback[TOOL_REMINDER]
    assert entry["executions"] == 3
    assert entry["revoked_after"] == 3


def test_feedback_window_requires_followup_turns_to_be_applied(db_session_factory):
    """跟随窗按 N 轮截断：第 N+1 轮起不计。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_REMINDER,
        count=3,
        status="succeeded",
        failure_kind=None,
        user_id=OTHER_USER,
        session_id="conv-tool009-turns",
        now=NOW,
        step_hours=13,
        record_prefix="act009-turns",
    )
    for index in range(3):
        seed_human_message(
            db_session_factory,
            f"第 {index} 轮",
            created_at=NOW - timedelta(hours=5 - index),
            conversation_id="conv-tool009-turns",
        )
    feedback = reflection_evidence.aggregate_user_feedback(
        OTHER_USER, now=NOW, followup_turns=1
    )
    entry = feedback[TOOL_REMINDER]
    assert entry["followup_neutral"] == 3


# --- E1：无任何工具执行记录 --------------------------------------------------


def test_no_tool_executions_yields_empty_windows(db_session_factory):
    """E1：三窗全空；无达门槛窗口（调用方 → skipped 且 0 LLM）。"""
    package = reflection_evidence.aggregate_tool_evidence(USER, now=NOW)
    assert package.windows == []
    assert package.passing == 0
    assert package.executions == 0
    assert reflection_evidence.aggregate_tool_usage(USER, now=NOW) == {}
    assert reflection_evidence.aggregate_success_rate(USER, now=NOW) == {}
    assert reflection_evidence.aggregate_user_feedback(USER, now=NOW) == {}


# --- E4：聚合异常 ------------------------------------------------------------


def test_projection_failure_degrades_to_empty_with_log(
    db_session_factory, monkeypatch, caplog
):
    """E4：证据聚合抛异常 → 空 dict + 日志（按门槛未过处理），不阻断主流程。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("action_records 不可读")

    monkeypatch.setattr(memory_sources, "fetch_action_records", _boom)
    with caplog.at_level(logging.ERROR, logger=EVIDENCE_LOGGER):
        assert reflection_evidence.aggregate_tool_usage(USER, now=NOW) == {}
        assert reflection_evidence.aggregate_success_rate(USER, now=NOW) == {}
        assert reflection_evidence.aggregate_user_feedback(USER, now=NOW) == {}
        package = reflection_evidence.aggregate_tool_evidence(USER, now=NOW)
    assert package.windows == []
    assert "聚合异常" in caplog.text


def test_projection_failure_is_isolated_per_window(
    db_session_factory, monkeypatch, caplog
):
    """单窗聚合异常不污染其余窗口（各窗独立 try/降级）。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        now=NOW,
        step_hours=13,
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("messages 表不可读")

    monkeypatch.setattr(reflection_evidence, "_human_messages_after", _boom)
    with caplog.at_level(logging.ERROR, logger=EVIDENCE_LOGGER):
        package = reflection_evidence.aggregate_tool_evidence(USER, now=NOW)
    assert reflection_evidence.aggregate_user_feedback(USER, now=NOW) == {}
    assert package.executions == 3
    assert WINDOW_USAGE in {window.window_kind for window in package.windows}
    assert WINDOW_FEEDBACK not in {window.window_kind for window in package.windows}
    assert "用户反馈窗聚合异常" in caplog.text


# --- 达门槛窗口结构 + 数据来源纪律 -------------------------------------------


def test_tool_evidence_window_structure_and_types(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        now=NOW,
        step_hours=13,
    )
    package = reflection_evidence.aggregate_tool_evidence(USER, now=NOW)
    assert package.passing == len(package.windows) >= 1
    for window in package.windows:
        assert window.kind == "tool_evidence"
        assert window.window_kind in asuna_evaluation.TOOL_WINDOW_KINDS
        assert window.insight_types == asuna_evaluation.allowed_insight_types(
            window.window_kind
        )
        assert window.gate_reasons == []
        assert window.stats.member_count >= 3
        assert window.stats.coherence == 1.0
        assert all(
            member.memory_id.startswith("tool:") for member in window.members
        )
        assert all(member.source == "tool_execution" for member in window.members)
    kinds = [window.window_kind for window in package.windows]
    assert kinds == sorted(kinds, key=reflection_evidence._kind_priority)


def test_window_priority_order_is_deterministic():
    assert reflection_evidence.order_tool_window_kinds(
        [WINDOW_USAGE, WINDOW_FEEDBACK, WINDOW_RATE]
    ) == [WINDOW_RATE, WINDOW_FEEDBACK, WINDOW_USAGE]
    assert reflection_evidence.order_tool_window_kinds([]) == []
    assert reflection_evidence.order_tool_window_kinds(["unknown"]) == []


def test_evidence_module_never_imports_tool_registry():
    """数据来源纪律（静态）：反思证据模块零导入工具注册表 / 健康度。"""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "app/services/reflection/evidence.py"
    ).read_text(encoding="utf-8")
    assert "from app.services.tool" not in source
    assert "services.tool.registry" not in source
    assert ".record_outcome(" not in source
    assert ".mark_tripped(" not in source
    assert ".clear_tripped(" not in source
    assert "get_tool_registry" not in source


def test_aggregation_reads_only_action_record_projection(
    db_session_factory, monkeypatch
):
    """数据来源纪律（运行期）：只经 `fetch_action_records` 取工具执行事实。"""
    calls: list[tuple] = []
    original = memory_sources.fetch_action_records

    def _spy(user_id, limit=20):
        calls.append((user_id, limit))
        return original(user_id, limit=limit)

    monkeypatch.setattr(memory_sources, "fetch_action_records", _spy)
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        now=NOW,
        step_hours=13,
    )
    package = reflection_evidence.aggregate_tool_evidence(USER, now=NOW)
    assert package.executions == 3
    assert calls and all(call[0] == USER for call in calls)


def test_tool_fact_projection_is_read_only(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=2,
        status="failed",
        now=NOW,
        step_hours=13,
    )
    facts = reflection_evidence.tool_fact_projection(USER, now=NOW)
    assert len(facts) == 2
    assert {fact.tool_id for fact in facts} == {TOOL_WEATHER}
    assert all(
        reflection_evidence.tool_id_of_evidence_id(fact.evidence_id) == TOOL_WEATHER
        for fact in facts
    )
    assert reflection_evidence.tool_id_of_evidence_id("memory:abc") is None


def test_trace_records_tool_evidence_step(db_session_factory):
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        now=NOW,
        step_hours=13,
    )
    trace = StubTrace()
    reflection_evidence.aggregate_tool_evidence(USER, now=NOW, trace=trace)
    steps = [step for step in trace.steps if step["name"] == "reflection_tool_evidence"]
    assert steps and steps[0]["executions"] == 3
