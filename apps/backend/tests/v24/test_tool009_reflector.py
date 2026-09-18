"""TOOL-009 §6.1/§6.2/§6.3：Insight 类型产出、类型闸、隔离断言（反思不熔断工具）、
Flag off 逐字节一致与离线评估场景（E11~E13）。
"""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.character.asuna import evaluation as asuna_evaluation
from app.core.db import BackgroundJobRow, InsightRow, Memory, ReflectionRunRow
from app.core.settings import get_settings
from app.models.reflection import ToolEvidenceWindow
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import evaluation as reflection_evaluation
from app.services.reflection import reflector, triggers
from tests.v24.tool009_support import (
    CHARACTER,
    USER,
    ScriptedLLM,
    StubTrace,
    TOOL_REMINDER,
    TOOL_WEATHER,
    registry_snapshot,
    seed_record,
    seed_tool_series,
    tool_capability_proposal,
    tool_evidence_window,
    tool_record,
)

NOW = datetime(2026, 9, 14, 12, 0, 0)
BACKEND_ROOT = Path(__file__).resolve().parents[2]

WINDOW_USAGE = asuna_evaluation.TOOL_WINDOW_USAGE_EFFECT
WINDOW_RATE = asuna_evaluation.TOOL_WINDOW_ACTION_SUCCESS_RATE
WINDOW_FEEDBACK = asuna_evaluation.TOOL_WINDOW_USER_FEEDBACK


@pytest.fixture
def tool_reflection_on(v24_tool_env):
    v24_tool_env(
        V24_TOOL_SYSTEM_ENABLED=True,
        V24_TOOL_REFLECTION_ENABLED=True)
    triggers.reset_trigger_state()
    yield
    triggers.reset_trigger_state()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch):
    llm = ScriptedLLM()
    monkeypatch.setattr(reflector, "_resolve_llm", lambda settings: llm)
    return llm


def _runs(session_factory):
    with session_factory() as session:
        rows = session.query(ReflectionRunRow).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


def _insights(session_factory, user_id=USER):
    with session_factory() as session:
        rows = (
            session.query(InsightRow).filter(InsightRow.user_id == user_id).all()
        )
        for row in rows:
            session.expunge(row)
        return list(rows)


def _queued_run_id(session_factory) -> str:
    with session_factory() as session:
        row = (
            session.query(ReflectionRunRow)
            .filter(ReflectionRunRow.status == "queued")
            .first()
        )
        assert row is not None
        return row.id


def _execute_queued(session_factory, llm, proposal) -> str:
    run_id = _queued_run_id(session_factory)
    llm.proposals = [proposal]
    assert reflector._claim_run(run_id, datetime.now()) is True
    outcome = reflector.execute_run(run_id)
    return outcome


def _pin_window_kind(session_factory, window_kind: str) -> None:
    """把触发侧裁决的窗口名改成指定值（窗口轮转下让用例聚焦单一窗口语义）。"""
    with session_factory() as session:
        row = (
            session.query(ReflectionRunRow)
            .filter(ReflectionRunRow.status == "queued")
            .first()
        )
        assert row is not None
        summary = dict(row.evidence_summary)
        summary["window_kind"] = window_kind
        row.evidence_summary = summary
        session.commit()


def _seed_tool_failures(session_factory, *, tool_id=TOOL_WEATHER, count=3):
    return seed_tool_series(
        session_factory,
        tool_id=tool_id,
        count=count,
        status="failed",
        failure_kind="transient",
        now=NOW,
        step_hours=13,
    )


def _fire_tool_channel(session_factory, *, times=3):
    for _ in range(times):
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
        )


# --- §6.1 三类 Insight 产出正确 ---------------------------------------------


def test_tool_window_persists_capability_note(
    db_session_factory, tool_reflection_on, _patch_llm
):
    _seed_tool_failures(db_session_factory)
    _fire_tool_channel(db_session_factory)
    _pin_window_kind(db_session_factory, WINDOW_RATE)
    outcome = _execute_queued(db_session_factory, _patch_llm, tool_capability_proposal())
    assert outcome == "done"
    assert _patch_llm.calls == 1
    insights = _insights(db_session_factory)
    assert len(insights) == 1
    insight = insights[0]
    assert insight.type == "capability_note"
    assert insight.scope == "world"
    assert insight.confidence >= get_settings().v2_reflection_min_confidence
    with db_session_factory() as session:
        links = session.query(Memory.id).all()
    assert links == []


def test_tool_run_window_kind_drives_type(
    db_session_factory, tool_reflection_on, _patch_llm
):
    """窗口一/三各自产出其 Insight 类型（同一反射路径，类型由窗口裁决）。"""
    cases = (
        (WINDOW_USAGE, "usage_preference", "user", "act009-usage"),
        (WINDOW_FEEDBACK, "interaction_calibration", "user", "act009-feedback"),
    )
    for window_kind, insight_type, scope, prefix in cases:
        triggers.reset_trigger_state()
        with db_session_factory() as session:
            session.query(ReflectionRunRow).delete()
            session.query(BackgroundJobRow).delete()
            session.query(InsightRow).delete()
            session.commit()
        seed_tool_series(
            db_session_factory,
            tool_id=TOOL_WEATHER,
            count=4,
            status="failed",
            failure_kind="transient",
            now=NOW,
            step_hours=13,
            record_prefix=prefix,
        )
        _fire_tool_channel(db_session_factory)
        _pin_window_kind(db_session_factory, window_kind)
        outcome = _execute_queued(
            db_session_factory,
            _patch_llm,
            tool_capability_proposal(insight_type=insight_type, scope=scope),
        )
        assert outcome == "done"
        insights = _insights(db_session_factory)
        assert [insight.type for insight in insights] == [insight_type]
        assert asuna_evaluation.scope_for(window_kind) == scope


@pytest.mark.parametrize(
    "window_kind,allowed",
    (
        (WINDOW_RATE, ("capability_note",)),
        (WINDOW_USAGE, ("usage_preference", "capability_note")),
        (WINDOW_FEEDBACK, ("interaction_calibration", "usage_preference")),
    ),
)
def test_review_rejects_types_outside_window_domain(window_kind, allowed, tool_reflection_on):
    """类型闸：窗口只允许资产声明的 Insight 类型（越界一律拒绝）。"""
    window = tool_evidence_window(window_kind=window_kind)
    assert window.insight_types == allowed
    proposal = tool_capability_proposal(insight_type="belief", scope="user")
    accepted, rejected = reflector._calibrate_and_review(
        proposal, window, window.members, get_settings()
    )
    assert accepted == []
    assert "insight_type_not_allowed" in rejected[0]["reasons"]


def test_review_rejects_relationship_scope(tool_reflection_on):
    """scope 闸：工具证据不下关系域结论。"""
    window = tool_evidence_window(window_kind=WINDOW_RATE)
    proposal = tool_capability_proposal(scope="relationship")
    accepted, rejected = reflector._calibrate_and_review(
        proposal, window, window.members, get_settings()
    )
    assert accepted == []
    assert "insight_scope_not_allowed" in rejected[0]["reasons"]


def test_memory_window_review_has_no_type_gate(tool_reflection_on):
    """既有记忆窗口不追加类型闸（零改动对照）。"""
    from tests.v24.tool009_support import memory_window

    window = memory_window()
    proposal = tool_capability_proposal(insight_type="belief", scope="relationship")
    accepted, rejected = reflector._calibrate_and_review(
        proposal, window, window.members, get_settings()
    )
    assert rejected == []
    assert len(accepted) == 1


def test_prohibited_proposal_is_rejected_in_full_flow(
    db_session_factory, tool_reflection_on, _patch_llm
):
    """性格 / 关系类提案在完整流程中被拒（零落库）。"""
    _seed_tool_failures(db_session_factory)
    _fire_tool_channel(db_session_factory)
    _pin_window_kind(db_session_factory, WINDOW_RATE)
    outcome = _execute_queued(
        db_session_factory,
        _patch_llm,
        tool_capability_proposal(insight_type="pattern", scope="relationship"),
    )
    assert outcome == "rejected"
    assert _insights(db_session_factory) == []
    run = _runs(db_session_factory)[0]
    assert run.outcome == "rejected"
    assert run.evidence_summary["rejected"][0]["reasons"] == [
        "insight_type_not_allowed",
        "insight_scope_not_allowed",
    ]


def test_is_personality_affecting_is_always_false():
    """防御性契约：任意入参恒返回 False（工具故障不改变人格）。"""
    for payload in (
        None,
        {},
        {"type": "capability_note"},
        tool_evidence_window(),
        {"window_kind": WINDOW_FEEDBACK, "statement": "用户很讨厌我"},
    ):
        assert asuna_evaluation.is_personality_affecting(payload) is False
    assert asuna_evaluation.insight_type_is_allowed(WINDOW_RATE, "capability_note") is True
    assert asuna_evaluation.insight_type_is_allowed(WINDOW_RATE, "belief") is False


def test_insight_type_domain_extends_only_tool_types():
    """值域扩展只增工具效能三类（不新增性格 / 人格 / 关系类）。"""
    from app.models.reflection import TOOL_INSIGHT_TYPES

    assert TOOL_INSIGHT_TYPES == (
        "capability_note",
        "usage_preference",
        "interaction_calibration",
    )
    assert asuna_evaluation.tool_insight_type_domain() == TOOL_INSIGHT_TYPES
    assert asuna_evaluation.insight_type_for(WINDOW_RATE) == "capability_note"
    with pytest.raises(ValueError):
        asuna_evaluation.insight_type_for("unknown_window")


# --- E11：Insight 不自动撤销 --------------------------------------------------


def test_insight_is_not_auto_revoked_when_tool_succeeds_later(
    db_session_factory, tool_reflection_on, _patch_llm
):
    """E11：反思产出 Insight 后工具再次成功 → Insight 不自动撤销（认知不追运维）。"""
    _seed_tool_failures(db_session_factory)
    _fire_tool_channel(db_session_factory)
    _pin_window_kind(db_session_factory, WINDOW_RATE)
    assert _execute_queued(db_session_factory, _patch_llm, tool_capability_proposal()) == "done"
    insight_id = _insights(db_session_factory)[0].id

    seed_tool_series(
        db_session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="succeeded",
        failure_kind=None,
        now=NOW + timedelta(hours=2),
        step_hours=13,
        record_prefix="act009-later",
    )
    triggers.trigger_for_user(USER, now=NOW + timedelta(hours=3), channel=triggers.CHANNEL_TOOL)
    for run_id in [run.id for run in _runs(db_session_factory) if run.status == "queued"]:
        reflector._claim_run(run_id, datetime.now())
        reflector.execute_run(run_id)
    insight = _insights(db_session_factory)[0]
    assert insight.id == insight_id
    assert insight.status == "active"
    assert insight.invalidated_at is None


# --- §6.2 隔离断言（核心）：反思不熔断工具 -----------------------------------


def test_reflection_flow_leaves_tool_registry_byte_identical(
    db_session_factory, tool_reflection_on, _patch_llm, monkeypatch
):
    """§6.2 隔离断言（核心）：完整反思流程跑完后注册表 / 健康度 / 工具面逐字节未变。"""
    from app.services.tool.registry import ToolRegistry, get_tool_registry

    registry = get_tool_registry()
    assert registry is not None
    registered_tool = sorted(registry.health())[0]
    registry.record_outcome(registered_tool, ok=False, failure_kind="transient")
    before = registry_snapshot(registry)
    before_health = registry.health()
    writes: list[tuple] = []

    def _spy(name):
        def _inner(self, *args, **kwargs):
            writes.append((name, args, kwargs))
            return None

        return _inner

    originals = {}
    for method in _REGISTRY_WRITE_METHODS:
        originals[method] = getattr(ToolRegistry, method)
        monkeypatch.setattr(ToolRegistry, method, _spy(method))

    _seed_tool_failures(db_session_factory)
    _fire_tool_channel(db_session_factory)
    _pin_window_kind(db_session_factory, WINDOW_RATE)
    assert _execute_queued(db_session_factory, _patch_llm, tool_capability_proposal()) == "done"
    assert _insights(db_session_factory)[0].type == "capability_note"

    for method, original in originals.items():
        setattr(ToolRegistry, method, original)
    assert writes == []
    assert registry_snapshot(registry) == before
    assert registry.health() == before_health
    assert registry.effective_status(registered_tool) == "enabled"


_REGISTRY_WRITE_METHODS = (
    "register",
    "unregister",
    "record_outcome",
    "mark_tripped",
    "clear_tripped",
    "set_runtime_disabled",
    "clear_runtime_disabled",
)


def test_reflection_package_has_no_registry_write_calls():
    """接口层面隔离（静态）：反思域零调用工具注册表写方法 / 零导入注册表模块。"""
    forbidden_calls = (
        ".record_outcome(",
        ".mark_tripped(",
        ".clear_tripped(",
        ".set_runtime_disabled(",
        ".clear_runtime_disabled(",
        "get_tool_registry(",
        "ToolHealthTracker(",
    )
    for path in sorted((BACKEND_ROOT / "app/services/reflection").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden_calls:
            assert token not in source, f"{path.name} 出现越界调用：{token}"
        assert "from app.services.tool" not in source
        assert "import app.services.tool" not in source


def test_tool_feed_interface_exposes_only_read_methods():
    """E12：反哺接口无任何写方法（API 形状断言）。"""
    from app.services.reflection import tool_feed

    public = [
        name
        for name in dir(tool_feed)
        if not name.startswith("_") and callable(getattr(tool_feed, name))
    ]
    assert "interest_signal" in public
    assert "autonomy_signal" in public
    assert "tool_ids_of_insights" in public
    write_prefixes = (
        "write",
        "trip",
        "disable",
        "enable",
        "record",
        "set_",
        "update",
        "delete",
        "save",
        "register",
    )
    for name in public:
        assert not name.startswith(write_prefixes), f"越界方法：{name}"


def test_full_reflection_flow_writes_no_memories(
    db_session_factory, tool_reflection_on, _patch_llm
):
    _seed_tool_failures(db_session_factory)
    for _ in range(3):
        triggers.observe_tool_evidence(
            USER, tool_id=TOOL_WEATHER, failure_kind="transient", now=NOW
        )
    _execute_queued(db_session_factory, _patch_llm, tool_capability_proposal())
    with db_session_factory() as session:
        assert session.query(Memory.id).count() == 0


# --- §6.2 Flag 全 off / 既有行为逐字节一致 -----------------------------------


def _seed_cluster_memory(session_factory, memory_id, *, created_at, content):
    with session_factory() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=USER,
                character_id=CHARACTER,
                content=content,
                type="user_fact",
                importance=0.7,
                confidence=0.9,
                source="user_stated",
                status="active",
                salience=0.8,
                source_ref={"table": "conversation", "id": f"conv:u:s:{memory_id}"},
                visibility="private",
                created_at=created_at,
                updated_at=datetime.now(),
            )
        )
        session.commit()


def _seed_memory_cluster(session_factory, count=5):
    for index in range(count):
        _seed_cluster_memory(
            session_factory,
            f"mem009-{index}",
            created_at=NOW - timedelta(days=index * 2),
            content="用户说最近加班很累" if index == 0 else f"用户说最近加班很累（第{index + 1}次）",
        )


def _window_digest(windows) -> list:
    return [
        {
            "topic": window.topic_digest,
            "members": [member.memory_id for member in window.members],
            "stats": window.stats,
            "gates": window.gate_reasons,
        }
        for window in windows
    ]


def test_existing_windows_identical_with_tool_flag_on(
    db_session_factory, v24_tool_env, override_settings
):
    """既有四个窗口的聚合在工具子闸 on / off 下逐字节一致。"""
    _seed_memory_cluster(db_session_factory)
    digest_off = _window_digest(
        reflection_evidence.aggregate_evidence_windows(USER, CHARACTER, now=NOW)
    )
    v24_tool_env(
        V24_TOOL_SYSTEM_ENABLED=True,
        V24_TOOL_REFLECTION_ENABLED=True)
    digest_on = _window_digest(
        reflection_evidence.aggregate_evidence_windows(USER, CHARACTER, now=NOW)
    )
    assert digest_off == digest_on
    assert hashlib.sha256(repr(digest_off).encode()).digest() == hashlib.sha256(
        repr(digest_on).encode()
    ).digest()


def test_memory_channel_run_unchanged_with_tool_flag_on(
    db_session_factory, tool_reflection_on, _patch_llm
):
    """工具子闸 on 且无工具证据：记忆通道 run 与既有行为一致（同类型同落库）。"""
    _seed_memory_cluster(db_session_factory)
    assert triggers.trigger_for_user(USER, character_id=CHARACTER, now=NOW) == "queued"
    proposal = tool_capability_proposal(insight_type="pattern", scope="user")
    assert _execute_queued(db_session_factory, _patch_llm, proposal) == "done"
    insights = _insights(db_session_factory)
    assert [insight.type for insight in insights] == ["pattern"]
    with db_session_factory() as session:
        links = session.query(ReflectionRunRow).first()
    assert "channel" not in (links.evidence_summary or {})


def test_tool_flag_off_keeps_trigger_behavior(
    db_session_factory, v24_tool_env, monkeypatch, _patch_llm
):
    """Flag 全 off：工具证据完全不参与，工具通道直接 off。"""
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=True)
    _seed_tool_failures(db_session_factory)
    assert triggers.tool_channel_enabled(get_settings()) is False
    assert triggers.observe_tool_evidence_from_records(USER, now=NOW) == 0
    assert triggers.trigger_for_user(USER, now=NOW, channel=triggers.CHANNEL_TOOL) == "off"
    assert _runs(db_session_factory) == []
    assert _insights(db_session_factory) == []


# --- E13：离线评估场景 -------------------------------------------------------


def _tool_seeder(session_factory, user_id, now):
    seed_tool_series(
        session_factory,
        tool_id=TOOL_WEATHER,
        count=3,
        status="failed",
        failure_kind="transient",
        user_id=user_id,
        now=now,
        step_hours=13,
        record_prefix="act009-eval",
    )


def test_offline_tool_scenario_is_reproducible(
    db_session_factory, tool_reflection_on, _patch_llm
):
    result = reflection_evaluation.run_tool_scenario(
        db_session_factory, _patch_llm, _tool_seeder, now=NOW
    )
    assert result["scenario_id"] == "tool_effectiveness"
    assert result["passed"] is True, result["failures"]
    assert result["insights"] >= 1
    assert result["outcome"] == "insights_created"
    assert result["llm_calls"] == 1


def test_offline_tool_scenario_requires_injected_seeder(
    db_session_factory, tool_reflection_on, _patch_llm
):
    result = reflection_evaluation.run_tool_scenario(
        db_session_factory, _patch_llm, None, now=NOW
    )
    assert result["passed"] is False
    assert result["failures"] == ["缺少注入式工具证据 seeder"]


def test_offline_tool_scenario_flags_type_violation(
    db_session_factory, tool_reflection_on, _patch_llm
):
    """注入越界提案 → 场景失败（类型闸在离线场景内同样生效）。"""

    def _seeder(session_factory, user_id, now):
        _tool_seeder(session_factory, user_id, now)
        _patch_llm.proposals = [
            tool_capability_proposal(insight_type="pattern", scope="relationship")
        ]

    result = reflection_evaluation.run_tool_scenario(
        db_session_factory, _patch_llm, _seeder, now=NOW
    )
    assert result["passed"] is False
    assert any("未产出工具效能 Insight" in item for item in result["failures"])


def test_offline_existing_scenarios_untouched():
    """既有 E-REF-01~04 场景集与 Gate 指标零改动。"""
    assert reflection_evaluation.SCENARIO_TOOL_EFFECTIVENESS == "tool_effectiveness"
    assert (
        reflection_evaluation.SCENARIO_TOOL_EFFECTIVENESS
        not in reflection_evaluation.KIND_TO_METRIC
    )
    assert set(reflection_evaluation.GATE_THRESHOLDS) == {
        "E-REF-01",
        "E-REF-01-JUDGE",
        "E-REF-02",
        "E-REF-03",
        "E-REF-04",
    }


# --- 冻结面 -------------------------------------------------------------------


def test_tool_evidence_window_is_a_memory_evidence_window_subclass():
    window = tool_evidence_window()
    assert isinstance(window, ToolEvidenceWindow)
    assert window.passes_gate is True
    trace = StubTrace()
    trace.record("reflection_evidence", 1.0, "ok", windows=[])
    assert trace.steps[0]["name"] == "reflection_evidence"


def test_seeded_record_shape_is_terminal(db_session_factory):
    seed_record(
        db_session_factory,
        tool_record(
            TOOL_REMINDER,
            record_id="act009-frozen",
            status="succeeded",
            observed_at=NOW,
        ),
    )
    facts = reflection_evidence.tool_fact_projection(USER, now=NOW)
    assert [fact.status for fact in facts] == ["succeeded"]
    assert facts[0].failure_kind is None
