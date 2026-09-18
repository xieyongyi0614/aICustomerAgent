"""TOOL-009 §6.2/§6.3：工具证据 reinforce 计数、三道闸零豁免、幂等键与 E5/E6/E14。

工具证据与用户证据走同一 `trigger_for_user`（同一函数、同一顺序、同一判定），
仅证据源与幂等键不同；额度语义共享，两通道各自独立入队。
"""

from datetime import datetime, timedelta

import pytest

from app.core.db import BackgroundJobRow, ReflectionRunRow
from app.core.settings import get_settings
from app.repositories import background_job_repository
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import triggers
from tests.v24.tool009_support import (
    USER,
    ScriptedLLM,
    StubTrace,
    TOOL_WEATHER,
    fake_tool_package,
    memory_window,
    seed_tool_series,
    tool_evidence_window,
)

NOW = datetime(2026, 9, 14, 12, 0, 0)


@pytest.fixture
def tool_reflection_on(v24_tool_env):
    """反思总闸 + 工具反思子闸双开（V2.4.0 工具证据通道的最小开启面）。"""
    v24_tool_env(
        V24_TOOL_SYSTEM_ENABLED=True,
        V24_TOOL_REFLECTION_ENABLED=True)
    triggers.reset_trigger_state()
    yield
    triggers.reset_trigger_state()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch):
    from app.services.reflection import reflector

    llm = ScriptedLLM()
    monkeypatch.setattr(reflector, "_resolve_llm", lambda settings: llm)
    return llm


def _patch_tool_package(monkeypatch, package):
    monkeypatch.setattr(
        reflection_evidence,
        "aggregate_tool_evidence",
        lambda user_id, *, now=None, trace=None: package,
    )


def _patch_memory_windows(monkeypatch, windows):
    monkeypatch.setattr(
        reflection_evidence,
        "aggregate_evidence_windows",
        lambda user_id, character_id="asuna", now=None, trace=None: list(windows),
    )


def _runs(session_factory):
    with session_factory() as session:
        rows = session.query(ReflectionRunRow).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


def _jobs(session_factory):
    with session_factory() as session:
        rows = session.query(BackgroundJobRow).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


# --- 子闸 / 总闸门控 ---------------------------------------------------------


def test_tool_channel_off_without_sub_flag(db_session_factory, v24_tool_env, monkeypatch):
    """工具反思子闸 off：工具通道返回 off 且零落行、零入队。"""
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=True)
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    assert triggers.tool_channel_enabled(get_settings()) is False
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "off"
    assert _runs(db_session_factory) == []
    assert _jobs(db_session_factory) == []


# --- reinforce 计数 ----------------------------------------------------------


def test_reinforce_below_threshold_does_not_fire(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """阈值以下不触发（同 tool_id 同 failure_kind 计数）。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    fired = triggers.observe_tool_evidence(
        USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
    )
    assert fired is False
    assert triggers.observe_tool_evidence(
        USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
    ) is False
    assert _runs(db_session_factory) == []
    assert _jobs(db_session_factory) == []


def test_reinforce_reaches_threshold_and_fires(
    db_session_factory, tool_reflection_on, monkeypatch
):
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    fired = [
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
        )
        for _ in range(3)
    ]
    assert fired == [False, False, True]
    runs = _runs(db_session_factory)
    assert [run.status for run in runs] == ["queued"]
    jobs = _jobs(db_session_factory)
    assert [job.idempotency_key for job in jobs] == [f"reflect:tool:{USER}:2026-09-14"]
    assert runs[0].evidence_summary["channel"] == "tool"
    assert runs[0].llm_used is False


def test_reinforce_failure_kinds_are_counted_separately(
    db_session_factory, tool_reflection_on, monkeypatch
):
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    for kind in ("transient", "timeout", "permanent", "unavailable"):
        assert (
            triggers.observe_tool_evidence(
                USER, tool_id=TOOL_WEATHER, failure_kind=kind, now=NOW
            )
            is False
        )
    assert triggers.observe_tool_evidence(
        USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
    ) is False
    assert _runs(db_session_factory) == []


def test_reinforce_cooldown_blocks_repeat_fire(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """冷却窗内重复证据不重复触发（复用既有 REF-003 冷却窗机制）。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    for _ in range(3):
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
        )
    assert len(_jobs(db_session_factory)) == 1
    later = NOW + timedelta(hours=1)
    fired = [
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=later
        )
        for _ in range(3)
    ]
    assert fired == [False, False, False]
    assert len(_jobs(db_session_factory)) == 1


def test_reinforce_after_cooldown_fires_again(
    db_session_factory, tool_reflection_on, monkeypatch
):
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    for _ in range(3):
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
        )
    run = _runs(db_session_factory)[0]
    with db_session_factory() as session:
        session.query(ReflectionRunRow).filter(ReflectionRunRow.id == run.id).delete()
        session.commit()
    later = NOW + timedelta(hours=25)
    fired = [
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=later
        )
        for _ in range(3)
    ]
    assert fired[-1] is True


def test_records_projection_feeds_reinforce_once_per_evidence(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """`action_records` 补扫：同一证据只计一次（跨轮重复补扫不放大计数）。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        now=NOW,
        step_hours=13,
    )
    assert (
        triggers.observe_tool_evidence_from_records(USER, now=NOW) == 1
    )
    assert triggers.observe_tool_evidence_from_records(USER, now=NOW) == 0
    assert len(_jobs(db_session_factory)) == 1


def test_records_projection_skips_when_flag_off(db_session_factory, v24_tool_env):
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=True)
    assert triggers.observe_tool_evidence_from_records(USER, now=NOW) == 0


# --- 三道闸：证据门槛（0 LLM）------------------------------------------------


def test_evidence_gate_failure_skips_with_zero_llm(
    db_session_factory, tool_reflection_on, monkeypatch, _patch_llm
):
    """证据门槛未过 → skipped 且零 LLM 调用（工具证据零豁免）。"""
    _patch_tool_package(monkeypatch, fake_tool_package([]))
    outcome = triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL)
    assert outcome == "skipped"
    runs = _runs(db_session_factory)
    assert [run.status for run in runs] == ["skipped"]
    assert runs[0].outcome == "no_passing_tool_window"
    assert runs[0].llm_used is False
    assert _patch_llm.calls == 0
    assert _jobs(db_session_factory) == []


def test_skipped_tool_run_carries_full_evidence_package(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """§2.2 证据包结构：tool_windows + existing_windows + passing。"""
    _patch_tool_package(monkeypatch, fake_tool_package([]))
    _patch_memory_windows(monkeypatch, [memory_window()])
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "skipped"
    summary = _runs(db_session_factory)[0].evidence_summary
    assert summary["channel"] == "tool"
    assert summary["passing"] == 0
    assert "tool_windows" in summary
    assert summary["existing_windows"] == {"count": 1, "passing": 1}


def test_live_projection_below_gate_skips_with_zero_llm(
    db_session_factory, tool_reflection_on, monkeypatch, _patch_llm
):
    """真实投影：reinforce 达标但证据窗（7 天）不足 → skipped 且 0 LLM。"""
    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        now=NOW - timedelta(days=20),
        step_hours=13,
    )
    for _ in range(3):
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
        )
    runs = _runs(db_session_factory)
    assert [run.status for run in runs] == ["skipped"]
    assert _patch_llm.calls == 0
    assert runs[0].evidence_summary["tool_windows"]["executions"] == 0


# --- 三道闸：当日额度（E5）与幂等入队（E6）----------------------------------


def test_quota_exhausted_writes_no_new_row(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """E5：当日额度已满 → 不产 Insight、不产新行（既有行为，防行膨胀）。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    with db_session_factory() as session:
        session.add(
            ReflectionRunRow(
                id="rr-existing",
                user_id=USER,
                character_id="asuna",
                trigger="scheduled",
                status="done",
                llm_used=False,
                created_at=NOW - timedelta(hours=1),
                updated_at=NOW - timedelta(hours=1),
            )
        )
        session.commit()
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "quota"
    runs = _runs(db_session_factory)
    assert [run.id for run in runs] == ["rr-existing"]
    assert _jobs(db_session_factory) == []


def test_idempotency_key_hit_does_not_enqueue_twice(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """E6：幂等键命中（同日重复触发）→ 不重复入队。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "queued"
    with db_session_factory() as session:
        session.query(ReflectionRunRow).delete()
        session.commit()
    decision = triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL)
    assert decision == "quota"
    assert len(_jobs(db_session_factory)) == 1


def test_enqueue_failure_rolls_back_run_row(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """入队异常：回滚 run 行待下轮重试（既有降级语义）。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))

    def _boom(*args, **kwargs):
        raise RuntimeError("job 表不可用")

    monkeypatch.setattr(background_job_repository, "enqueue_job", _boom)
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "skipped"
    assert _runs(db_session_factory) == []


# --- 三道闸零豁免：同一函数调用路径 -----------------------------------------


def test_both_channels_take_the_same_gate_path(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """同一函数、同一顺序、同一判定：两通道都过 `_quota_used` → `has_job` → `enqueue_job`。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    _patch_memory_windows(monkeypatch, [memory_window()])
    calls = {"quota": 0, "has_job": 0, "enqueue": 0}
    original_quota = triggers._quota_used
    original_has = background_job_repository.has_job
    original_enqueue = background_job_repository.enqueue_job

    def _quota(user_id, now):
        calls["quota"] += 1
        return original_quota(user_id, now)

    def _has(key):
        calls["has_job"] += 1
        return original_has(key)

    def _enqueue(*args, **kwargs):
        calls["enqueue"] += 1
        return original_enqueue(*args, **kwargs)

    monkeypatch.setattr(triggers, "_quota_used", _quota)
    monkeypatch.setattr(background_job_repository, "has_job", _has)
    monkeypatch.setattr(background_job_repository, "enqueue_job", _enqueue)

    memory_decision = triggers.trigger_for_user(USER, now=NOW)
    with db_session_factory() as session:
        session.query(ReflectionRunRow).delete()
        session.query(BackgroundJobRow).delete()
        session.commit()
    tool_decision = triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL)

    assert (memory_decision, tool_decision) == ("queued", "queued")
    assert calls == {"quota": 2, "has_job": 2, "enqueue": 2}


def test_memory_channel_row_shape_is_unchanged(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """既有用户通道的 evidence_summary 形状零变化（无 channel / window_kind 新键）。"""
    _patch_memory_windows(monkeypatch, [memory_window()])
    assert triggers.trigger_for_user(USER, now=NOW) == "queued"
    summary = _runs(db_session_factory)[0].evidence_summary
    assert set(summary) == {"passing", "windows"}
    assert summary["passing"] == 1
    assert _jobs(db_session_factory)[0].idempotency_key == f"reflect:{USER}:2026-09-14"


def test_memory_channel_skipped_row_shape_is_unchanged(
    db_session_factory, tool_reflection_on, monkeypatch
):
    _patch_memory_windows(monkeypatch, [])
    assert triggers.trigger_for_user(USER, now=NOW) == "skipped"
    summary = _runs(db_session_factory)[0].evidence_summary
    assert set(summary) == {"passing", "window_count", "gate_reasons", "top_window"}


# --- E14：世界（记忆）证据窗与工具窗各自独立入队、额度共享 ------------------


def test_world_and_tool_windows_enqueue_independently_sharing_quota(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """E14：两窗同时过门槛 → 幂等键不同（各自独立入队）；额度语义共享。"""
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    _patch_memory_windows(monkeypatch, [memory_window()])

    assert triggers.trigger_for_user(USER, now=NOW) == "queued"
    assert [job.idempotency_key for job in _jobs(db_session_factory)] == [
        f"reflect:{USER}:2026-09-14"
    ]
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "quota"
    assert [job.idempotency_key for job in _jobs(db_session_factory)] == [
        f"reflect:{USER}:2026-09-14"
    ]

    with db_session_factory() as session:
        session.query(ReflectionRunRow).delete()
        session.commit()
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "queued"

    keys = sorted(job.idempotency_key for job in _jobs(db_session_factory))
    assert keys == [
        f"reflect:tool:{USER}:2026-09-14",
        f"reflect:{USER}:2026-09-14",
    ]


def test_tool_window_selection_rotates_by_day(
    db_session_factory, tool_reflection_on, monkeypatch
):
    """同一批多窗达门槛：按日序轮转主分析窗口（三日一轮覆盖三类认知）。"""
    windows = [
        tool_evidence_window(window_kind="action_success_rate"),
        tool_evidence_window(window_kind="user_feedback_signal"),
        tool_evidence_window(window_kind="tool_usage_effect"),
    ]
    _patch_tool_package(monkeypatch, fake_tool_package(windows))
    chosen = []
    for day in (14, 15, 16):
        triggers.reset_trigger_state()
        with db_session_factory() as session:
            session.query(ReflectionRunRow).delete()
            session.query(BackgroundJobRow).delete()
            session.commit()
        now = datetime(2026, 9, day, 12, 0, 0)
        assert triggers.trigger_for_user(USER, now=now, channel=triggers.CHANNEL_TOOL) == "queued"
        chosen.append(_runs(db_session_factory)[0].evidence_summary["window_kind"])
    assert sorted(chosen) == [
        "action_success_rate",
        "tool_usage_effect",
        "user_feedback_signal",
    ]
    assert len(set(chosen)) == 3


def test_trace_marks_tool_channel_without_touching_memory_channel(
    db_session_factory, tool_reflection_on, monkeypatch
):
    _patch_tool_package(monkeypatch, fake_tool_package([tool_evidence_window()]))
    _patch_memory_windows(monkeypatch, [memory_window()])
    memory_trace = StubTrace()
    tool_trace = StubTrace()
    triggers.trigger_for_user(USER, now=NOW, trace=memory_trace)
    with db_session_factory() as session:
        session.query(ReflectionRunRow).delete()
        session.query(BackgroundJobRow).delete()
        session.commit()
    triggers.trigger_for_user(
        USER, now=NOW, trace=tool_trace, channel=triggers.CHANNEL_TOOL
    )
    assert "channel" not in memory_trace.steps[0]
    assert tool_trace.steps[0]["channel"] == "tool"
