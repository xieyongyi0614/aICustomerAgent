from datetime import datetime

from app.models.scene import SceneContext, SceneState
from app.models.world import WEEKDAY_CN

RHYTHM_BLOCK = """【回复节奏】
一次回复只推进合理的一小步剧情：
- {action_line}
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

ACTION_LINE_DEFAULT = "0~2 个角色动作（含 *动作描写*）"


def action_budget_line(budget) -> str:
    if budget is None or not budget.allow_action_desc:
        return "0 个角色动作（含 *动作描写*）：本轮不做动作描写"
    if budget.max_action_desc == 0:
        return "0 个角色动作（含 *动作描写*）：本轮不做动作描写"
    if budget.max_action_desc == 1:
        return "最多 1 个角色动作（含 *动作描写*），放在最关键处"
    return "最多 2 个角色动作（含 *动作描写*），不连续堆叠"


def has_scene_content(state: SceneState) -> bool:
    return bool(state.completed_actions) or any(
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
    if state.last_active_at is not None:
        now = datetime.now()
        lines.append(
            f"现在时间：{now:%Y-%m-%d %H:%M}（星期{WEEKDAY_CN[now.weekday()]}）；"
            f"本场景开始于{state.last_active_at:%Y-%m-%d %H:%M}"
        )
    if state.location is not None:
        lines.append(f"地点：{state.location}")
    if state.current_activity is not None:
        lines.append(f"活动：{state.current_activity}")
    if state.current_action is not None:
        lines.append(f"正在做：{state.current_action}")
    pending = state.pending_action
    if pending is not None and pending.status == "pending":
        lines.append(f"待完成动作：{pending.action}（状态：{pending.status}）")
    if state.completed_actions:
        lines.append(
            "刚完成：" + "、".join(state.completed_actions)
            + "（这些动作已经发生，不要再重复执行或描写）"
        )
    if state.scene_mood is not None:
        lines.append(f"氛围：{state.scene_mood}")
    return "\n".join(lines)


def build_directive_section(directive: str | None) -> str | None:
    if not directive:
        return None
    return f"【本轮指令】\n{directive}"


def build_scene_sections(ctx: SceneContext, budget=None) -> list[str]:
    sections: list[str] = []
    scene = build_scene_section(ctx.state)
    if scene is not None:
        sections.append(scene)
    directive = build_directive_section(ctx.directive)
    if directive is not None:
        sections.append(directive)
    sections.append(_rhythm_block(budget))
    return sections


def _rhythm_block(budget=None) -> str:
    if budget is None:
        return RHYTHM_BLOCK.replace("{action_line}", ACTION_LINE_DEFAULT)
    return RHYTHM_BLOCK.replace("{action_line}", action_budget_line(budget))
