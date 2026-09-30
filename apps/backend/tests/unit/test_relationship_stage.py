import pytest

from app.engines.state import next_stage


class TestUpgradeThresholds:
    def test_friend_requires_familiarity(self):
        assert next_stage(0.1, 0.1, 0.36, "stranger") == "friend"

    def test_below_threshold_stays(self):
        assert next_stage(0.1, 0.1, 0.30, "stranger") == "stranger"

    def test_close_friend_requires_intimacy_and_trust(self):
        assert next_stage(0.56, 0.56, 0.40, "friend") == "close_friend"

    def test_partner_requires_higher_thresholds(self):
        assert next_stage(0.76, 0.76, 0.40, "close_friend") == "partner"

    def test_upgrade_only_one_level_per_turn(self):
        assert next_stage(0.90, 0.90, 0.90, "stranger") == "friend"


class TestDowngradeHysteresis:
    def test_stays_within_hysteresis_band(self):
        assert next_stage(0.50, 0.50, 0.40, "close_friend") == "close_friend"

    def test_downgrades_after_falling_below_threshold_minus_hysteresis(self):
        assert next_stage(0.40, 0.40, 0.40, "close_friend") == "friend"

    def test_partial_fall_keeps_stage(self):
        assert next_stage(0.40, 0.56, 0.40, "close_friend") == "close_friend"


class TestTensionFreeze:
    def test_freeze_blocks_upgrade(self):
        assert (
            next_stage(0.60, 0.60, 0.40, "friend", tension=0.55) == "friend"
        )

    def test_freeze_at_boundary_blocks(self):
        assert (
            next_stage(0.60, 0.60, 0.40, "friend", tension=0.51) == "friend"
        )

    def test_below_freeze_allows_upgrade(self):
        assert (
            next_stage(0.60, 0.60, 0.40, "friend", tension=0.49) == "close_friend"
        )

    def test_freeze_does_not_block_downgrade(self):
        assert (
            next_stage(0.20, 0.20, 0.20, "friend", tension=0.60) == "stranger"
        )

    def test_v2_path_without_tension_unaffected(self):
        assert next_stage(0.60, 0.60, 0.40, "friend") == "close_friend"
