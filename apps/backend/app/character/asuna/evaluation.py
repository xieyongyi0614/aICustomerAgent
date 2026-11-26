"""亚丝娜评估资产（persona-evaluation.md §2.2）：人设矛盾表达模式表 + 工具效能判定规则。

词表按人设走（character/<persona>/ 每人设一套）；allowed_modes 命中当前
会话模式时跳过——immersive 剧情需要的情绪爆发不算 OOC。

TOOL-009 §4.2：追加工具效能证据窗的判定规则资产（窗口 → Insight 类型映射 /
门槛 / 防御性断言）。纯数据与纯函数：无 IO、无 LLM、无状态；聚合在
`app/services/reflection/evidence.py`，闸门与执行在 `reflector.py`。
资产只回答"哪个窗口该产出哪类认知"与"多少证据才算数"，不回答"怎么聚合"。
"""

from pydantic import BaseModel, Field

from app.models.reflection import TOOL_INSIGHT_TYPES


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

# --- 工具效能证据窗（TOOL-009 §2.2 / §4.2）-----------------------------------

TOOL_WINDOW_USAGE_EFFECT = "tool_usage_effect"
TOOL_WINDOW_ACTION_SUCCESS_RATE = "action_success_rate"
TOOL_WINDOW_USER_FEEDBACK = "user_feedback_signal"

TOOL_WINDOW_KINDS: tuple[str, ...] = (
    TOOL_WINDOW_USAGE_EFFECT,
    TOOL_WINDOW_ACTION_SUCCESS_RATE,
    TOOL_WINDOW_USER_FEEDBACK,
)

TOOL_WINDOW_PRIMARY_INSIGHT: dict[str, str] = {
    TOOL_WINDOW_USAGE_EFFECT: "usage_preference",
    TOOL_WINDOW_ACTION_SUCCESS_RATE: "capability_note",
    TOOL_WINDOW_USER_FEEDBACK: "interaction_calibration",
}
"""窗口 → 首选 Insight 类型（`insight_type_for` 的值域来源）。"""

TOOL_WINDOW_PRIORITY: tuple[str, ...] = (
    TOOL_WINDOW_ACTION_SUCCESS_RATE,
    TOOL_WINDOW_USER_FEEDBACK,
    TOOL_WINDOW_USAGE_EFFECT,
)
"""多窗同时达门槛时的确定性优先序（失败驱动链优先答"能力是否可靠"，用量窗兜底）。"""

TOOL_WINDOW_PRIMARY_SCOPE: dict[str, str] = {
    TOOL_WINDOW_ACTION_SUCCESS_RATE: "world",
    TOOL_WINDOW_USER_FEEDBACK: "user",
    TOOL_WINDOW_USAGE_EFFECT: "user",
}
"""窗口 → 首选 scope（能力可靠性属于环境世界；偏好与交互校正属于用户维度）。"""

TOOL_WINDOW_ALLOWED_INSIGHTS: dict[str, tuple[str, ...]] = {
    TOOL_WINDOW_USAGE_EFFECT: ("usage_preference", "capability_note"),
    TOOL_WINDOW_ACTION_SUCCESS_RATE: ("capability_note",),
    TOOL_WINDOW_USER_FEEDBACK: ("interaction_calibration", "usage_preference"),
}
"""窗口 → 允许的 Insight 类型集（窗口一供偏好，窗口一+二供能力自省，窗口三供校正）。"""

TOOL_WINDOW_THRESHOLDS: dict[str, dict[str, float]] = {
    TOOL_WINDOW_USAGE_EFFECT: {"min_samples": 3, "min_span_hours": 24.0},
    TOOL_WINDOW_ACTION_SUCCESS_RATE: {
        "min_samples": 3,
        "min_failures": 3,
        "min_span_hours": 24.0,
    },
    TOOL_WINDOW_USER_FEEDBACK: {"min_samples": 3, "min_span_hours": 24.0},
}
"""样本数 / 时间跨度门槛：与既有 `reflection_min_evidence` / `min_span_hours` 同量级。"""

TOOL_FEEDBACK_POLARITY_NEGATIVE = "negative"
TOOL_FEEDBACK_POLARITY_POSITIVE = "positive"
TOOL_FEEDBACK_POLARITY_NEUTRAL = "neutral"

TOOL_FEEDBACK_NEGATIVE_MARKERS: tuple[str, ...] = (
    "不对",
    "错了",
    "不是这个",
    "不是这样",
    "没用",
    "没有用",
    "算了",
    "不要",
    "不用了",
    "讨厌",
    "好烦",
    "很烦",
    "糟糕",
    "失望",
    "差劲",
    "怎么又",
    "别闹",
    "白费",
)

TOOL_FEEDBACK_POSITIVE_MARKERS: tuple[str, ...] = (
    "谢谢",
    "好的",
    "太棒",
    "很好",
    "不错",
    "可以",
    "收到",
    "辛苦",
    "爱你",
    "喜欢",
    "哈哈",
)

TOOL_FEEDBACK_SILENCE_MIN_AGE_HOURS = 24.0
"""沉默信号最小锚点年龄：刚执行的工具不算"无人回应"（防误判，E8）。"""

TOOL_REVOKE_ACTION_PREFIX = "cancel"
TOOL_REVOKE_SOURCE = "cancel"
TOOL_EVIDENCE_CONTENT_MAX_CHARS = 120

TOOL_INSIGHT_LABELS: dict[str, str] = {
    "capability_note": "能力自省",
    "usage_preference": "使用偏好",
    "interaction_calibration": "交互校正",
}
"""工具效能 Insight 类型 → 反哺理由前缀（角色口吻的中文标签）。"""

TOOL_INSIGHT_INTEREST_PENALTY = 0.3
TOOL_INSIGHT_INTEREST_BOOST = 0.1
"""interest 维软信号权重：能力不可靠降分 / 使用偏好加分（均为软信号，不拆闸门）。"""


def insight_type_for(window_kind: str) -> str:
    """窗口 → 首选 Insight 类型；未知窗口是资产缺口，显式报错（不静默兜底）。"""
    insight_type = TOOL_WINDOW_PRIMARY_INSIGHT.get(window_kind)
    if insight_type is None:
        raise ValueError(f"未知工具证据窗: {window_kind}")
    return insight_type


def allowed_insight_types(window_kind: str) -> tuple[str, ...]:
    """窗口 → 允许的 Insight 类型集；未知窗口显式报错。"""
    allowed = TOOL_WINDOW_ALLOWED_INSIGHTS.get(window_kind)
    if allowed is None:
        raise ValueError(f"未知工具证据窗: {window_kind}")
    return allowed


def thresholds_for(window_kind: str) -> dict[str, float]:
    """窗口 → 门槛（样本数 / 失败数 / 时间跨度）；未知窗口显式报错。"""
    thresholds = TOOL_WINDOW_THRESHOLDS.get(window_kind)
    if thresholds is None:
        raise ValueError(f"未知工具证据窗: {window_kind}")
    return dict(thresholds)


def scope_for(window_kind: str) -> str:
    """窗口 → 首选 scope；未知窗口显式报错。"""
    scope = TOOL_WINDOW_PRIMARY_SCOPE.get(window_kind)
    if scope is None:
        raise ValueError(f"未知工具证据窗: {window_kind}")
    return scope


def is_personality_affecting(window: object) -> bool:
    """恒返回 False（防御性契约）：工具证据不得产生性格 / 人格 / 关系类 Insight。

    把"工具故障不改变人格"固化为可测试的接口契约，而非依赖实现者记忆；
    对任意入参（含 None / 异常形状）都不抛错、不返回 True。
    """
    return False


def insight_type_is_allowed(window_kind: str, insight_type: str) -> bool:
    """提案类型是否属于该窗口的允许集（工具证据的类型闸，E 类防御）。"""
    return insight_type in allowed_insight_types(window_kind)


def tool_insight_type_domain() -> tuple[str, ...]:
    """工具效能 Insight 类型值域（资产侧只读投影，供 prompt 与断言复用）。"""
    return TOOL_INSIGHT_TYPES


def classify_feedback_polarity(content: str) -> str:
    """用户消息极性（零 LLM 词表判定）：命中负向词表 → negative；正向 → positive；其余中性。"""
    text = (content or "").strip()
    if not text:
        return TOOL_FEEDBACK_POLARITY_NEUTRAL
    if any(marker in text for marker in TOOL_FEEDBACK_NEGATIVE_MARKERS):
        return TOOL_FEEDBACK_POLARITY_NEGATIVE
    if any(marker in text for marker in TOOL_FEEDBACK_POSITIVE_MARKERS):
        return TOOL_FEEDBACK_POLARITY_POSITIVE
    return TOOL_FEEDBACK_POLARITY_NEUTRAL


def is_revoke_action(source: str | None, action_type: str | None) -> bool:
    """撤销判定（E9）：`source=cancel` 或 cancel* 行动类型视为用户撤销了工具产生的效果。"""
    if source == TOOL_REVOKE_SOURCE:
        return True
    return str(action_type or "").startswith(TOOL_REVOKE_ACTION_PREFIX)
