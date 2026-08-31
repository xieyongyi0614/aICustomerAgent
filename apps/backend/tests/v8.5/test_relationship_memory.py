"""V8.5 M6 关系记忆套件（memory-integration.md：路由边界/模板确定性/去重）。"""

from datetime import datetime, timedelta

from app.models.relationship import MilestoneRecord, RelationshipDelta, RelationshipEvent
from app.services import relationship_memory as rmem

NOW = datetime(2026, 8, 31, 12, 0, 0)


def _event(type_="praise", magnitude="normal", cause="被夸") -> RelationshipEvent:
    return RelationshipEvent(
        user_id="u1", session_id="s1", type=type_, magnitude=magnitude,
        impact=RelationshipDelta(trust=0.02), confidence=0.8, cause=cause,
        created_at=NOW,
    )


def _milestone(key="first_self_disclosure") -> MilestoneRecord:
    return MilestoneRecord(
        user_id="u1", milestone_key=key, period_key="",
        applied_bonus=RelationshipDelta(), created_at=NOW,
    )


def test_unpromoted_signal_not_memorized():
    assert rmem.to_memory_candidates(None, [], "") == []


def test_strong_disclosure_memorized_weak_not():
    strong = rmem.to_memory_candidates(_event("intimate_moment", "strong"), [], "", NOW)
    assert len(strong) == 1
    assert strong[0].importance == 0.80
    weak = rmem.to_memory_candidates(_event("intimate_moment", "weak"), [], "", NOW)
    assert weak == []


def test_conflict_and_boundary_memorized_negative_included():
    candidates = rmem.to_memory_candidates(_event("conflict", cause="误会"), [], "", NOW)
    assert candidates[0].importance == 0.75
    assert "误会" in candidates[0].content


def test_milestone_memorized_at_090():
    candidates = rmem.to_memory_candidates(None, [_milestone()], "", NOW)
    assert candidates[0].importance == 0.90
    assert candidates[0].type == "relationship_event"


def test_reconciled_memorized_at_085():
    candidates = rmem.to_memory_candidates(None, [], "reconciled", NOW)
    assert candidates[0].importance == 0.85


def test_template_deterministic_and_cause_clipped():
    first = rmem.render_template("first_self_disclosure", "工作压力很大很久了")
    second = rmem.render_template("first_self_disclosure", "工作压力很大很久了")
    assert first == second
    assert "工作压力很大很久了"[:20] in first
    long_cause = "这是一个超过二十个字的敏感隐私信息需要被截断处理"
    rendered = rmem.render_template("conflict", long_cause)
    assert long_cause not in rendered


def test_dedup_within_24h():
    rmem.to_memory_candidates(_event("conflict", cause="误会"), [], "", NOW)
    later = rmem.to_memory_candidates(
        _event("conflict", cause="误会"), [], "", NOW + timedelta(hours=23)
    )
    assert later == []
    far = rmem.to_memory_candidates(
        _event("conflict", cause="误会"), [], "", NOW + timedelta(hours=25)
    )
    assert len(far) == 1


def test_source_untyped_for_v4_compat():
    candidates = rmem.to_memory_candidates(_event("conflict"), [], "", NOW)
    assert candidates[0].source == "ai_inferred"