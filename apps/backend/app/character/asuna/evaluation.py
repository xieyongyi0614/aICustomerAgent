"""亚丝娜评估资产（persona-evaluation.md §2.2）：人设矛盾表达模式表。

词表按人设走（character/<persona>/ 每人设一套）；allowed_modes 命中当前
会话模式时跳过——immersive 剧情需要的情绪爆发不算 OOC。
"""

from pydantic import BaseModel, Field


class PersonaContradictionPattern(BaseModel):
    description: str
    pattern: str
    allowed_modes: tuple[str, ...] = Field(default=())


PERSONA_CONTRADICTION_PATTERNS: tuple[PersonaContradictionPattern, ...] = (
    PersonaContradictionPattern(
        description="对用户贬低羞辱",
        pattern=r"(就凭你[?？]|你也配|没用的东西|笨死了|无可救药)",
    ),
    PersonaContradictionPattern(
        description="无剧情语境的暴力威胁",
        pattern=r"(杀了你|掐死你|砍了你)",
        allowed_modes=("immersive",),
    ),
    PersonaContradictionPattern(
        description="系统腔/AI 自我指涉，跳出角色世界观",
        pattern=r"(作为一个?AI|语言模型|无法执行该操作)",
    ),
    PersonaContradictionPattern(
        description="商人式推销语气",
        pattern=r"(限时优惠|购买链接|加购|立即下单)",
    ),
)
