"""V8.5 relationship_milestones 仓储集成测试（milestone-system.md §3~§4）。"""

from datetime import datetime

import pytest

from app.models.relationship import RelationshipDelta
from app.repositories import relationship_milestone_repository as repo

NOW = datetime(2026, 8, 31, 12, 0, 0)


def test_create_and_list_milestones(db_session_factory):
    record = repo.create_milestone(
        user_id="u1",
        milestone_key="first_self_disclosure",
        title="第一次袒露心事",
        applied_bonus=RelationshipDelta(trust=0.03, intimacy=0.02),
        unlocks=("emotional_support_deep",),
        now=NOW,
    )
    assert record is not None
    assert record.milestone_key == "first_self_disclosure"
    assert record.applied_bonus.trust == pytest.approx(0.03)
    assert record.unlocks == ("emotional_support_deep",)
    listed = repo.list_milestones("u1")
    assert [m.milestone_key for m in listed] == ["first_self_disclosure"]


def test_unique_key_idempotent_return_none(db_session_factory):
    first = repo.create_milestone(
        user_id="u1", milestone_key="first_interaction", title="第一次聊天", now=NOW
    )
    second = repo.create_milestone(
        user_id="u1", milestone_key="first_interaction", title="第一次聊天", now=NOW
    )
    assert first is not None and second is None
    assert len(repo.list_milestones("u1")) == 1


def test_period_key_allows_recurring_milestones(db_session_factory):
    assert (
        repo.create_milestone(
            user_id="u1",
            milestone_key="monthly_anniversary",
            title="认识满一个月",
            period_key="2026-07",
            now=NOW,
        )
        is not None
    )
    assert (
        repo.create_milestone(
            user_id="u1",
            milestone_key="monthly_anniversary",
            title="认识满一个月",
            period_key="2026-08",
            now=NOW,
        )
        is not None
    )
    assert (
        repo.create_milestone(
            user_id="u1",
            milestone_key="monthly_anniversary",
            title="认识满一个月",
            period_key="2026-08",
            now=NOW,
        )
        is None
    )


def test_existing_keys_and_has_unlock(db_session_factory):
    repo.create_milestone(
        user_id="u1",
        milestone_key="stage_close_friend",
        title="成为亲密朋友",
        unlocks=("proactive_goodnight", "personal_topics"),
        now=NOW,
    )
    assert repo.existing_keys("u1") == {("stage_close_friend", "")}
    assert repo.existing_keys("u2") == set()
    assert repo.has_unlock("u1", "proactive_goodnight") is True
    assert repo.has_unlock("u1", "deep_commitment_language") is False
    assert repo.has_unlock("u2", "proactive_goodnight") is False


def test_list_unlocks_deduplicated_ordered(db_session_factory):
    repo.create_milestone(
        user_id="u1",
        milestone_key="stage_friend",
        title="成为朋友",
        unlocks=("casual_check_in",),
        now=NOW,
    )
    repo.create_milestone(
        user_id="u1",
        milestone_key="stage_close_friend",
        title="成为亲密朋友",
        unlocks=("proactive_goodnight", "casual_check_in"),
        now=NOW,
    )
    unlocks = repo.list_unlocks("u1")
    assert unlocks == ("casual_check_in", "proactive_goodnight")