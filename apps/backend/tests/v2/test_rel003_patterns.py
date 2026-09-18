"""REL-003 Relationship Patterns 接入测试。

覆盖：消费侧 scope 过滤与落选原因、strength 门槛、封顶、双闸 Flag 矩阵、
PolicySnapshot 参考注入（R 规则行为不变）、Context 段渲染与端到端装配。
"""

from datetime import datetime

import pytest

from app.core.db import InsightRow
from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.development import RelationshipPattern
from app.prompts.builder import PromptBuilder
from app.services import relationship_patterns
from app.services.autonomy_policy import PolicySnapshot, effective_interval_minutes
from app.services.development import aggregate

NOW = datetime(2026, 9, 6, 12, 0, 0)
USER = "u-rel3"


@pytest.fixture
def rel_flags(monkeypatch):
    """v2 开关已删除，关系模式通路转常开；保留空夹具以兼容既有调用点。"""
    yield


def _seed_insight(
    insight_id,
    scope="relationship",
    statement="他更愿意在深夜向我倾诉",
    user_id=USER,
):
    with relationship_patterns.SessionLocal() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                statement=statement,
                type="pattern",
                confidence=0.9,
                scope=scope,
                status="active",
                run_id=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def _seed_pattern(key, strength, insight_id, user_id=USER, kind="pattern"):
    aggregate.upsert_modulation(
        user_id=user_id,
        kind=kind,
        key=key,
        value={"tier_delta": 0.4},
        strength=strength,
        source_insight_id=insight_id,
        now=NOW,
    )


class TestReadRelationshipPatterns:
    def test_relationship_scope_pattern_selected(self, _offline_repos, rel_flags):
        _seed_insight("ins-rel")
        _seed_pattern("goal.user_care.weight", 0.8, "ins-rel")
        patterns, payload = relationship_patterns.read_relationship_patterns(USER)
        assert len(patterns) == 1
        assert patterns[0].key == "goal.user_care.weight"
        assert patterns[0].statement == "他更愿意在深夜向我倾诉"
        assert patterns[0].source_insight_id == "ins-rel"
        assert payload["reasons"] == {}

    def test_user_scope_excluded(self, _offline_repos, rel_flags):
        _seed_insight("ins-user", scope="user")
        _seed_pattern("goal.user_care.weight", 0.8, "ins-user")
        patterns, payload = relationship_patterns.read_relationship_patterns(USER)
        assert patterns == []
        assert payload["reasons"]["goal.user_care.weight"] == "scope_excluded"

    def test_strength_threshold(self, _offline_repos, rel_flags):
        _seed_insight("ins-low")
        _seed_pattern("goal.user_care.weight", 0.5, "ins-low")
        patterns, payload = relationship_patterns.read_relationship_patterns(USER)
        assert patterns == []
        assert payload["reasons"]["goal.user_care.weight"] == "below_threshold"

    def test_missing_insight_skipped(self, _offline_repos, rel_flags):
        _seed_pattern("goal.user_care.weight", 0.8, "ins-gone")
        patterns, payload = relationship_patterns.read_relationship_patterns(USER)
        assert patterns == []
        assert payload["reasons"]["goal.user_care.weight"] == "insight_missing"

    def test_max_items_top_strength(self, _offline_repos, rel_flags):
        for index, strength in enumerate((0.7, 0.9, 0.8)):
            _seed_insight(f"ins-{index}")
            _seed_pattern(f"goal.care.{index}", strength, f"ins-{index}")
        patterns, payload = relationship_patterns.read_relationship_patterns(USER)
        assert [pattern.key for pattern in patterns] == ["goal.care.1", "goal.care.2"]
        assert payload["reasons"]["goal.care.0"] == "over_limit"

    def test_non_pattern_kind_ignored(self, _offline_repos, rel_flags):
        _seed_insight("ins-pref")
        _seed_pattern("response_style.tone", 0.9, "ins-pref", kind="preference")
        patterns, _ = relationship_patterns.read_relationship_patterns(USER)
        assert patterns == []


class TestAutonomyReference:
    def test_snapshot_default_empty(self):
        assert PolicySnapshot().relationship_patterns == ()

    def test_interval_invariant_to_patterns(self):
        from types import SimpleNamespace

        config = SimpleNamespace(
            autonomy_min_interval_minutes=120,
            autonomy_backoff_multiplier=1.5,
            autonomy_min_interval_floor_minutes=30,
        )
        base = PolicySnapshot(intimacy=0.6, selected_goal_type="relationship")
        with_patterns = PolicySnapshot(
            intimacy=0.6,
            selected_goal_type="relationship",
            relationship_patterns=("goal.user_care.weight",),
        )
        assert (
            effective_interval_minutes(base, config)
            == effective_interval_minutes(with_patterns, config)
        )


class TestRenderAndAssembly:
    def _pattern(self, statement="他更愿意在深夜向我倾诉"):
        return RelationshipPattern(
            key="goal.user_care.weight",
            value={},
            strength=0.8,
            statement=statement,
            source_insight_id="ins-rel",
        )

    def test_render_section(self):
        state = ConversationState(
            session_id="s",
            user_id="u",
            messages=[],
            summary=None,
            memories=[],
            current_input="",
            relationship_patterns=[self._pattern()],
        )
        section = PromptBuilder.build_relationship_pattern_section(state)
        assert section is not None
        assert section.startswith("【关系模式】")
        assert "他更愿意在深夜向我倾诉" in section

    def test_render_statement_truncated(self):
        state = ConversationState(
            session_id="s",
            user_id="u",
            messages=[],
            summary=None,
            memories=[],
            current_input="",
            relationship_patterns=[self._pattern(statement="长" * 100)],
        )
        section = PromptBuilder.build_relationship_pattern_section(state)
        assert "…" in section

    def test_render_empty_is_none(self):
        state = ConversationState(
            session_id="s",
            user_id="u",
            messages=[],
            summary=None,
            memories=[],
            current_input="",
        )
        assert PromptBuilder.build_relationship_pattern_section(state) is None

    def test_end_to_end_wiring(self, _offline_repos, rel_flags, monkeypatch):
        _seed_insight("ins-rel")
        _seed_pattern("goal.user_care.weight", 0.8, "ins-rel")
        from app.services import context_builder

        monkeypatch.setattr(
            context_builder, "_load_shared_experiences", lambda *a, **k: ([], {})
        )
        import asyncio

        state = asyncio.run(
            context_builder.build(
                session_id="s-rel3",
                user_id=USER,
                current_input="最近睡得还好吗",
            )
        )
        assert len(state.relationship_patterns) == 1
        assert state.relationship_patterns[0].source_insight_id == "ins-rel"
