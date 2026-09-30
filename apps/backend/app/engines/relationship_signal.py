"""V8.5 M2 Interaction Analyzer（interaction-analysis.md）。

信号是演化的唯一上游输入：启发式词表（通道 A）+ 既有 LLM 可选字段（通道 B），
P0 零新增 LLM 调用。信号不落库；落库的只有升格后的事件。
"""

import logging
from collections import deque
from datetime import datetime

from app.character.asuna.relationship_lexicon import SIGNAL_LEXICON
from app.core.settings import get_settings
from app.models.emotion import TurnAnalysis
from app.models.relationship import InteractionSignal

logger = logging.getLogger(__name__)

MAGNITUDE_STRONG_SALIENCE = 0.7
MAGNITUDE_NORMAL_SALIENCE = 0.4

# kind × quality → (RelationshipEventType, magnitude_rule)
# magnitude_rule: "salience" 按显著度分档 / "weak" 一律弱档 / "normal_floor" 一律 normal 以上
SIGNAL_EVENT_MATRIX: dict[tuple[str, str], tuple[str, str]] = {
    ("self_disclosure", "positive"): ("intimate_moment", "salience"),
    ("support", "positive"): ("user_care", "salience"),
    ("gratitude", "positive"): ("praise", "salience"),
    ("appreciation", "positive"): ("praise", "salience"),
    ("humor", "positive"): ("warm_moment", "salience"),
    ("shared_activity", "positive"): ("long_interaction", "salience"),
    ("smalltalk", "positive"): ("long_interaction", "weak"),
    ("ambient", "positive"): ("long_interaction", "weak"),
    ("request_help", "positive"): ("user_care", "salience"),
    ("teaching", "positive"): ("user_help", "salience"),
    ("promise", "positive"): ("promise_kept", "salience"),
    ("promise", "negative"): ("promise_broken", "salience"),
    ("criticism", "negative"): ("criticized", "salience"),
    ("boundary_violation", "negative"): ("boundary_violation", "normal_floor"),
    ("conflict", "negative"): ("conflict", "salience"),
}


def detect_heuristic(user_message: str, ai_reply: str = "") -> InteractionSignal | None:
    """通道 A：词表高置信命中（宁缺毋滥；敏感类宁误报不漏报）。

    一轮至多一个主信号（显著性最高者）。
    """
    text = f"{user_message}\n{ai_reply}" if ai_reply else user_message
    best: InteractionSignal | None = None
    for patterns, kind, quality, salience in SIGNAL_LEXICON:
        if not any(pattern in text for pattern in patterns):
            continue
        if best is None or salience > best.salience:
            best = InteractionSignal(kind=kind, quality=quality, salience=salience)
    return best


def signal_from_analysis(analysis: TurnAnalysis) -> InteractionSignal | None:
    """通道 B：既有 turn_analysis_chain 输出的可选 interaction_signal 字段。"""
    signal = getattr(analysis, "interaction_signal", None)
    if signal is None or (signal.kind, signal.quality) not in SIGNAL_EVENT_MATRIX:
        return None
    return signal


def analyze_interaction(
    user_message: str,
    analysis: TurnAnalysis | None = None,
    ai_reply: str = "",
) -> InteractionSignal | None:
    """双通道检测：LLM 字段优先，缺失/非法降级通道 A。"""
    if analysis is not None:
        signal = signal_from_analysis(analysis)
        if signal is not None:
            return signal
    return detect_heuristic(user_message, ai_reply)


def _magnitude_for(rule: str, salience: float) -> str:
    if rule == "weak":
        return "weak"
    if rule == "normal_floor":
        return "strong" if salience >= MAGNITUDE_STRONG_SALIENCE else "normal"
    if salience >= MAGNITUDE_STRONG_SALIENCE:
        return "strong"
    if salience >= MAGNITUDE_NORMAL_SALIENCE:
        return "normal"
    return "weak"


def map_signal_to_event(signal: InteractionSignal | None) -> tuple[str, str]:
    """信号 → V5 事件映射矩阵（纯函数）：信号不直接产生 delta。"""
    if signal is None:
        return "none", "normal"
    entry = SIGNAL_EVENT_MATRIX.get((signal.kind, signal.quality))
    if entry is None:
        if signal.quality != "neutral":
            return "none", "normal"
        neutral = SIGNAL_EVENT_MATRIX.get((signal.kind, "positive"))
        if neutral is None:
            return "none", "normal"
        return neutral[0], "weak"
    event_type, rule = entry
    return event_type, _magnitude_for(rule, signal.salience)


def novelty_for(count: int) -> float:
    """新颖度 = 1/(1+窗口内同 kind+quality 重复次数)：0/1/3 次 → 1.0/0.5/0.25。"""
    return 1.0 / (1.0 + count)


class EvidenceWindow:
    """每用户环形证据窗（内存结构，不落库）：novelty 与边际递减计数用。"""

    def __init__(self, capacity: int | None = None):
        settings = get_settings()
        self._entries: deque[tuple[str, str]] = deque(
            maxlen=capacity or settings.rel_signal_evidence_window
        )

    def record(self, signal: InteractionSignal) -> None:
        self._entries.append((signal.kind, signal.quality))

    def count(self, kind: str, quality: str) -> int:
        return sum(
            1
            for entry_kind, entry_quality in self._entries
            if entry_kind == kind and entry_quality == quality
        )

    def novelty(self, signal: InteractionSignal) -> float:
        return novelty_for(self.count(signal.kind, signal.quality))

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._entries)

    @classmethod
    def rebuild_from_events(cls, events: list) -> "EvidenceWindow":
        """冷启动从账本近 N 行近似重建：强档≈positive、其余≈neutral。"""
        window = cls()
        for event in events:
            quality = "positive" if event.magnitude == "strong" else "neutral"
            kind = _KIND_FOR_EVENT.get(event.type, "ambient")
            window._entries.append((kind, quality))
        return window


_KIND_FOR_EVENT: dict[str, str] = {
    "intimate_moment": "self_disclosure",
    "user_care": "support",
    "praise": "gratitude",
    "warm_moment": "humor",
    "long_interaction": "ambient",
    "user_help": "teaching",
    "promise_kept": "promise",
    "promise_broken": "promise",
    "criticized": "criticism",
    "boundary_violation": "boundary_violation",
    "conflict": "conflict",
}


def observe(
    window: EvidenceWindow, signal: InteractionSignal | None
) -> InteractionSignal | None:
    """把信号并入证据窗并回填新颖度；无信号轮原样返回。"""
    if signal is None:
        return None
    novelty = window.novelty(signal)
    window.record(signal)
    return signal.model_copy(update={"novelty": novelty})


def resolve_turn_signal(
    user_message: str,
    analysis: TurnAnalysis | None,
    window: EvidenceWindow,
    now: datetime | None = None,
    ai_reply: str = "",
) -> InteractionSignal | None:
    """一轮完整信号解析：检测 → 新颖度回填 → 并窗。"""
    signal = analyze_interaction(user_message, analysis, ai_reply)
    return observe(window, signal)