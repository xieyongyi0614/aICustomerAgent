"""反思 Prompt（REF-004）。

输入：证据组（成员含截断内容/时间/来源/weight，按 weight 降序取 top）+ 类型约束
说明 + scope 选项 + 反例字段强制。输出 ReflectionProposal 结构化 JSON。
LLM 无权：决定 confidence 终值（代码按证据强度折算）、直写其他域、修改证据。
"""

REFLECTION_SYSTEM_PROMPT = """你是角色的反思引擎：从一组已沉淀的记忆证据中形成关于用户的认知（Insight）。

判定原则：
- 结论必须完全由给出的证据支撑，不得超出证据可支撑的范围（不要外推、不要脑补细节）。
- 每条候选结论必须引用支撑它的证据编号（evidence_ids），引用不存在的证据编号视为无效。
- 每条候选结论必须填写 counter_evidence 字段：说明「证据不支持什么」；确无反例时填「无」。
- type 取值：belief（对用户的具体看法）/ preference（稳定偏好）/ pattern（跨时间的重复模式）。
- scope 取值：user（关于用户本人）/ relationship（关于你们的关系）/ world（关于环境世界）。

只依据给出的证据组输出，不要臆造信息。"""

EVIDENCE_LINE_TEMPLATE = "[E{index}] ({date} {source}) {content}"


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def build_evidence_block(window, max_members: int, content_chars: int) -> tuple[str, list]:
    """渲染证据块；返回 (文本, 提供给 LLM 的成员列表)。成员按 weight 降序截断。"""
    members = sorted(window.members, key=lambda member: member.weight, reverse=True)
    provided = members[:max_members]
    lines = [
        EVIDENCE_LINE_TEMPLATE.format(
            index=index + 1,
            date=member.created_at.strftime("%Y-%m-%d"),
            source=member.source,
            content=_clip(member.content, content_chars),
        )
        for index, member in enumerate(provided)
    ]
    return "\n".join(lines), provided


def build_reflection_messages(window) -> list[tuple[str, str]]:
    from app.core.settings import get_settings

    settings = get_settings()
    evidence_block, _provided = build_evidence_block(
        window,
        settings.v2_reflection_evidence_max_members,
        settings.v2_reflection_evidence_content_chars,
    )
    user_prompt = (
        f"证据组（同一主题的时间窗聚合，共 {len(_provided)} 条）：\n{evidence_block}\n\n"
        "请从以上证据形成候选 Insight（最多 3 条），每条包含 statement（陈述句）、"
        "type、scope、evidence_ids（引用 [E编号] 对应的成员 id）、"
        "counter_evidence（证据不支持什么，无反例填「无」）、self_confidence（0~1 自评，"
        "仅作参考，终值由系统按证据强度校准）。"
    )
    return [
        ("system", REFLECTION_SYSTEM_PROMPT),
        ("user", user_prompt),
    ]
