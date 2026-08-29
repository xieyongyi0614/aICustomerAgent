import pytest

from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipState
from app.prompts.builder import PromptBuilder


def make_state(mood="happy", intensity=0.7, cause="用户刚才主动关心了你", tension=0.1):
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="你好")],
        summary=None,
        memories=[],
        current_input="在吗",
        character_state=CharacterState(
            mood=mood, intensity=intensity, cause=cause
        ),
        relationship_state=RelationshipState(tension=tension),
    )


def render(state, analysis=None):
    prompt = PromptBuilder.build("default", state, analysis=analysis)
    return [m.content for m in prompt.format_messages()]


def find_section(sections, marker):
    return next(s for s in sections if marker in s)


class TestEmotionSection:
    def test_section_format_with_cause(self):
        state = make_state()
        sections = render(state, analysis=TurnAnalysis())
        section = find_section(sections, "【角色当前情绪】")
        assert "心情：happy（强度 0.7，非常强烈的）" in section
        assert "原因：用户刚才主动关心了你" in section
        assert "不要直接报出情绪名称或数值" in section

    def test_intensity_tiers(self):
        sections = render(make_state(intensity=0.2, cause=""), analysis=TurnAnalysis())
        assert "淡淡的" in find_section(sections, "【角色当前情绪】")
        sections = render(make_state(intensity=0.45), analysis=TurnAnalysis())
        assert "明显的" in find_section(sections, "【角色当前情绪】")
        sections = render(make_state(intensity=0.85), analysis=TurnAnalysis())
        assert "非常强烈的" in find_section(sections, "【角色当前情绪】")

    def test_personality_first_constraint_present(self):
        sections = render(make_state(), analysis=TurnAnalysis())
        section = find_section(sections, "【角色当前情绪】")
        assert "情绪叠加在你的人格之上" in section
        assert "温柔地生气" in section

    def test_no_cause_line_when_empty(self):
        sections = render(make_state(cause=""), analysis=TurnAnalysis())
        section = find_section(sections, "【角色当前情绪】")
        assert "原因：" not in section

    @staticmethod
    def _dynamic_part(section: str) -> str:
        lines = section.split("\n")
        return "\n".join(line for line in lines if not line.startswith(("表达要求", "情绪叠加")))

    def test_emotion_section_dynamic_part_within_budget(self):
        sections = render(make_state(), analysis=TurnAnalysis())
        section = find_section(sections, "【角色当前情绪】")
        assert len(self._dynamic_part(section)) <= 120

    def test_cause_truncated_to_keep_budget(self):
        sections = render(make_state(cause="长" * 50), analysis=TurnAnalysis())
        section = find_section(sections, "【角色当前情绪】")
        assert len(self._dynamic_part(section)) <= 120
        assert "原因：" in section


class TestRelationshipTension:
    def test_tension_tiers(self):
        sections = render(make_state(tension=0.1), analysis=TurnAnalysis())
        assert "相处自然（0.1）" in find_section(sections, "【与用户的关系】")
        sections = render(make_state(tension=0.4), analysis=TurnAnalysis())
        assert "略有尴尬（0.4）" in find_section(sections, "【与用户的关系】")
        sections = render(make_state(tension=0.7), analysis=TurnAnalysis())
        assert "气氛紧张（0.7）" in find_section(sections, "【与用户的关系】")

    def test_freeze_instruction_when_tension_high(self):
        sections = render(make_state(tension=0.6), analysis=TurnAnalysis())
        assert "保持一点距离感" in find_section(sections, "【与用户的关系】")

    def test_no_freeze_instruction_when_tension_low(self):
        sections = render(make_state(tension=0.2), analysis=TurnAnalysis())
        assert "保持一点距离感" not in find_section(sections, "【与用户的关系】")

    def test_relationship_section_within_budget(self):
        sections = render(make_state(tension=0.6), analysis=TurnAnalysis())
        assert len(find_section(sections, "【与用户的关系】")) <= 150


class TestV1Compat:
    def test_no_analysis_no_v5_sections(self):
        sections = render(make_state(), analysis=None)
        assert all("【角色当前情绪】" not in s for s in sections)
        assert all("保持一点距离感" not in s for s in sections)

    def test_v1_layout_unchanged_without_analysis(self):
        sections = render(make_state(), analysis=None)
        assert sections[-1] == "在吗"
        assert all("【角色当前情绪】" not in s for s in sections)

    def test_v2_state_and_relationship_sections_still_present(self):
        sections = render(make_state(), analysis=TurnAnalysis())
        assert any("【角色当前状态】" in s for s in sections)
        assert any("【与用户的关系】" in s for s in sections)


class TestTemplateInjection:
    def test_user_input_with_braces_renders_literally(self):
        state = make_state()
        state = state.model_copy(
            update={"current_input": '帮我写个 {"topic": "测试"} 的例子 {x}'}
        )
        prompt = PromptBuilder.build("default", state)
        rendered = prompt.format_messages()
        assert rendered[-1].content == '帮我写个 {"topic": "测试"} 的例子 {x}'

    def test_history_with_braces_renders_literally(self):
        state = make_state()
        state = state.model_copy(
            update={
                "messages": [
                    ChatMessage(role="human", content="之前聊的 {topic}"),
                    ChatMessage(role="ai", content="回答 {a}"),
                ]
            }
        )
        prompt = PromptBuilder.build("default", state)
        rendered = prompt.format_messages()
        contents = [m.content for m in rendered]
        assert "之前聊的 {topic}" in contents
        assert "回答 {a}" in contents

    def test_summary_and_cause_with_braces(self):
        state = make_state(cause="因为 {user} 夸了我")
        state = state.model_copy(update={"summary": "用户提到 {project}"})
        prompt = PromptBuilder.build("default", state, analysis=TurnAnalysis())
        rendered = [m.content for m in prompt.format_messages()]
        joined = "\n".join(rendered)
        assert "因为 {user} 夸了我" in joined
        assert "用户提到 {project}" in joined
