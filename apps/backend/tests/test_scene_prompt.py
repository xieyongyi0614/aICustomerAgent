from app.models.conversation import ChatMessage, ConversationState
from app.models.scene import SceneContext, SceneState
from app.prompts.builder import PromptBuilder


def _conv_state() -> ConversationState:
    return ConversationState(
        session_id="s-1",
        user_id="u-1",
        messages=[
            ChatMessage(role="human", content="给我拿瓶水"),
            ChatMessage(role="ai", content="好，我去拿。"),
        ],
        summary=None,
        memories=[],
        current_input="好的",
    )


def _empty_scene() -> SceneState:
    return SceneState(session_id="s-1")


def _render(ctx):
    prompt = PromptBuilder.build("immersive", _conv_state(), scene_ctx=ctx)
    return "".join(m.content for m in prompt.format_messages())


def test_scene_section_rendered_when_content_present():
    state = SceneState(
        session_id="s-1",
        location="客厅",
        current_activity="休息",
        current_action="切西瓜",
    )
    ctx = SceneContext(state=state, intent="continue_scene")
    rendered = _render(ctx)
    assert "【当前场景】" in rendered
    assert "地点：客厅" in rendered
    assert "活动：休息" in rendered
    assert "正在做：切西瓜" in rendered


def test_scene_section_omitted_when_empty():
    ctx = SceneContext(state=_empty_scene(), intent="chat")
    rendered = _render(ctx)
    assert "【当前场景】" not in rendered
    assert "【回复节奏】" in rendered


def test_directive_rendered_when_present():
    state = SceneState(session_id="s-1", location="客厅")
    ctx = SceneContext(
        state=state, intent="correct_scene", directive="本轮必须先执行“切西瓜”"
    )
    rendered = _render(ctx)
    assert "【本轮指令】" in rendered
    assert "必须先执行“切西瓜”" in rendered


def test_directive_omitted_when_absent():
    ctx = SceneContext(state=_empty_scene(), intent="chat")
    rendered = _render(ctx)
    assert "【本轮指令】" not in rendered


def test_rhythm_block_always_present_with_scene_ctx():
    ctx = SceneContext(state=_empty_scene(), intent="chat")
    rendered = _render(ctx)
    assert "【回复节奏】" in rendered
    assert "不替用户行动" in rendered


def test_no_scene_ctx_preserves_v2_output():
    prompt = PromptBuilder.build("immersive", _conv_state())
    rendered = "".join(m.content for m in prompt.format_messages())
    assert "【当前场景】" not in rendered
    assert "【回复节奏】" not in rendered
    assert "【本轮指令】" not in rendered
    assert "好的" in rendered
