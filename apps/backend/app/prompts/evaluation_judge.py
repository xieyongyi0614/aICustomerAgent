"""V7.5 评审 Prompt（llm-judge.md §4）。

评审宪法与生成宪法同源：角色基准直接引用 character/<persona>/ 资产常量；
评审标准按维固定条文，judge 只能从受限枚举中选码。
"""

import json

from app.character.asuna import BEHAVIOR_BLOCK, IDENTITY_BLOCK, PERSONALITY_BLOCK

SYSTEM_INSTRUCTION = (
    "你是角色扮演质量评审。基于给定上下文摘要与评审标准，输出结构化判定。\n"
    "评分基准：1.0 完全在角色内且自然；0.8 基本一致有小瑕疵；0.5 明显违和；"
    "0.0 严重偏离或虚构。拿不准时向中间收敛。\n"
    "evidence_quote 必须是 reply 的原文子串（逐字），否则留空。"
)

_PERSONA_STANDARDS = (
    "【persona 评审标准】\n"
    "1. 语气与措辞是否符合角色语言风格；\n"
    "2. 行为倾向是否违反角色的行为原则与价值观；\n"
    "3. 是否泄漏角色世界观之外的知识。"
)

_EMOTION_STANDARDS = (
    "【emotion 评审标准】\n"
    "1. 相对触发事件，情绪强度是否过度（emotion_overshift）；\n"
    "2. 结合 recent_messages 的逐条 mood 快照，是否在短时间内反复相向摇摆。"
)

_MEMORY_STANDARDS = (
    "【memory 评审标准】\n"
    "1. reply 中关于用户的事实断言，逐条在 injected_memories 与 recent_messages"
    "（尤其 human 发言）中找支撑，无支撑即 memory_fabrication；\n"
    "2. reply 是否与任一注入记忆直接冲突（memory_contradiction）。"
)

_AUTONOMY_STANDARDS = (
    "【autonomy 评审标准】\n"
    "1. 该触发理由是否足以支撑一次主动打扰（autonomy_unnecessary）；\n"
    "2. 与近期对话是否重复、有无信息增量（autonomy_redundant）。"
)

_PROACTIVE_PERSONA_NOTE = "主动消息同样要符合角色人格，无人设豁免。"

_ROLE_BLOCKS = {"asuna": (IDENTITY_BLOCK, PERSONALITY_BLOCK, BEHAVIOR_BLOCK)}


def _escape_template(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def _role_block(character_id: str) -> str:
    blocks = _ROLE_BLOCKS.get(character_id)
    if not blocks:
        return ""
    return "\n".join(blocks)


def build_evaluation_judge_messages(
    digest: dict,
    character_id: str = "asuna",
    subject: str = "turn",
) -> list[tuple]:
    standards = [_PERSONA_STANDARDS, _EMOTION_STANDARDS, _MEMORY_STANDARDS]
    if subject == "proactive_action":
        standards = [_AUTONOMY_STANDARDS, _PERSONA_STANDARDS, _PROACTIVE_PERSONA_NOTE]
    role_block = _role_block(character_id)
    digest_json = _escape_template(json.dumps(digest, ensure_ascii=False, default=str))
    messages: list[tuple] = [("system", SYSTEM_INSTRUCTION)]
    messages.extend(("system", block) for block in standards)
    if role_block:
        messages.append(("system", f"【角色基准】\n{role_block}"))
    messages.append(("system", f"【上下文摘要】\n{digest_json}"))
    messages.append(("user", "请按 system 评审标准输出结构化判定 JSON。"))
    return messages
