from datetime import datetime, timezone

from app.models.memory import MemoryCandidate, UserMemoryV4
from app.services.memory_conflict import (
    ACTION_DISCARD_PAIR,
    ACTION_INVALIDATE,
    ACTION_NOOP,
    ACTION_SAVE,
    ACTION_SUPERSEDE,
    ACTION_UPDATE,
    resolve_batch,
    resolve_candidate,
    same_topic,
)

NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)


def make_candidate(**overrides):
    payload = {
        "action": "save",
        "type": "user_preference",
        "content": "用户喜欢喝茶",
        "importance": 0.8,
        "confidence": 0.95,
        "source": "user_stated",
    }
    payload.update(overrides)
    return MemoryCandidate(**payload)


def make_memory(id: str, content: str, type: str = "user_preference", **overrides):
    payload = {
        "id": id,
        "user_id": "u1",
        "character_id": "asuna",
        "type": type,
        "content": content,
        "importance": 0.7,
        "confidence": 0.9,
        "source": "user_stated",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return UserMemoryV4(**payload)


class TestSameTopic:
    def test_substring_containment(self):
        assert same_topic("喜欢咖啡", "用户以前喜欢咖啡") is True

    def test_high_overlap_same_topic(self):
        assert same_topic("用户喜欢咖啡", "用户喜欢喝茶") is True

    def test_negation_variant_same_topic(self):
        assert same_topic("用户喜欢咖啡", "用户不喝咖啡") is True

    def test_unrelated_contents_not_same_topic(self):
        assert same_topic("用户在深圳工作", "用户养了一只猫") is False

    def test_threshold_boundary(self):
        assert same_topic("用户喜欢咖啡", "用户喜欢喝茶", threshold=0.99) is False

    def test_empty_content(self):
        assert same_topic("", "用户喜欢咖啡") is False


class TestResolveSave:
    def test_no_match_saves(self):
        outcome = resolve_candidate(
            make_candidate(content="用户养了一只猫", type="user_fact"),
            [make_memory("m1", "用户在深圳工作", type="user_fact")],
        )
        assert outcome.action == ACTION_SAVE
        assert outcome.target_id is None

    def test_different_type_does_not_conflict(self):
        outcome = resolve_candidate(
            make_candidate(content="用户不喝咖啡", type="user_fact"),
            [make_memory("m1", "用户喜欢咖啡")],
        )
        assert outcome.action == ACTION_SAVE


class TestResolveUpdate:
    def test_refine_updates_target(self):
        outcome = resolve_candidate(
            make_candidate(
                content="用户喜欢冰美式咖啡", relation="refine"
            ),
            [make_memory("m1", "用户喜欢咖啡")],
        )
        assert outcome.action == ACTION_UPDATE
        assert outcome.target_id == "m1"

    def test_refine_prefers_best_match(self):
        outcome = resolve_candidate(
            make_candidate(content="用户喜欢冰美式咖啡", relation="refine"),
            [
                make_memory("m1", "用户在深圳工作", type="user_fact"),
                make_memory("m2", "用户喜欢咖啡"),
                make_memory("m3", "用户喜欢速溶咖啡"),
            ],
        )
        assert outcome.action == ACTION_UPDATE
        assert outcome.target_id in ("m2", "m3")


class TestResolveSupersede:
    def test_replace_supersedes(self):
        outcome = resolve_candidate(
            make_candidate(content="用户喜欢喝茶", relation="replace"),
            [make_memory("m1", "用户喜欢咖啡")],
        )
        assert outcome.action == ACTION_SUPERSEDE
        assert outcome.target_id == "m1"

    def test_missing_relation_defaults_to_supersede(self):
        outcome = resolve_candidate(
            make_candidate(content="用户喜欢喝茶"),
            [make_memory("m1", "用户喜欢咖啡")],
        )
        assert outcome.action == ACTION_SUPERSEDE
        assert outcome.target_id == "m1"


class TestResolveInvalidate:
    def test_invalidate_with_explicit_target(self):
        outcome = resolve_candidate(
            make_candidate(
                action="invalidate",
                content="用户喜欢咖啡",
                target_memory_id="m9",
            ),
            [make_memory("m1", "用户喜欢咖啡"), make_memory("m9", "用户喜欢咖啡")],
        )
        assert outcome.action == ACTION_INVALIDATE
        assert outcome.target_id == "m9"

    def test_invalidate_without_target_uses_topic_match(self):
        outcome = resolve_candidate(
            make_candidate(action="invalidate", content="用户喜欢咖啡"),
            [make_memory("m1", "用户喜欢咖啡")],
        )
        assert outcome.action == ACTION_INVALIDATE
        assert outcome.target_id == "m1"

    def test_invalidate_without_any_match_is_noop(self):
        outcome = resolve_candidate(
            make_candidate(action="invalidate", content="用户喜欢咖啡"),
            [make_memory("m1", "用户在深圳工作", type="user_fact")],
        )
        assert outcome.action == ACTION_NOOP
        assert outcome.target_id is None


class TestSameRoundContradiction:
    def test_contradictory_pair_both_discarded(self):
        outcomes = resolve_batch(
            [
                make_candidate(content="用户养了一只猫", type="user_fact"),
                make_candidate(content="用户养了一只狗", type="user_fact"),
            ],
            [],
        )
        actions = [o.action for o in outcomes]
        assert actions.count(ACTION_DISCARD_PAIR) == 2

    def test_unrelated_candidates_both_saved(self):
        outcomes = resolve_batch(
            [
                make_candidate(content="用户在深圳工作", type="user_fact"),
                make_candidate(content="用户喜欢西瓜", type="user_preference"),
            ],
            [],
        )
        assert all(o.action == ACTION_SAVE for o in outcomes)

    def test_invalidate_processed_in_batch(self):
        outcomes = resolve_batch(
            [
                make_candidate(action="invalidate", content="用户喜欢咖啡"),
                make_candidate(content="用户在深圳工作", type="user_fact"),
            ],
            [make_memory("m1", "用户喜欢咖啡")],
        )
        invalidate = [o for o in outcomes if o.action == ACTION_INVALIDATE]
        assert len(invalidate) == 1
        assert invalidate[0].target_id == "m1"
