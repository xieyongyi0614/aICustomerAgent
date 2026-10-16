import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from app.character.asuna import (
    BEHAVIOR_BLOCK,
    BEHAVIOR_INSTRUCTIONS,
    IDENTITY_BLOCK,
    MODE_INSTRUCTIONS,
    PERSONALITY_BLOCK,
    RELATIONSHIP_BLOCK,
    STAGE_DESCRIPTIONS,
    STAGE_LABELS,
    describe_level,
)
from app.character.asuna.relationship_lexicon import (
    CONFLICT_DIRECTIVES,
    DEFAULT_COMFORT,
    DEFAULT_RESPECT,
    NEGLECT_RETURN_NOTE,
    describe_comfort,
    describe_respect,
)
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.style_contract import StyleContract
from app.core.settings import get_settings
from app.services.world.context_selector import render_world_section
from app.prompts.behavior import build_activity_section, build_behavior_section
from app.prompts.goal import build_goal_section, build_intention_section
from app.prompts.scene import build_scene_sections
from app.repositories import relationship_milestone_repository
from app.services.action.context import render_action_section
from app.services.relationship.milestone import MILESTONES

logger = logging.getLogger(__name__)

MEMORY_TYPE_LABELS = {
    "user_preference": "偏好",
    "user_fact": "事实",
    "experience": "经历",
    "relationship_fact": "关系",
    "commitment": "目标",
    "milestone_event": "里程碑",
    "behavior_pattern": "习惯",
}
"""记忆类型中文标签（键覆盖 `CANONICAL_MEMORY_TYPES` 全部 7 值，有静态用例钉住）。

键顺序 = `CANONICAL_MEMORY_TYPES`。措辞与记忆产品读面
（`services/memory/product_view.py::TYPE_LABELS`）同源；其中
`user_fact` / `experience` 与 `commitment` / `milestone_event` 在该表内同标签，
此处按「标签两两不同」纪律细化为「事实 / 经历」「目标 / 里程碑」。
遗留类型名（`important_event` / `relationship_event`）已退役，不再入表；
`memory_type_label` 对未覆盖值落回原值并告警（旧库行不会因此失败）。
"""

INSIGHT_TYPE_LABELS = {
    "belief": "看法",
    "preference": "偏好",
    "pattern": "模式",
}


def memory_type_label(memory_type: str) -> str:
    """标签查表：未覆盖的类型落回原值并告警（prompt 装配不得因数据异常失败）。"""
    label = MEMORY_TYPE_LABELS.get(memory_type)
    if label is None:
        logger.warning("unknown memory type for label: %s", memory_type)
        return memory_type
    return label


EMOTION_BUDGET_CHARS = 120
RELATIONSHIP_BUDGET_CHARS = 150

STYLE_SECTION_HEADER = "【本轮表达风格】"
STYLE_SECTION_BUDGET_CHARS = 300

SHARED_EXPERIENCE_HEADER = "【共同经历】"
SHARED_EXPERIENCE_NOTE = "（这是你们一起经历过的事，仅自然相关时提起，不要罗列）"

RELATIONSHIP_PATTERN_HEADER = "【关系模式】"
RELATIONSHIP_PATTERN_NOTE = "（这是你们相处中形成的模式，融入互动即可，不要直接引用）"
RELATIONSHIP_PATTERN_STATEMENT_CHARS = 60

PERSONALITY_FIRST_CONSTRAINT = (
    "情绪叠加在你的人格之上：无论此刻情绪如何，你说话的方式、价值观和性格底色不变。"
    "温柔的角色生气时是“温柔地生气”，不是变成另一个人。"
)

EXPRESS_EMOTION_RULE = (
    "表达要求：情绪通过语气、用词和节奏自然流露，不要直接报出情绪名称或数值。"
)

TENSION_FREEZE_RULE = "最近气氛有些紧张，对话中保持一点距离感，直到氛围缓和。"

_MID_BAND = (0.4, 0.7)


def _literal(text: str) -> str:
    """转义花括号，使动态内容不被 ChatPromptTemplate 当作模板变量。"""
    return text.replace("{", "{{").replace("}", "}}")


def _append_within_budget(section: str, lines: list[str], budget: int) -> str:
    result = section
    for line in lines:
        candidate = f"{result}\n{line}"
        if len(candidate) > budget:
            break
        result = candidate
    return result


def _safe_recent_milestone_title(user_id: str) -> str | None:
    try:
        worthy = {spec.key for spec in MILESTONES if spec.memory_worthy}
        for record in relationship_milestone_repository.list_milestones(user_id):
            if record.milestone_key in worthy and record.title:
                return record.title[:30]
    except Exception:
        return None
    return None


class PromptBuilder:
    @staticmethod
    def build_identity_sections() -> list[str]:
        return [
            IDENTITY_BLOCK,
            PERSONALITY_BLOCK,
            RELATIONSHIP_BLOCK,
            BEHAVIOR_BLOCK,
        ]

    @staticmethod
    def build_emotion_section(state: ConversationState) -> str:
        character = state.character_state
        intensity = character.intensity
        if intensity <= 0.3:
            tier = "淡淡的"
        elif intensity <= 0.6:
            tier = "明显的"
        else:
            tier = "非常强烈的"
        header = "【角色当前情绪】"
        mood_line = f"心情：{character.mood}（强度 {intensity:.1f}，{tier}）"
        budget = EMOTION_BUDGET_CHARS - len(header) - len(mood_line) - 1
        cause_line = None
        if character.cause:
            cause_text = character.cause
            if len(cause_text) + 3 > budget:
                cause_text = cause_text[: max(budget - 4, 0)] + "…"
            cause_line = f"原因：{cause_text}"
        lines = [header, mood_line]
        if cause_line:
            lines.append(cause_line)
        lines.append(EXPRESS_EMOTION_RULE)
        lines.append(PERSONALITY_FIRST_CONSTRAINT)
        return "\n".join(lines)

    @staticmethod
    def build_character_state_section(state: ConversationState) -> str:
        character = state.character_state
        energy = character.energy
        energy_level = (
            "充沛" if energy >= 0.7 else "一般" if energy >= 0.4 else "有些疲惫"
        )
        topic = character.current_topic or "还没有明确话题"
        return (
            f"【角色当前状态】\n心情：{character.mood}\n精力：{energy_level}\n"
            f"最近在聊：{topic}\n内心：{character.inner_state}"
        )

    @staticmethod
    def build_agent_state_section() -> str | None:
        """V2.1.0 AGENT-002：Run 内组装的统一意识状态只读段（contextvar 通道）。

        仅渲染兴趣/焦点净新增行；Flag 关闭或无快照时返回 None，段不出现。
        """
        from app.application.agent_state_context import get_snapshot

        snapshot = get_snapshot()
        if snapshot is None:
            return None
        lines = snapshot.prompt_lines()
        if not lines:
            return None
        return chr(10).join(lines) + chr(10) + "（这是你此刻真实的兴趣与关注，自然融入表达即可，不要罗列）"

    @staticmethod
    def build_goal_stack_section(state: ConversationState) -> str | None:
        """V2.1.0 AGENT-003：层叠目标栈只读段（L3/L2/L1 各一行，空层跳过）。"""
        layered = getattr(state, "layered_goals", None) or []
        if not layered:
            return None
        labels = {"long_term": "长期", "medium": "中期", "short_term": "当前"}
        by_layer = {}
        for goal in layered:
            by_layer.setdefault(goal.layer, goal)
        lines = [
            f"{labels[layer]}：{goal.description}"
            for layer in ("long_term", "medium", "short_term")
            if (goal := by_layer.get(layer)) is not None
        ]
        if not lines:
            return None
        return chr(10).join(["【目标方向】", *lines]) + chr(10) + "（这些是你自己想做的事，与用户话题自然结合即可，不要刻意汇报）"

    @staticmethod
    def build_relationship_section(
        state: ConversationState,
        *,
        recent_milestone_title: str | None = None,
    ) -> str:
        relationship = state.relationship_state
        label = STAGE_LABELS.get(relationship.stage, STAGE_LABELS["friend"])
        description = STAGE_DESCRIPTIONS.get(
            relationship.stage, STAGE_DESCRIPTIONS["friend"]
        )
        tension = relationship.tension
        if tension <= 0.3:
            tension_tier = "相处自然"
        elif tension <= 0.5:
            tension_tier = "略有尴尬"
        else:
            tension_tier = "气氛紧张"
        section = (
            f"【与用户的关系】\n当前关系：{label}（{description}）\n"
            f"亲密：{describe_level(relationship.intimacy)}　"
            f"信任：{describe_level(relationship.trust)}　"
            f"熟悉：{describe_level(relationship.familiarity)}\n"
            f"紧张度：{tension_tier}（{tension:.1f}）"
        )
        conflict_status = getattr(relationship, "conflict_status", "none") or "none"
        conflict_line = CONFLICT_DIRECTIVES.get(conflict_status)
        show_freeze = tension > 0.5 and conflict_line is None
        if show_freeze:
            section += f"\n{TENSION_FREEZE_RULE}"

        extras: list[str] = []
        if conflict_line is not None:
            extras.append(conflict_line)
        if getattr(relationship, "neglect_active", False):
            extras.append(NEGLECT_RETURN_NOTE)
        if recent_milestone_title:
            extras.append(f"你们最近一起经历了：{recent_milestone_title}")
        respect = getattr(relationship, "respect", DEFAULT_RESPECT)
        comfort = getattr(relationship, "comfort", DEFAULT_COMFORT)
        low, high = _MID_BAND
        if not (low <= respect <= high) or not (low <= comfort <= high):
            extras.append(
                f"尊重：{describe_respect(respect)}　自在：{describe_comfort(comfort)}"
            )
        return _append_within_budget(section, extras, RELATIONSHIP_BUDGET_CHARS)

    @staticmethod
    def build_shared_experience_section(state: ConversationState) -> str | None:
        entries = getattr(state, "shared_experiences", None) or []
        if not entries:
            return None
        settings = get_settings()
        budget = settings.relationship_shared_budget_chars
        lines = [SHARED_EXPERIENCE_HEADER]
        used = len(SHARED_EXPERIENCE_HEADER)
        for entry in entries:
            line = f"· {entry.title}"
            if used + len(line) > budget:
                break
            lines.append(line)
            used += len(line)
        lines.append(SHARED_EXPERIENCE_NOTE)
        return "\n".join(lines)

    @staticmethod
    def build_relationship_pattern_section(state: ConversationState) -> str | None:
        patterns = getattr(state, "relationship_patterns", None) or []
        if not patterns:
            return None
        settings = get_settings()
        budget = settings.relationship_pattern_budget_chars
        lines = [RELATIONSHIP_PATTERN_HEADER]
        used = len(RELATIONSHIP_PATTERN_HEADER)
        for pattern in patterns:
            statement = pattern.statement.strip()
            if len(statement) > RELATIONSHIP_PATTERN_STATEMENT_CHARS:
                statement = (
                    statement[:RELATIONSHIP_PATTERN_STATEMENT_CHARS] + "…"
                )
            line = f"· {statement}"
            if used + len(line) > budget:
                break
            lines.append(line)
            used += len(line)
        lines.append(RELATIONSHIP_PATTERN_NOTE)
        return "\n".join(lines)

    @staticmethod
    def build_style_section(style_ctx: StyleContract | None) -> str | None:
        """V2.2.0 CHAR-007：StyleContract → prompt 风格段（behavior_ctx 并列，Q5）。"""
        if style_ctx is None:
            return None
        lines = style_ctx.prompt_lines()
        if not lines:
            return None
        section = _append_within_budget(
            STYLE_SECTION_HEADER, lines, STYLE_SECTION_BUDGET_CHARS
        )
        if len(section) <= len(STYLE_SECTION_HEADER):
            return None
        return section

    @staticmethod
    def build_behavior_section(analysis: TurnAnalysis) -> str:
        behavior = analysis.behavior.behavior
        instruction = BEHAVIOR_INSTRUCTIONS.get(
            behavior, BEHAVIOR_INSTRUCTIONS["normal_reply"]
        )
        return f"【本轮行为指令】\n{instruction}"

    @staticmethod
    def _fit_variable_parts(
        state: ConversationState, fixed_chars: int
    ) -> tuple[list, list, str | None]:
        settings = get_settings()
        budget = settings.context_total_char_budget - fixed_chars

        history = list(state.messages)
        memories = list(state.memories)
        summary = state.summary

        history_chars = sum(len(m.content) for m in history)
        memory_chars = sum(len(m.content) for m in memories)
        while history and history_chars + memory_chars > budget:
            history_chars -= len(history[0].content)
            history.pop(0)
        while memories and history_chars + memory_chars > budget:
            memory_chars -= len(memories[-1].content)
            memories.pop()
        if summary is not None:
            remaining = budget - history_chars - memory_chars
            if len(summary) > remaining:
                summary = summary[: max(remaining - 1, 0)] + "…"
        return history, memories, summary

    @staticmethod
    def build(
        mode: str,
        state: ConversationState,
        analysis: TurnAnalysis | None = None,
        scene_ctx=None,
        goal_ctx=None,
        behavior_ctx=None,
        world_ctx=None,
        action_ctx=None,
        style_ctx=None,
    ) -> ChatPromptTemplate:
        settings = get_settings()
        roleplay = settings.roleplay_prompt_mode == "full"
        world_budget = settings.world_prompt_char_budget
        brief = getattr(world_ctx, "brief", None) if world_ctx is not None else None
        world_text = (
            render_world_section(world_ctx, world_budget, brief=brief)
            if roleplay
            else None
        )

        action_text = render_action_section(
            action_ctx, get_settings().action_context_char_budget
        )
        identity = (
            [
                ("system", section)
                for section in PromptBuilder.build_identity_sections()
            ]
            if roleplay
            else []
        )
        state_sections: list[str] = []
        if analysis is not None and roleplay:
            milestone_title = _safe_recent_milestone_title(state.user_id)
            state_sections = [
                _literal(PromptBuilder.build_emotion_section(state)),
                _literal(PromptBuilder.build_character_state_section(state)),
                _literal(
                    PromptBuilder.build_relationship_section(
                        state, recent_milestone_title=milestone_title
                    )
                ),
            ]
        tail_sections: list[str] = []
        style_section = None
        if style_ctx is not None and roleplay:
            style_section = PromptBuilder.build_style_section(style_ctx)
            if style_section is not None:
                style_section = _literal(style_section)
        if world_text:
            tail_sections.append(_literal(world_text))
        if action_text:
            tail_sections.append(_literal(action_text))
        if roleplay:
            tail_sections.append(
                MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["default"])
            )
        behavior_section = None
        activity_section = None
        if roleplay and analysis is not None and behavior_ctx is not None:
            activity_section = build_activity_section(behavior_ctx)
            if behavior_ctx.fallback_directive is not None:
                tail_sections.append(_literal(build_behavior_section(behavior_ctx)))
            else:
                behavior_section = build_behavior_section(behavior_ctx)
                if behavior_section is not None:
                    behavior_section = _literal(behavior_section)
            if activity_section is not None:
                activity_section = _literal(activity_section)
        elif analysis is not None and roleplay:
            tail_sections.append(PromptBuilder.build_behavior_section(analysis))
        scene_budget = (
            behavior_ctx.budget
            if behavior_ctx is not None and behavior_ctx.fallback_directive is None
            else None
        )
        if scene_ctx is not None and roleplay:
            tail_sections.extend(
                _literal(section) for section in build_scene_sections(scene_ctx, scene_budget)
            )
        if activity_section is not None:
            tail_sections.append(activity_section)


        goal_section = None
        intention_section = None
        if analysis is not None and goal_ctx is not None:
            goal_section = build_goal_section(goal_ctx.selected_goal)
            intention_section = build_intention_section(goal_ctx.intention)
            if goal_section is not None:
                goal_section = _literal(goal_section)
            if intention_section is not None:
                intention_section = _literal(intention_section)

        fixed_chars = (
            sum(len(text) for _, text in identity)
            + sum(len(text) for text in state_sections)
            + sum(len(text) for text in tail_sections)
            + (len(goal_section) if goal_section else 0)
            + (len(intention_section) if intention_section else 0)
            + (len(behavior_section) if behavior_section else 0)
            + (len(style_section) if style_section else 0)
            + len(state.current_input)
            + 120
        )
        history, memories, summary = PromptBuilder._fit_variable_parts(state, fixed_chars)

        messages = list(identity)
        messages.extend(("system", text) for text in state_sections)
        if style_section is not None:
            messages.append(("system", style_section))
        if goal_section is not None:
            messages.append(("system", goal_section))
        if intention_section is not None:
            messages.append(("system", intention_section))
        if behavior_section is not None:
            messages.append(("system", behavior_section))

        if memories:
            memory_lines = "\n".join(
                f"- ({memory_type_label(m.type)}) {m.content}"
                for m in memories
            )
            messages.append(
                (
                    "system",
                    "【你记得关于用户的事】\n"
                    f"{_literal(memory_lines)}\n"
                    "（仅在自然相关时引用，不要主动罗列；已提到过的事不要复述，除非用户问起）",
                )
            )

        if state.insights:
            insight_lines = "\n".join(
                f"- ({INSIGHT_TYPE_LABELS.get(i.type, i.type)}) {i.statement}"
                for i in state.insights
            )
            messages.append(
                (
                    "system",
                    "【你确信的认知】\n"
                    f"{_literal(insight_lines)}\n"
                    "（这是你基于相处形成的看法，仅在自然相关时体现，不要罗列或直接引用条目）",
                )
            )

        overlay = getattr(state, "development_overlay", None)
        if roleplay and overlay is not None and overlay.modulation_summary:
            messages.append(
                (
                    "system",
                    "【你因经历而改变】\n"
                    f"{_literal(overlay.modulation_summary)}\n"
                    "（这是相处带来的自然变化，融入表达即可，不要直接引用说明）",
                )
            )

        agent_state_section = (
            PromptBuilder.build_agent_state_section() if roleplay else None
        )
        if agent_state_section:
            messages.append(("system", _literal(agent_state_section)))

        goal_stack_section = PromptBuilder.build_goal_stack_section(state)
        if goal_stack_section:
            messages.append(("system", _literal(goal_stack_section)))

        pattern_section = (
            PromptBuilder.build_relationship_pattern_section(state)
            if roleplay
            else None
        )
        if pattern_section:
            messages.append(("system", _literal(pattern_section)))

        shared_section = (
            PromptBuilder.build_shared_experience_section(state)
            if roleplay
            else None
        )
        if shared_section:
            messages.append(("system", _literal(shared_section)))

        if summary:
            messages.append(("system", _literal(f"【对话摘要】\n{summary}")))

        for message in history:
            if message.role == "human":
                messages.append(HumanMessage(content=message.content))
            else:
                messages.append(AIMessage(content=message.content))

        messages.extend(("system", text) for text in tail_sections)
        messages.append(HumanMessage(content=state.current_input))

        return ChatPromptTemplate.from_messages(messages)
