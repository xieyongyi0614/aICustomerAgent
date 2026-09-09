import logging

from langchain_core.runnables import Runnable

from app.chains.structured import build_structured_chain
from app.models.scene import SceneActionDecision, SceneState
from app.prompts.scene_update import scene_update_prompt

logger = logging.getLogger(__name__)


def build_snapshot(state: SceneState) -> str:
    pending = state.pending_action
    pending_line = (
        f"待完成动作：{pending.action}（状态：{pending.status}）"
        if pending is not None and pending.status == "pending"
        else "待完成动作：无"
    )
    completed_line = (
        "刚完成：" + "、".join(state.completed_actions)
        if state.completed_actions
        else "刚完成：无"
    )
    return "\n".join(
        [
            f"地点：{state.location or '未知'}",
            f"活动：{state.current_activity or '未知'}",
            f"正在做：{state.current_action or '未知'}",
            pending_line,
            completed_line,
        ]
    )


def build_chain(llm=None) -> Runnable:
    return build_structured_chain(
        [
            ("system", scene_update_prompt),
            ("user", "用户：{user_input}\nAI：{ai_reply}"),
        ],
        SceneActionDecision,
        llm,
    )


async def detect(
    user_input: str,
    ai_reply: str,
    scene_state: SceneState,
    llm=None,
) -> SceneActionDecision | None:
    chain = build_chain(llm)
    try:
        return await chain.ainvoke(
            {
                "scene_snapshot": build_snapshot(scene_state),
                "user_input": user_input,
                "ai_reply": ai_reply,
            }
        )
    except Exception:
        logger.exception("场景更新链失败，保持上一轮状态")
        return None
