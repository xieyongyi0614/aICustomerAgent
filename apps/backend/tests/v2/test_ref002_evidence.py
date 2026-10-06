"""REF-002：Evidence Window 聚合。

贪心聚类（语义邻域/关键词/混合/embedding NULL 降级）、组统计数值、passes_gate
三闸表驱动、tasks.md 验收场景（10 天 5 条同主题聚为一组；孤立单条不成组；
同 1 小时内 5 条因跨度落选；hypothetical 排除）、幂等。
"""

import json
from datetime import datetime, timedelta

from app.core import timeutil
from app.core.db import Memory
from app.services.memory import lifecycle as memory_lifecycle
from app.services.reflection import evidence

USER = "u-ev"
CHARACTER = "asuna"


class StubTrace:
    def __init__(self):
        self.steps = []

    def record(self, name, duration_ms, status="ok", **extra):
        self.steps.append({"name": name, "status": status, **extra})


def _vector(seed: int, dim: int = 8) -> str:
    return json.dumps([1.0 if i == seed % dim else 0.1 for i in range(dim)])


def _seed_memory(
    session_factory,
    memory_id,
    content,
    *,
    created_at,
    embedding=None,
    salience=0.8,
    source="user_stated",
    source_ref=None,
    visibility="private",
    last_reinforced_at=None,
    type_="user_fact",
):
    now = timeutil.now()
    with session_factory() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=USER,
                character_id=CHARACTER,
                content=content,
                type=type_,
                importance=0.7,
                confidence=0.9,
                source=source,
                status="active",
                salience=salience,
                embedding=embedding,
                source_ref=source_ref,
                visibility=visibility,
                last_reinforced_at=last_reinforced_at,
                created_at=created_at,
                updated_at=now,
            )
        )
        session.commit()


def _seed_fatigue_cluster(session_factory, *, now, hours_spread=True, count=5):
    base = "用户说最近加班很累"
    for i in range(count):
        _seed_memory(
            session_factory,
            f"mem-fat-{i}",
            base if i == 0 else f"{base}（第{i + 1}次提到）",
            created_at=now - timedelta(days=i * 2) if hours_spread else now - timedelta(minutes=10 * i),
            embedding=_vector(3),
            source_ref={"table": "conversation", "id": f"conv:u:s:{i}"},
        )


def test_five_same_topic_memories_cluster_and_pass(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now)
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    passing = [w for w in windows if w.passes_gate]
    assert len(passing) == 1
    window = passing[0]
    assert window.stats.member_count == 5
    assert window.stats.distinct_source_refs == 5
    assert window.stats.span_hours >= 24.0
    assert window.stats.coherence >= 0.5
    assert window.topic_digest.startswith("用户说最近加班很累")


def test_isolated_single_memory_never_passes_gate(db_session_factory):
    now = timeutil.now()
    _seed_memory(
        db_session_factory,
        "mem-solo",
        "用户喜欢单板滑雪",
        created_at=now - timedelta(days=3),
        source_ref={"table": "conversation", "id": "conv:u:solo"},
    )
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    assert all(not w.passes_gate for w in windows)
    assert any(w.stats.member_count == 1 for w in windows)


def test_same_hour_cluster_fails_span_gate(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now, hours_spread=False)
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    assert windows, "应产出簇（成员数/来源达标）"
    assert all(not w.passes_gate for w in windows)
    assert any("span" in w.gate_reasons for w in windows)


def test_hypothetical_and_out_of_window_excluded(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now)
    _seed_memory(
        db_session_factory,
        "mem-hypo",
        "用户说最近加班很累（假设）",
        created_at=now - timedelta(days=1),
        embedding=_vector(3),
        source_ref={"table": "conversation", "id": "conv:u:s:h"},
        visibility="hypothetical",
    )
    _seed_memory(
        db_session_factory,
        "mem-old",
        "用户说最近加班很累（旧事）",
        created_at=now - timedelta(days=60),
        embedding=_vector(3),
        source_ref={"table": "conversation", "id": "conv:u:s:old"},
    )
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    member_ids = {m.memory_id for w in windows for m in w.members}
    assert "mem-hypo" not in member_ids
    assert "mem-old" not in member_ids
    assert all(w.stats.member_count == 5 for w in windows if w.stats.member_count > 1)


def test_embedding_null_degrades_to_keyword_path(db_session_factory):
    now = timeutil.now()
    base = "用户喜欢在周末爬山"
    for i in range(4):
        _seed_memory(
            db_session_factory,
            f"mem-kw-{i}",
            base if i == 0 else f"{base}，天气好的时候",
            created_at=now - timedelta(days=i * 3),
            embedding=None,
            source_ref={"table": "conversation", "id": f"conv:u:s:kw{i}"},
        )
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    passing = [w for w in windows if w.passes_gate]
    assert len(passing) == 1
    assert passing[0].stats.member_count == 4
    assert passing[0].degraded == "keyword_only"


def test_mixed_pools_form_separate_clusters(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now)
    _seed_memory(
        db_session_factory,
        "mem-cat",
        "用户养了一只叫小雪的猫",
        created_at=now - timedelta(days=1),
        embedding=_vector(5),
        source_ref={"table": "conversation", "id": "conv:u:s:cat"},
    )
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    passing = [w for w in windows if w.passes_gate]
    assert len(passing) == 1
    assert all(m.memory_id.startswith("mem-fat") for m in passing[0].members)


def test_reinforced_stale_memory_enters_window(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now)
    _seed_memory(
        db_session_factory,
        "mem-stale-fresh",
        "用户说最近加班很累（久远但刚被强化）",
        created_at=now - timedelta(days=90),
        last_reinforced_at=now - timedelta(hours=2),
        embedding=_vector(3),
        source_ref={"table": "conversation", "id": "conv:u:s:stale"},
    )
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    passing = [w for w in windows if w.passes_gate]
    assert len(passing) == 1
    assert passing[0].stats.member_count == 6


def test_aggregate_is_idempotent(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now)
    first = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    second = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    assert _serialize(first) == _serialize(second)


def _serialize(windows):
    return [
        {
            "topic": w.topic_digest,
            "members": [
                (m.memory_id, m.weight, m.source_ref, m.semantic_sim, m.topic_sim)
                for m in w.members
            ],
            "stats": vars(w.stats),
            "gate_reasons": w.gate_reasons,
        }
        for w in windows
    ]


def test_aggregate_error_returns_empty_with_trace(db_session_factory, monkeypatch):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now)

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(evidence.memory_repository, "list_active", _boom)
    trace = StubTrace()
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now, trace=trace)
    assert windows == []
    assert trace.steps[0]["name"] == "reflection_evidence"
    assert trace.steps[0]["status"] == "error"


def test_trace_records_pool_clusters_and_gate(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now)
    trace = StubTrace()
    evidence.aggregate_evidence_windows(USER, CHARACTER, now=now, trace=trace)
    # v25 去门控（批次 6）：计划证据通道恒扩源，trace 追加第二步（本用例无计划数据，零窗）。
    assert len(trace.steps) == 2
    step = trace.steps[0]
    assert step["name"] == "reflection_evidence"
    assert step["pool_size"] == 5
    assert step["clusters"] == 1
    assert step["windows"][0]["passes_gate"] is True
    assert step["windows"][0]["member_ids"] == [
        f"mem-fat-{i}" for i in range(5)
    ]
    assert trace.steps[1]["name"] == "reflection_plan_evidence"
    assert trace.steps[1]["windows"] == []


def test_passes_gate_three_gates_independent():
    from app.core.settings import get_settings
    from app.models.reflection import EvidenceMember, EvidenceWindow, WindowStats

    settings = get_settings()
    now = timeutil.now()

    def _window(**stats):
        return EvidenceWindow(
            topic_digest="t",
            members=[],
            stats=WindowStats(
                member_count=stats.get("member_count", 5),
                span_hours=stats.get("span_hours", 72.0),
                distinct_source_refs=stats.get("distinct_source_refs", 5),
                coherence=stats.get("coherence", 0.8),
            ),
        )

    passed, reasons = evidence.passes_gate(_window(), settings)
    assert passed and reasons == []

    passed, reasons = evidence.passes_gate(_window(distinct_source_refs=2), settings)
    assert not passed and reasons == ["evidence_count"]

    passed, reasons = evidence.passes_gate(_window(span_hours=2.0), settings)
    assert not passed and reasons == ["span"]

    passed, reasons = evidence.passes_gate(_window(coherence=0.4), settings)
    assert not passed and reasons == ["coherence"]

    passed, reasons = evidence.passes_gate(_window(distinct_source_refs=1, span_hours=0.5), settings)
    assert not passed and set(reasons) == {"evidence_count", "span"}


def test_member_weight_recency_half_life(db_session_factory):
    now = timeutil.now()
    fresh = evidence._member_weight(0.8, now - timedelta(days=1), now)
    stale = evidence._member_weight(0.8, now - timedelta(days=30), now)
    assert fresh > stale
    assert evidence._member_weight(None, now, now) > 0


def test_reinforce_signal_source_type_mix_recorded(db_session_factory):
    now = timeutil.now()
    _seed_fatigue_cluster(db_session_factory, now=now, count=2)
    _seed_memory(
        db_session_factory,
        "mem-ai",
        "用户说最近加班很累（推断补充）",
        created_at=now - timedelta(days=4),
        embedding=_vector(3),
        source="ai_inferred",
        source_ref={"table": "conversation", "id": "conv:u:s:ai"},
    )
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    assert windows[0].stats.source_type_mix == {"user_stated": 2, "ai_inferred": 1}


def test_malformed_vector_falls_back_to_keyword_path(db_session_factory):
    """单条向量解析失败（坏 JSON）→ 该行语义路缺席，关键词路照常聚类。"""
    now = timeutil.now()
    base = "用户说最近加班很累"
    for i in range(4):
        _seed_memory(
            db_session_factory,
            f"mem-bad-{i}",
            base if i == 0 else f"{base}（第{i + 1}次提到）",
            created_at=now - timedelta(days=i * 2),
            embedding="not-json{" if i == 0 else _vector(3),
            source_ref={"table": "conversation", "id": f"conv:u:s:bad{i}"},
        )
    windows = evidence.aggregate_evidence_windows(USER, CHARACTER, now=now)
    passing = [w for w in windows if w.passes_gate]
    assert len(passing) == 1
    assert passing[0].stats.member_count == 4
    assert passing[0].members[0].semantic_sim == 0.0
    assert passing[0].members[0].topic_sim > 0.0
