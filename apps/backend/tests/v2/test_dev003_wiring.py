"""DEV-003：行为接线。

read_overlay 组装（Flag OFF/空数据/各行解析/非法候选丢弃）、叠加层 v1 字节级
等价（overlay=None 逐字段一致）、habit 候选合入（domain 过滤/去重/上限）、
goal 权重调制（排序翻转/封顶/None 等价）、answer 长度偏移（clamp 下限）、
prompt 渲染（development 段仅非空出现）、development_apply trace。
"""

from datetime import datetime

import pytest

from app.core import timeutil
from app.chains.answer_chain import answer_max_tokens
from app.core.db import DevelopmentStateRow
from app.models.behavior_strategy import BehaviorDirective
from app.models.conversation import ConversationState
from app.models.development import DevelopmentOverlay, DevelopmentStyleParams
from app.engines import behavior as behavior_engine
from app.services.goal import service as goal_service
from app.services.development import aggregate

pytestmark = pytest.mark.xdist_group("development")

USER = "u-wire"


class StubTrace:
    def __init__(self):
        self.steps = []

    def record(self, name, duration_ms, status="ok", **extra):
        self.steps.append({"name": name, "status": status, **extra})


def _seed_modulation(
    session_factory, key, value, *, strength=0.8, insight_id="ins-w1", kind="preference"
):
    now = timeutil.now()
    with session_factory() as session:
        session.add(
            DevelopmentStateRow(
                id=f"dev-{key}-{insight_id}",
                user_id=USER,
                character_id="asuna",
                kind=kind,
                key=key,
                value=value,
                strength=strength,
                source_insight_id=insight_id,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_read_overlay_empty_data_returns_none(db_session_factory, override_settings):
    override_settings()
    assert aggregate.read_overlay(USER) is None


def test_read_overlay_composes_all_rows(db_session_factory, override_settings):
    override_settings()
    _seed_modulation(
        db_session_factory, "response_style.length", {"max_tokens_delta": -150}
    )
    _seed_modulation(
        db_session_factory,
        "response_style.tone",
        {"tone_hint": "更简练、直给，不绕弯子"},
        insight_id="ins-w2",
    )
    _seed_modulation(
        db_session_factory,
        "behavior.care_topics",
        {"topics": ["工作压力"], "care_hint": "最近特别在意他的工作压力"},
        insight_id="ins-w3",
        kind="belief",
    )
    _seed_modulation(
        db_session_factory,
        "behavior.habit_candidates",
        {
            "candidates": [
                {
                    "id": "dev_habit_late_care",
                    "domain": "relate",
                    "priority": 3,
                    "instruction": "深夜时段主动问一句他的休息状况",
                }
            ]
        },
        insight_id="ins-w4",
        kind="belief",
    )
    _seed_modulation(
        db_session_factory,
        "goal.user_care.weight",
        {"tier_delta": 0.35},
        insight_id="ins-w5",
        kind="pattern",
    )
    overlay = aggregate.read_overlay(USER)
    assert overlay is not None
    assert overlay.style.max_tokens_delta == -150
    assert overlay.style.tone_hint == "更简练、直给，不绕弯子"
    assert overlay.care_hint == "最近特别在意他的工作压力"
    assert overlay.habit_candidates[0]["id"] == "dev_habit_late_care"
    assert overlay.goal_weights == {"user_care": 0.35}
    assert len(overlay.modulation_summary) <= 100
    assert overlay.sources["response_style.length"] == "ins-w1"
    assert overlay.sources["goal.user_care.weight"] == "ins-w5"


def test_read_overlay_drops_duplicate_and_invalid_candidates(
    db_session_factory, override_settings
):
    override_settings()
    _seed_modulation(
        db_session_factory,
        "behavior.habit_candidates",
        {
            "candidates": [
                {"id": "dev_habit_a", "domain": "relate", "priority": 3, "instruction": "a"},
                {"id": "dev_habit_a", "domain": "relate", "priority": 3, "instruction": "a"},
                {"bad": "shape"},
            ]
        },
        insight_id="ins-w9",
        kind="belief",
    )
    overlay = aggregate.read_overlay(USER)
    assert overlay is not None
    assert [item["id"] for item in overlay.habit_candidates] == ["dev_habit_a"]


def _directive(session_factory, overlay=None, intention="comfort_user") -> BehaviorDirective:
    from app.models.character_state import CharacterState
    from app.models.intention import IntentionDecision
    from app.models.relationship import RelationshipState

    class _State:
        relationship_state = RelationshipState()
        character_state = CharacterState()

    intention_decision = IntentionDecision(intention=intention, confidence=0.9)
    return behavior_engine.resolve(
        intention_decision, _State(), None, "default", development_overlay=overlay
    )


def test_resolve_without_overlay_matches_v1_directive(db_session_factory):
    baseline = _directive(db_session_factory)
    explicit = _directive(db_session_factory, overlay=None)
    assert baseline.model_dump() == explicit.model_dump()
    assert baseline.development_style is None
    assert baseline.development_care_hint == ""


def test_resolve_applies_overlay_to_directive(db_session_factory, override_settings):
    override_settings()
    overlay = DevelopmentOverlay(
        style=DevelopmentStyleParams(tone_hint="更简练、直给"),
        care_hint="最近特别在意他的休息",
        habit_candidates=[
            {
                "id": "dev_habit_late_care",
                "domain": "relate",
                "priority": 1,
                "instruction": "深夜时段主动问一句他的休息状况",
            }
        ],
    )
    directive = _directive(db_session_factory, overlay)
    assert directive.development_care_hint == "最近特别在意他的休息"
    assert directive.development_style.tone_hint == "更简练、直给"
    assert "dev_habit_late_care" in [habit.id for habit in directive.habits]


def test_goal_weights_flip_selection(db_session_factory):
    from app.models.goal import GoalRecord

    now = timeutil.now()
    companion = GoalRecord(
        user_id=USER,
        type="user_care",
        description="陪伴用户放松",
        priority=3,
        horizon="current",
        source="policy",
        created_turn=1,
        created_at=now,
        updated_at=now,
    )
    repair = GoalRecord(
        user_id=USER,
        type="relationship",
        description="修复与用户的隔阂",
        priority=3,
        horizon="current",
        source="policy",
        created_turn=1,
        created_at=now,
        updated_at=now,
    )
    signals = dict(
        tension=0.9,
        user_emotion="sad",
        character_mood="sad",
        character_intensity=0.8,
        scene_pending=False,
        late_night=False,
    )
    baseline = goal_service.select([repair, companion], **signals)
    modulated = goal_service.select(
        [repair, companion], **signals, development_weights={"relationship": 0.45}
    )
    assert baseline.goal.type == "user_care"
    assert modulated.goal.type == "relationship"
    assert "development 调制生效" in modulated.reason
    plain = goal_service.select([repair, companion], **signals, development_weights=None)
    assert plain.goal.type == baseline.goal.type


def test_answer_max_tokens_overlay_and_clamp(override_settings):
    override_settings(answer_max_tokens=800, development_answer_min_tokens=300)
    base_state = _conversation_state(overlay=None)
    assert answer_max_tokens(base_state) == 800
    lowered = _conversation_state(
        overlay=DevelopmentOverlay(style=DevelopmentStyleParams(max_tokens_delta=-200))
    )
    assert answer_max_tokens(lowered) == 600
    clamped = _conversation_state(
        overlay=DevelopmentOverlay(style=DevelopmentStyleParams(max_tokens_delta=-900))
    )
    assert answer_max_tokens(clamped) == 300


def _conversation_state(overlay) -> ConversationState:
    return ConversationState(
        session_id="s",
        user_id=USER,
        messages=[],
        summary=None,
        memories=[],
        current_input="hi",
        development_overlay=overlay,
    )


def test_behavior_section_renders_development_lines():
    directive = BehaviorDirective(
        strategy=_strategy(),
        budget=behavior_engine.ActionBudget(max_action_desc=1),
        habits=[],
        development_style=DevelopmentStyleParams(tone_hint="更简练、直给"),
        development_care_hint="最近特别在意他的休息",
    )
    from app.prompts.behavior import build_behavior_section

    section = build_behavior_section(directive)
    assert "风格调整：更简练、直给" in section
    assert "此刻的在意：最近特别在意他的休息" in section
    plain = build_behavior_section(
        directive.model_copy(
            update={"development_style": None, "development_care_hint": ""}
        )
    )
    assert "风格调整" not in plain
    assert "此刻的在意" not in plain


def _strategy():
    from app.models.behavior_strategy import BehaviorStrategy

    return BehaviorStrategy(
        strategy="direct_support", base_strategy="direct_support"
    )


def test_development_apply_trace_payload(override_settings):
    override_settings(answer_max_tokens=800, development_answer_min_tokens=300)
    trace = StubTrace()
    overlay = DevelopmentOverlay(
        style=DevelopmentStyleParams(max_tokens_delta=-200, tone_hint="更简练"),
        care_hint="在意他的休息",
        goal_weights={"user_care": 0.35},
        sources={"response_style.length": "ins-1", "goal.user_care.weight": "ins-2"},
    )
    from app.application.chat_pipeline import _record_development_apply

    _record_development_apply(
        trace, _conversation_state(overlay), _directive(None, overlay)
    )
    step = trace.steps[-1]
    assert step["name"] == "development_apply"
    assert step["applied"]["response_style.length"]["before"] > step["applied"][
        "response_style.length"
    ]["after"]
    assert step["applied"]["goal.user_care.weight"]["after"] == {"user_care": 0.35}
    assert step["sources"]["response_style.length"] == "ins-1"


def test_development_apply_trace_skipped_without_overlay():
    trace = StubTrace()
    from app.application.chat_pipeline import _record_development_apply

    _record_development_apply(trace, _conversation_state(None), _directive(None))
    assert all(step["name"] != "development_apply" for step in trace.steps)
