import pytest

from app.models.memory import MemoryCandidate
from app.services import memory_policy
from app.services.memory_policy import (
    DECISION_DISCARD,
    DECISION_PRIVACY,
    DECISION_SAVE,
    apply_policy,
)


def make_candidate(**overrides):
    payload = {
        "action": "save",
        "type": "user_preference",
        "content": "用户不喝咖啡",
        "importance": 0.8,
        "confidence": 0.95,
        "source": "user_stated",
    }
    payload.update(overrides)
    return MemoryCandidate(**payload)


def rule_of(report, index=0):
    return report.outcomes[index].rule


def decision_of(report, index=0):
    return report.outcomes[index].decision


class TestR1AiInferred:
    def test_ai_inferred_discarded_even_with_high_importance(self):
        report = apply_policy([make_candidate(source="ai_inferred", importance=0.95)])
        assert decision_of(report) == DECISION_DISCARD
        assert rule_of(report) == "R1"

    def test_user_stated_passes(self):
        report = apply_policy([make_candidate()])
        assert decision_of(report) == DECISION_SAVE


class TestR2Suppress:
    def test_suppress_blocks_whole_round(self):
        candidates = [
            make_candidate(content="用户在深圳工作", type="user_fact"),
            make_candidate(
                action="suppress", type="user_fact", content="用户的收入信息"
            ),
        ]
        report = apply_policy(candidates)
        assert report.saved == []
        assert report.has_suppress()
        assert all(o.decision == DECISION_DISCARD for o in report.discarded)

    def test_round_without_suppress_unaffected(self):
        report = apply_policy([make_candidate()])
        assert not report.has_suppress()
        assert len(report.saved) == 1


class TestR3Forget:
    def test_forget_routed_to_privacy(self):
        report = apply_policy(
            [make_candidate(action="forget", content="用户喜欢咖啡")]
        )
        assert decision_of(report) == DECISION_PRIVACY
        assert rule_of(report) == "R3"
        assert len(report.privacy_items) == 1

    def test_forget_not_saved(self):
        report = apply_policy(
            [make_candidate(action="forget", content="用户喜欢咖啡")]
        )
        assert report.saved == []


class TestR4OneOff:
    def test_one_off_content_discarded(self):
        report = apply_policy([make_candidate(content="今天吃了拉面")])
        assert rule_of(report) == "R4"

    def test_stable_content_passes(self):
        report = apply_policy([make_candidate(content="用户喜欢吃拉面")])
        assert decision_of(report) == DECISION_SAVE


class TestR5Confidence:
    def test_low_confidence_discarded(self):
        report = apply_policy([make_candidate(confidence=0.4)])
        assert rule_of(report) == "R5"

    def test_high_confidence_passes(self):
        report = apply_policy([make_candidate(confidence=0.9)])
        assert decision_of(report) == DECISION_SAVE


class TestR6Importance:
    def test_low_importance_discarded(self):
        report = apply_policy([make_candidate(importance=0.3)])
        assert rule_of(report) == "R6"

    def test_high_importance_passes(self):
        report = apply_policy([make_candidate(importance=0.8)])
        assert decision_of(report) == DECISION_SAVE


class TestR7Duplicate:
    def test_exact_duplicate_discarded(self):
        report = apply_policy(
            [make_candidate(content="用户不喝咖啡")],
            active_contents=["用户不喝咖啡", "用户在深圳工作"],
        )
        assert rule_of(report) == "R7"

    def test_non_duplicate_passes(self):
        report = apply_policy(
            [make_candidate(content="用户喜欢喝茶")],
            active_contents=["用户不喝咖啡"],
        )
        assert decision_of(report) == DECISION_SAVE

    def test_invalidate_skips_duplicate_check(self):
        report = apply_policy(
            [
                make_candidate(
                    action="invalidate",
                    content="用户喜欢咖啡",
                    target_memory_id="m-old",
                )
            ],
            active_contents=["用户喜欢咖啡"],
        )
        assert decision_of(report) == DECISION_SAVE


class TestR8UnresolvedReference:
    def test_pronoun_discarded(self):
        report = apply_policy([make_candidate(content="用户喜欢它")])
        assert rule_of(report) == "R8"

    def test_decontextualized_content_passes(self):
        report = apply_policy([make_candidate(content="用户喜欢猫")])
        assert decision_of(report) == DECISION_SAVE


class TestOrderAndMisc:
    def test_r1_beats_later_rules(self):
        report = apply_policy(
            [
                make_candidate(
                    source="ai_inferred",
                    content="今天吃了拉面",
                    confidence=0.3,
                    importance=0.3,
                )
            ]
        )
        assert rule_of(report) == "R1"

    def test_action_none_discarded(self):
        report = apply_policy(
            [MemoryCandidate(type="user_fact", importance=0.9, confidence=0.9)]
        )
        assert decision_of(report) == DECISION_DISCARD
        assert rule_of(report) == "none"

    def test_empty_candidates(self):
        report = apply_policy([])
        assert report.saved == []
        assert report.privacy_items == []

    def test_report_buckets(self):
        report = apply_policy(
            [
                make_candidate(),
                make_candidate(content="今天很开心", type="user_fact"),
                make_candidate(action="forget", content="用户喜欢咖啡"),
            ]
        )
        assert len(report.saved) == 1
        assert len(report.privacy_items) == 1
        assert len(report.discarded) == 1

    def test_policy_uses_settings_thresholds(self, monkeypatch):
        class StrictSettings:
            memory_min_confidence = 0.9
            memory_importance_threshold = 0.9

        monkeypatch.setattr(
            memory_policy, "get_settings", lambda: StrictSettings()
        )
        report = apply_policy([make_candidate(confidence=0.8, importance=0.8)])
        assert rule_of(report) in ("R5", "R6")
