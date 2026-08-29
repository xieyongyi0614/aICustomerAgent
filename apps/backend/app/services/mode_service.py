"""V6.5 Mode 迟滞稳定器（conversation-mode.md §3.2）。纯函数，R1~R5 表驱动。"""

import logging
from dataclasses import dataclass

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_MODES = frozenset({"professional", "default", "immersive"})


@dataclass
class ModeDecision:
    effective: str
    rule: str
    write_back: bool
    switched: bool


_candidate_turns: dict[str, int] = {}


def reset_candidate_counts() -> None:
    _candidate_turns.clear()


def stabilize(
    confirmed_mode: str,
    candidate: str,
    confidence: float,
    session_id: str = "",
    idle_seconds: float = 0.0,
) -> ModeDecision:
    if confirmed_mode not in _MODES:
        confirmed_mode = "default"
    settings = get_settings()
    if idle_seconds > settings.mode_idle_reset_seconds:
        return ModeDecision(effective="default", rule="R4", write_back=True, switched=confirmed_mode != "default")
    if candidate not in _MODES:
        return ModeDecision(effective=confirmed_mode, rule="R5", write_back=False, switched=False)
    if candidate == confirmed_mode:
        if session_id:
            _candidate_turns.pop(session_id, None)
        return ModeDecision(effective=confirmed_mode, rule="R1", write_back=False, switched=False)
    turns_in_candidate = _candidate_turns.get(session_id, 0) + 1
    if session_id:
        _candidate_turns[session_id] = turns_in_candidate
    if (
        confidence >= settings.mode_switch_min_confidence
        and turns_in_candidate >= settings.mode_switch_min_turns
    ):
        if session_id:
            _candidate_turns.pop(session_id, None)
        return ModeDecision(effective=candidate, rule="R2", write_back=True, switched=True)
    return ModeDecision(effective=confirmed_mode, rule="R3", write_back=False, switched=False)
