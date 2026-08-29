from datetime import datetime

from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis
from app.models.goal import GoalRecord
from app.models.intention import ValidatedIntention
from app.models.relationship import RelationshipState
from app.prompts.builder import PromptBuilder
from app.prompts.goal import (
    GOAL_BUDGET_CHARS,
    INTENTION_BUDGET_CHARS,
    GoalContext,
    build_goal_section,
    build_intention_section,
)
from app.services.goal_service import SelectedGoal

NOW = datetime(2026, 8, 29, 12, 0, 0)


def _goal(goal_type="user_care", description="陪伴用户放松", goal_id="g-1") -> GoalRecord:
    return GoalRecord(
        id=goal_id,
        user_id="u1",
        type=goal_type,
        description=description,
        priority=5,
        horizon="current",
        source="policy",
        created_turn=1,
        expires_at_turn=21,
        created_at=NOW,
        updated_at=NOW,
    )


def _selected(
    reason="用户表达疲惫，关怀目标提升",
    suppressed=None,
    suppressed_description=None,
    goal_type="user_care",
    description="陪伴用户放松",
) -> SelectedGoal:
    return SelectedGoal(
        goal=_goal(goal_type, description),
        reason=reason,
        suppressed=suppressed or [],
        suppressed_description=suppressed_description,
    )


def _intention(intention="comfort_user", degraded=False, goal_id="g-1"):
    return ValidatedIntention(
        intention=intention,
        reason="内部解释，不进 Prompt",
        goal_id=goal_id,
        degraded=degraded,
    )


def _state() -> ConversationState:
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="我回来了")],
        summary=None,
        memories=[],
        current_input="今天好累",
        character_state=CharacterState(mood="worried", intensity=0.65),
        relationship_state=RelationshipState(tension=0.2),
    )


def _render(goal_ctx=None):
    prompt = PromptBuilder.build(
        "immersive", _state(), TurnAnalysis(), goal_ctx=goal_ctx
    )
    return [m.content for m in prompt.format_messages()]


class TestGoalSection:
    def test_section_format(self):
        section = build_goal_section(_selected())
        lines = section.split("\n")
        assert lines[0] == "【角色当前目标】"
        assert lines[1] == "主导：陪伴用户放松"
        assert lines[2] == "因为：用户表达疲惫，关怀目标提升"

    def test_section_budget(self):
        long_reason = "因为" * 80
        section = build_goal_section(_selected(reason=long_reason))
        assert len(section.split("\n", 1)[1]) <= GOAL_BUDGET_CHARS

    def test_suppressed_description_becomes_inner_tendency(self):
        section = build_goal_section(
            _selected(
                suppressed=["g-2"],
                suppressed_description="守护用户的身心状态",
            )
        )
        assert "内心倾向：暂时放下“守护用户的身心状态”，先陪伴用户放松" in section

    def test_none_goal_returns_none(self):
        assert build_goal_section(None) is None
        assert build_goal_section(SelectedGoal(goal=None, reason="x")) is None


class TestIntentionSection:
    def test_section_format_with_labels(self):
        section = build_intention_section(_intention())
        assert "【本轮意图】" in section
        assert "安抚用户（安抚用户的情绪）" in section
        assert "表达要求：" in section
        assert "意图叠加在你的人格之上" in section
        assert "不要直接说出意图名称" in section

    def test_internal_reason_not_injected(self):
        section = build_intention_section(_intention())
        assert "内部解释" not in section

    def test_degraded_intention_still_rendered(self):
        section = build_intention_section(_intention(intention="continue_topic", degraded=True))
        assert "延续话题（自然延续当前话题）" in section

    def test_none_intention_returns_none(self):
        assert build_intention_section(None) is None

    def test_section_budget(self):
        section = build_intention_section(_intention())
        intent_line = section.split("\n")[1]
        assert len(intent_line) <= INTENTION_BUDGET_CHARS


class TestBuilderIntegration:
    def test_sections_injected_after_relationship_before_memory(self):
        sections = _render(GoalContext(selected_goal=_selected(), intention=_intention()))
        relationship_idx = next(
            i for i, s in enumerate(sections) if "【与用户的关系】" in s
        )
        goal_idx = next(i for i, s in enumerate(sections) if "【角色当前目标】" in s)
        intention_idx = next(i for i, s in enumerate(sections) if "【本轮意图】" in s)
        memory_idx = next(
            (i for i, s in enumerate(sections) if "【你记得关于用户的事】" in s),
            len(sections),
        )
        assert relationship_idx < goal_idx < intention_idx < memory_idx

    def test_no_internal_fields_in_prompt(self):
        joined = "\n".join(_render(GoalContext(selected_goal=_selected(), intention=_intention())))
        assert "g-1" not in joined
        assert "priority" not in joined
        assert "horizon" not in joined
        assert "user_care" not in joined

    def test_v1_path_without_analysis_omits_sections(self):
        prompt = PromptBuilder.build("default", _state())
        sections = [m.content for m in prompt.format_messages()]
        assert all("【角色当前目标】" not in s for s in sections)
        assert all("【本轮意图】" not in s for s in sections)

    def test_none_goal_ctx_omits_sections(self):
        sections = _render(None)
        assert all("【角色当前目标】" not in s for s in sections)
        assert all("【本轮意图】" not in s for s in sections)

    def test_none_goal_with_intention_only_renders_intention(self):
        sections = _render(
            GoalContext(
                selected_goal=SelectedGoal(goal=None, reason="降级"),
                intention=_intention(),
            )
        )
        assert all("【角色当前目标】" not in s for s in sections)
        assert any("【本轮意图】" in s for s in sections)
