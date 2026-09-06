"""REL-004 叙事里程碑与关系评估测试。

覆盖：白名单匹配/频控/幂等、零 bonus 证明、Insight 非资格跳过、
narrative 切片与两条审计规则、IssueCode 收口、重放对账工具。
"""

from datetime import datetime

import pytest

from app.core.db import InsightRow, RelationshipMilestoneRow
from app.core.settings import get_settings
from app.models.evaluation import IssueCode
from app.models.relationship import RelationshipDelta, RelationshipEvent
from app.repositories import (
    relationship_event_repository,
    relationship_milestone_repository,
    relationship_repository,
    relationship_snapshot_repository,
)
from app.services import (
    relationship_audit,
    relationship_narrative,
)
from app.services.evaluation_context import (
    EvaluationContext,
    NarrativeFactRef,
    NarrativeMilestoneRef,
    NarrativeSlice,
)
from app.services.evaluation_rules.relationship import (
    NarrativeFactProvenanceRule,
    NarrativeMilestoneProvenanceRule,
)
from app.services.memory2.ingest import NARRATIVE_MILESTONE_PREFIX

NOW = datetime(2026, 9, 6, 12, 0, 0)


@pytest.fixture
def rel_flag(monkeypatch):
    monkeypatch.setattr(get_settings(), "v2_relationship_evolved_enabled", True)


def _seed_insight(
    insight_id,
    user_id,
    statement,
    scope="relationship",
    status="active",
):
    with relationship_narrative.SessionLocal() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                statement=statement,
                type="pattern",
                confidence=0.9,
                scope=scope,
                status=status,
                run_id=None,
                created_at=NOW,
                updated_at=NOW,
                invalidated_reason=(
                    "user_clarification:test" if status == "invalidated" else None
                ),
            )
        )
        session.commit()


class TestNarrativeMilestone:
    def test_whitelist_match_creates_milestone(self, _offline_repos, rel_flag):
        _seed_insight("ins-1", "u-rel4", "我们熬夜一起赶工了一个通宵")
        assert relationship_narrative.process_insight("ins-1") is True
        milestones = relationship_milestone_repository.list_milestones("u-rel4")
        assert len(milestones) == 1
        record = milestones[0]
        assert record.milestone_key == "narrative:all_nighter"
        assert record.title == "第一次一起熬夜赶工"
        assert record.period_key == ""
        assert record.meta["source"] == "insight"
        assert record.meta["insight_id"] == "ins-1"
        assert record.applied_bonus == RelationshipDelta()

    def test_zero_bonus_state_untouched(self, _offline_repos, rel_flag):
        _seed_insight("ins-1", "u-rel4", "我们熬夜一起赶工了一个通宵")
        before = relationship_repository.get_relationship("u-rel4")
        relationship_narrative.process_insight("ins-1")
        after = relationship_repository.get_relationship("u-rel4")
        assert before.intimacy == after.intimacy
        assert before.trust == after.trust
        assert before.stage == after.stage

    def test_idempotent_same_insight_once(self, _offline_repos, rel_flag):
        _seed_insight("ins-1", "u-rel4", "我们熬夜一起赶工了一个通宵")
        assert relationship_narrative.process_insight("ins-1") is True
        assert relationship_narrative.process_insight("ins-1") is False
        assert len(relationship_milestone_repository.list_milestones("u-rel4")) == 1

    def test_whitelist_miss_no_milestone(self, _offline_repos, rel_flag):
        _seed_insight("ins-2", "u-rel4", "用户喜欢深夜工作")
        assert relationship_narrative.process_insight("ins-2") is False
        assert relationship_milestone_repository.list_milestones("u-rel4") == []

    def test_inactive_insight_skipped(self, _offline_repos, rel_flag):
        _seed_insight(
            "ins-3",
            "u-rel4",
            "我们熬夜一起赶工",
            status="invalidated",
        )
        assert relationship_narrative.process_insight("ins-3") is False

    def test_low_confidence_skipped(self, _offline_repos, rel_flag, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "v2_relationship_narrative_min_confidence", 0.75
        )
        with relationship_narrative.SessionLocal() as session:
            session.add(
                InsightRow(
                    id="ins-low",
                    user_id="u-rel4",
                    statement="我们熬夜一起赶工",
                    type="pattern",
                    confidence=0.6,
                    scope="relationship",
                    status="active",
                    run_id=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.commit()
        assert relationship_narrative.process_insight("ins-low") is False

    def test_daily_cap(self, _offline_repos, rel_flag, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "v2_relationship_narrative_whitelist_json",
            '{"narrative:all_nighter": {"title": "熬夜", "keywords": ["熬夜"], "all": true},'
            ' "narrative:trip": {"title": "旅行", "keywords": ["旅行"], "all": true}}',
        )
        _seed_insight("ins-a", "u-rel4", "我们熬夜赶工")
        _seed_insight("ins-b", "u-rel4", "我们去旅行了")
        assert relationship_narrative.process_insight("ins-a") is True
        assert relationship_narrative.process_insight("ins-b") is False
        keys = [
            m.milestone_key
            for m in relationship_milestone_repository.list_milestones("u-rel4")
        ]
        assert keys == ["narrative:all_nighter"]

    def test_any_mode_matching(self, _offline_repos, rel_flag, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "v2_relationship_narrative_whitelist_json",
            '{"narrative:any_rule": {"title": "任意", "keywords": ["旅行", "熬夜"],'
            ' "all": false}}',
        )
        _seed_insight("ins-any", "u-rel4", "我们去旅行了")
        assert relationship_narrative.process_insight("ins-any") is True
        keys = [
            m.milestone_key
            for m in relationship_milestone_repository.list_milestones("u-rel4")
        ]
        assert keys == ["narrative:any_rule"]

    def test_on_insight_created_filters_scope_and_confidence(
        self, _offline_repos, rel_flag
    ):
        relationship_narrative.on_insight_created(
            "u-rel4",
            [
                {"insight_id": "ins-user", "scope": "user", "confidence": 0.9},
                {"insight_id": "ins-lowconf", "scope": "relationship", "confidence": 0.5},
                {"insight_id": "ins-ok", "scope": "relationship", "confidence": 0.9},
            ],
        )
        from app.repositories import background_job_repository

        jobs = background_job_repository.list_jobs(
            relationship_narrative.JOB_TYPE_NARRATIVE
        )
        eligible = [
            job
            for job in jobs
            if (job.payload or {}).get("insight_id") == "ins-ok"
            and (job.payload or {}).get("user_id") == "u-rel4"
        ]
        assert len(jobs) == 1 and len(eligible) == 1


def _slice(facts=None, milestones=None, insight_ids=None):
    return NarrativeSlice(
        facts=facts or [],
        narrative_milestones=milestones or [],
        insight_ids=insight_ids or set(),
    )


def _ctx(narrative):
    return EvaluationContext(
        subject="offline_batch",
        subject_id="batch",
        session_id="s",
        user_id="u",
        narrative=narrative,
    )


class TestNarrativeRules:
    def test_rules_skip_when_slice_absent(self):
        assert NarrativeFactProvenanceRule().evaluate(_ctx(None)) is None
        assert NarrativeMilestoneProvenanceRule().evaluate(_ctx(None)) is None

    def test_orphan_fact_detected(self):
        slice_ = _slice(
            facts=[NarrativeFactRef(id="m1", type="relationship_fact", source_ref={})]
        )
        issue = NarrativeFactProvenanceRule().evaluate(_ctx(slice_))
        assert issue is not None
        assert issue.code == IssueCode.RELATIONSHIP_NARRATIVE_ORPHAN

    def test_provenanced_fact_passes(self):
        slice_ = _slice(
            facts=[
                NarrativeFactRef(
                    id="m1",
                    type="relationship_fact",
                    source_ref={"table": "relationship_events", "id": "e1"},
                )
            ]
        )
        assert NarrativeFactProvenanceRule().evaluate(_ctx(slice_)) is None

    def test_milestone_provenance_violations(self, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "v2_relationship_narrative_whitelist_json",
            '{"narrative:all_nighter": {"title": "熬夜", "keywords": ["熬夜"], "all": true}}',
        )
        unprovenanced = _slice(
            milestones=[
                NarrativeMilestoneRef(
                    id="ms1", milestone_key="narrative:all_nighter", meta={}
                )
            ]
        )
        issue = NarrativeMilestoneProvenanceRule().evaluate(_ctx(unprovenanced))
        assert issue is not None and "缺少 insight 溯源" in issue.evidence_quote

        dangling = _slice(
            milestones=[
                NarrativeMilestoneRef(
                    id="ms1",
                    milestone_key="narrative:all_nighter",
                    meta={"source": "insight", "insight_id": "ins-gone"},
                )
            ],
            insight_ids={"ins-real"},
        )
        issue = NarrativeMilestoneProvenanceRule().evaluate(_ctx(dangling))
        assert issue is not None and "悬空" in issue.evidence_quote

        outside = _slice(
            milestones=[
                NarrativeMilestoneRef(
                    id="ms1",
                    milestone_key="narrative:rogue",
                    meta={"source": "insight", "insight_id": "ins-real"},
                )
            ],
            insight_ids={"ins-real"},
        )
        issue = NarrativeMilestoneProvenanceRule().evaluate(_ctx(outside))
        assert issue is not None and "白名单外" in issue.evidence_quote

    def test_numeric_milestones_ignored(self):
        slice_ = _slice(
            milestones=[NarrativeMilestoneRef(id="ms1", milestone_key="first_conflict")]
        )
        assert NarrativeMilestoneProvenanceRule().evaluate(_ctx(slice_)) is None


class TestReplayAudit:
    def test_no_snapshot_returns_none_consistent(self, _offline_repos):
        report = relationship_audit.replay_report("u-no-snap")
        assert report["consistent"] is None

    def test_replay_consistent_with_anchor(self, _offline_repos):
        from app.repositories import (
            relationship_repository,
            relationship_snapshot_repository,
        )

        user = "u-replay"
        state = relationship_repository.get_relationship(user)
        relationship_snapshot_repository.create_snapshot(
            user, state.version, state, trigger="test", now=NOW
        )
        updated = state.model_copy(
            update={"intimacy": state.intimacy + 0.02, "version": state.version + 1}
        )
        relationship_repository.commit_relationship_update(
            user,
            updated,
            [
                RelationshipEvent(
                    user_id=user,
                    session_id="s-1",
                    type="praise",
                    magnitude="normal",
                    impact=RelationshipDelta(intimacy=0.02),
                    confidence=0.9,
                    source="conversation",
                    cause="被夸奖",
                    created_at=NOW.replace(hour=13),
                )
            ],
        )
        report = relationship_audit.replay_report(user)
        assert report["consistent"] is True
        assert report["events_replayed"] == 1
        assert "intimacy" in report["reconciled"]

    def test_milestone_bonus_explained(self, _offline_repos):
        from app.repositories import (
            relationship_repository,
            relationship_snapshot_repository,
        )

        user = "u-replay-bonus"
        state = relationship_repository.get_relationship(user)
        relationship_snapshot_repository.create_snapshot(
            user, state.version, state, trigger="test", now=NOW
        )
        relationship_milestone_repository.create_milestone(
            user_id=user,
            milestone_key="first_self_disclosure",
            title="第一次袒露心事",
            applied_bonus=RelationshipDelta(intimacy=0.05, trust=0.03),
            now=NOW.replace(hour=14),
        )
        updated = state.model_copy(
            update={
                "intimacy": state.intimacy + 0.05,
                "trust": state.trust + 0.03,
                "version": state.version + 1,
            }
        )
        relationship_repository.commit_relationship_update(user, updated, [])
        report = relationship_audit.replay_report(user)
        assert report["consistent"] is True
        assert set(report["explained"]) == {"intimacy", "trust"}


class TestIssueCodeRegistry:
    def test_narrative_codes_registered(self):
        assert IssueCode.RELATIONSHIP_NARRATIVE_ORPHAN.value == (
            "relationship_narrative_orphan"
        )
        assert IssueCode.RELATIONSHIP_MILESTONE_UNPROVENANCED.value == (
            "relationship_milestone_unprovenanced"
        )
