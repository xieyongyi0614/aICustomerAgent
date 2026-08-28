from app.models.scene import SceneContext, SceneState

RHYTHM_BLOCK = """【回复节奏】
一次回复只推进合理的一小步剧情：
- 0~2 个角色动作（含 *动作描写*）
- 0~2 句角色台词
- 尽量不主动改变场景
- 不替用户决定动作
- 不替用户决定情绪与心理
- 不主动结束剧情

【角色扮演硬约束】
- 不替用户行动：禁止“你接过”“你点点头”等第二人称用户动作描写，除非用户已明确表达
- 不凭空创造用户心理：禁止“你一定很开心”“你看起来害羞”，除非上下文有明确依据
- 存在待完成动作时，回复必须围绕“完成 / 继续 / 取消 / 响应”它，而不是发明新剧情
- 用户纠正优先级最高：correct_scene 时本轮唯一任务就是执行 / 修正待完成动作"""


def has_scene_content(state: SceneState) -> bool:
    return any(
        value is not None
        for value in (
            state.location,
            state.current_activity,
            state.current_action,
            state.pending_action,
        )
    )


def build_scene_section(state: SceneState) -> str | None:
    if not has_scene_content(state):
        return None
    lines = ["【当前场景】"]
    if state.location is not None:
        lines.append(f"地点：{state.location}")
    if state.current_activity is not None:
        lines.append(f"活动：{state.current_activity}")
    if state.current_action is not None:
        lines.append(f"正在做：{state.current_action}")
    if state.pending_action is not None:
        lines.append(
            f"待完成动作：{state.pending_action.action}（状态：{state.pending_action.status}）"
        )
    if state.scene_mood is not None:
        lines.append(f"氛围：{state.scene_mood}")
    return "\n".join(lines)


def build_directive_section(directive: str | None) -> str | None:
    if not directive:
        return None
    return f"【本轮指令】\n{directive}"


def build_scene_sections(ctx: SceneContext) -> list[str]:
    sections: list[str] = []
    scene = build_scene_section(ctx.state)
    if scene is not None:
        sections.append(scene)
    directive = build_directive_section(ctx.directive)
    if directive is not None:
        sections.append(directive)
    sections.append(RHYTHM_BLOCK)
    return sections
