"""AI Reply Action Extractor（ACTION-002）。

从角色回复提取候选世界动作：只产出 candidate，绝不修改 World。
确定性词表通道（默认）；零写库、零 LLM。
"""

import logging
import re
from typing import Any

from app.character.asuna.narrative import (
    NARRATIVE_ACTION_VERBS,
    NARRATIVE_NOISE_PATTERNS,
    NARRATIVE_QUANTITY_WORDS,
)
from app.character.asuna.world import LOCATION_ALIASES
from app.core.settings import get_settings
from app.models.character_action import (
    ExtractionResult,
    TargetRef,
    TurnRef,
    WorldAction,
    WorldActionStatus,
    build_dedupe_key,
)
from app.services.world.locations import resolve_location_alias

logger = logging.getLogger(__name__)

_ARABIC_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")
_CHINESE_QUANTITY_RE = re.compile(
    "([一二两三四五六七八九十半]+)"
)

_SENTENCE_SPLIT_RE = re.compile(r"[。！\n；，]")


def _is_noise(text: str) -> bool:
    for pattern in NARRATIVE_NOISE_PATTERNS:
        if pattern in text:
            return True
    return False


def _parse_chinese_quantity(text: str) -> float | None:
    match = _CHINESE_QUANTITY_RE.search(text)
    if match:
        word = match.group(1)
        if word in NARRATIVE_QUANTITY_WORDS:
            return NARRATIVE_QUANTITY_WORDS[word]
    return None


def _parse_quantity(text: str) -> float | None:
    chinese = _parse_chinese_quantity(text)
    if chinese is not None:
        return chinese
    match = _ARABIC_NUM_RE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _find_verb_match(
    sentence: str,
) -> tuple[str, str] | None:
    best: tuple[str, str] | None = None
    for action_type, verbs in NARRATIVE_ACTION_VERBS.items():
        for verb in verbs:
            if verb in sentence:
                if best is None or len(verb) > len(best[1]):
                    best = (action_type, verb)
    return best


def _extract_object_name(
    sentence: str,
    verb: str,
    action_type: str,
    known_names: set[str],
) -> str | None:
    verb_idx = sentence.find(verb)
    if verb_idx < 0:
        return None
    after_verb = sentence[verb_idx + len(verb):]

    if action_type == "MOVE":
        move_match = re.search(r"到(.+?)(?:了|上|里|$)", after_verb)
        if move_match:
            return None

    for name in sorted(known_names, key=len, reverse=True):
        if name in sentence:
            return name

    if action_type == "CREATE":
        qty = _parse_quantity(after_verb)
        if qty is not None:
            after_qty = after_verb
            for pattern in [_CHINESE_QUANTITY_RE, _ARABIC_NUM_RE]:
                m = pattern.search(after_qty)
                if m:
                    after_qty = after_qty[m.end():]
                    break
            candidate = after_qty.strip("了的碗杯份个 ")
            if 1 <= len(candidate) <= 10:
                return candidate
        else:
            candidate = after_verb.strip("了的碗杯份个 ")
            if 1 <= len(candidate) <= 10:
                return candidate

    return None


def _extract_move_location(
    sentence: str,
    verb: str,
) -> str | None:
    verb_idx = sentence.find(verb)
    if verb_idx < 0:
        return None
    after_verb = sentence[verb_idx + len(verb):]
    after_verb = after_verb.rstrip("。！？\n；，")
    location = resolve_location_alias(after_verb)
    if location:
        return location
    for alias in sorted(LOCATION_ALIASES, key=len, reverse=True):
        if alias in sentence:
            return LOCATION_ALIASES[alias]
    return None


def _extract_consume_quantity(
    sentence: str,
    verb: str,
) -> float:
    verb_idx = sentence.find(verb)
    if verb_idx < 0:
        return 1.0
    before_verb = sentence[:verb_idx]
    after_verb = sentence[verb_idx + len(verb):]
    combined = before_verb + after_verb
    qty = _parse_quantity(combined)
    return qty if qty is not None else 1.0


def extract_actions(
    ai_reply: str,
    known_object_names: set[str] | None = None,
    current_location: str | None = None,
    turn_ref: TurnRef | None = None,
    world_notes: list[str] | None = None,
) -> ExtractionResult:
    settings = get_settings()
    if not settings.world_enabled:
        return ExtractionResult(skipped_reason="world_disabled")
    if not ai_reply or not isinstance(ai_reply, str):
        return ExtractionResult(skipped_reason="empty_reply")

    known_names = known_object_names or set()
    notes: list[str] = []
    candidates: list[WorldAction] = []

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(ai_reply) if s.strip()]

    if turn_ref is None:
        turn_ref = TurnRef(session_id="", turn_id="", ordinal=0)

    ordinal = 0
    seen_dedupes: set[str] = set()

    for sentence in sentences:
        if _is_noise(sentence):
            continue

        match = _find_verb_match(sentence)
        if match is None:
            continue

        action_type, verb = match

        if action_type == "MOVE":
            location_id = _extract_move_location(sentence, verb)
            obj_name = _extract_object_name(sentence, verb, action_type, known_names)
            if obj_name is None:
                continue
            target = TargetRef(name=obj_name, location_id=location_id)
            quantity = None
        elif action_type == "CONSUME":
            obj_name = _extract_object_name(sentence, verb, action_type, known_names)
            if obj_name is None:
                continue
            quantity = _extract_consume_quantity(sentence, verb)
            target = TargetRef(name=obj_name)
        elif action_type == "CREATE":
            obj_name = _extract_object_name(sentence, verb, action_type, known_names)
            if obj_name is None:
                continue
            quantity = _parse_quantity(sentence)
            if quantity is None:
                quantity = 1.0
            target = TargetRef(name=obj_name)
        else:
            continue

        start_idx = ai_reply.find(sentence)
        evidence = sentence[:50]

        dedupe = build_dedupe_key(
            action_type,
            target.name,
            quantity,
            turn_ref.session_id,
            turn_ref.turn_id,
            ordinal,
        )

        if dedupe in seen_dedupes:
            continue
        seen_dedupes.add(dedupe)

        action = WorldAction(
            action_type=action_type,
            target=target,
            quantity=quantity,
            source="character_reply",
            metadata={
                "evidence": evidence,
                "span": [start_idx, start_idx + len(sentence)] if start_idx >= 0 else [0, 0],
                "channel": "lexicon",
                "confidence": "high",
            },
            status=WorldActionStatus.CANDIDATE,
            dedupe_key=dedupe,
            turn_ref=TurnRef(
                session_id=turn_ref.session_id,
                turn_id=turn_ref.turn_id,
                ordinal=ordinal,
            ),
        )
        candidates.append(action)
        ordinal += 1

    return ExtractionResult(
        candidates=candidates,
        channel="lexicon",
        notes=notes,
    )
