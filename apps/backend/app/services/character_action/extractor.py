"""AI Reply Action Extractor（ACTION-002）。

从角色回复提取候选世界动作：只产出 candidate，绝不修改 World。
确定性词表通道（默认）；零写库、零 LLM。
"""

import logging
import re

from app.character.asuna.narrative import (
    NARRATIVE_ACTION_VERBS,
    NARRATIVE_NOISE_PATTERNS,
    NARRATIVE_OBJECT_NOUNS,
    NARRATIVE_QUANTITY_WORDS,
)
from app.character.asuna.world import LOCATION_ALIASES, OBJECT_CREATION_HINTS
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
    "([一二两俩三四五六七八九十半]+)"
)

# 取出/拿出/拿走/拿了：属于「占取」语义——只有显式数量才按消耗记账，
# 无量词时只算移动（宁可不扣，不造账）。
_APPROPRIATION_VERBS = frozenset({"拿出", "取出", "拿走", "拿了"})

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


def _find_verb_matches(sentence: str) -> list[tuple[str, str, int]]:
    """按出现顺序返回不重叠动词；同位取最长。"""
    raw: list[tuple[str, str, int]] = []
    for action_type, verbs in NARRATIVE_ACTION_VERBS.items():
        for verb in verbs:
            idx = sentence.find(verb)
            if idx >= 0:
                raw.append((action_type, verb, idx))
    raw.sort(key=lambda item: (item[2], -len(item[1])))
    selected: list[tuple[str, str, int]] = []
    last_end = -1
    for action_type, verb, idx in raw:
        end = idx + len(verb)
        if idx < last_end:
            continue
        selected.append((action_type, verb, idx))
        last_end = end
    return selected


def _is_creatable_noun(name: str, known_names: set[str]) -> bool:
    return (
        name in known_names
        or name in NARRATIVE_OBJECT_NOUNS
        or name in OBJECT_CREATION_HINTS
    )


def _infer_single_known_name(text: str, known_names: set[str]) -> str | None:
    """从文本里唯一推定的库存名（字面子串或单字命中）；候选多于一个则不猜。"""
    if not text or not known_names:
        return None
    hits: set[str] = set()
    text_chars = set(text)
    for name in known_names:
        if name in text:
            hits.add(name)
            continue
        if set(name) & text_chars:
            hits.add(name)
    return hits.pop() if len(hits) == 1 else None


def _extract_object_name(
    clause: str,
    verb: str,
    action_type: str,
    known_names: set[str],
    context: str = "",
) -> str | None:
    verb_idx = clause.find(verb)
    if verb_idx < 0:
        return None
    after_verb = clause[verb_idx + len(verb):]

    for name in sorted(known_names, key=len, reverse=True):
        if name in clause:
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
            candidate = after_qty.strip("了的碗杯份个把 ")
        else:
            candidate = after_verb.strip("了的碗杯份个把 ")
        if 1 <= len(candidate) <= 10 and _is_creatable_noun(candidate, known_names):
            return candidate

    if action_type != "CREATE" and context:
        inferred = _infer_single_known_name(context, known_names)
        if inferred is not None:
            return inferred

    return None


def _extract_move_location(
    clause: str,
    verb: str,
) -> str | None:
    verb_idx = clause.find(verb)
    if verb_idx < 0:
        return None
    after_verb = clause[verb_idx + len(verb):]
    after_verb = after_verb.rstrip("。！？\n；，")
    location = resolve_location_alias(after_verb)
    if location:
        return location
    for alias in sorted(LOCATION_ALIASES, key=len, reverse=True):
        if alias in clause:
            return LOCATION_ALIASES[alias]
    return None


def _extract_consume_quantity(
    clause: str,
    verb: str,
) -> float:
    verb_idx = clause.find(verb)
    if verb_idx < 0:
        return 1.0
    before_verb = clause[:verb_idx]
    after_verb = clause[verb_idx + len(verb):]
    combined = before_verb + after_verb
    qty = _parse_quantity(combined)
    return qty if qty is not None else 1.0


def _extract_explicit_quantity(
    clause: str,
    verb: str,
) -> float | None:
    """返回显式数量；无量词时返回 None（占取动词必须显式才记账）。"""
    verb_idx = clause.find(verb)
    if verb_idx < 0:
        return None
    combined = clause[:verb_idx] + clause[verb_idx + len(verb):]
    if _parse_quantity(combined) is None:
        return None
    return _extract_consume_quantity(clause, verb)


def _build_candidate(
    action_type: str,
    clause: str,
    verb: str,
    known_names: set[str],
    evidence: str,
    start_idx: int,
    turn_ref: TurnRef,
    ordinal: int,
    context: str = "",
) -> tuple[WorldAction, float | None] | None:
    if action_type == "MOVE":
        location_id = _extract_move_location(clause, verb)
        obj_name = _extract_object_name(clause, verb, action_type, known_names, context)
        if obj_name is None:
            return None
        target = TargetRef(name=obj_name, location_id=location_id)
        quantity = None
    elif action_type == "CONSUME":
        obj_name = _extract_object_name(clause, verb, action_type, known_names, context)
        if obj_name is None:
            return None
        if verb in _APPROPRIATION_VERBS:
            explicit = _extract_explicit_quantity(clause, verb)
            if explicit is None:
                return None
            quantity = explicit
        else:
            quantity = _extract_consume_quantity(clause, verb)
        target = TargetRef(name=obj_name)
    elif action_type == "CREATE":
        obj_name = _extract_object_name(clause, verb, action_type, known_names, context)
        if obj_name is None:
            return None
        quantity = _parse_quantity(clause)
        if quantity is None:
            quantity = 1.0
        target = TargetRef(name=obj_name)
    else:
        return None

    action = WorldAction(
        action_type=action_type,
        target=target,
        quantity=quantity,
        source="character_reply",
        metadata={
            "evidence": evidence[:50],
            "span": [start_idx, start_idx + len(evidence)] if start_idx >= 0 else [0, 0],
            "channel": "lexicon",
            "confidence": "high",
            "verb": verb,
        },
        status=WorldActionStatus.CANDIDATE,
        dedupe_key=build_dedupe_key(
            action_type,
            target.name,
            quantity,
            turn_ref.session_id,
            turn_ref.turn_id,
            ordinal,
        ),
        turn_ref=TurnRef(
            session_id=turn_ref.session_id,
            turn_id=turn_ref.turn_id,
            ordinal=ordinal,
        ),
    )
    return action, quantity


def extract_actions(
    ai_reply: str,
    known_object_names: set[str] | None = None,
    turn_ref: TurnRef | None = None,
    context_text: str = "",
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

        matches = _find_verb_matches(sentence)
        for i, (action_type, verb, idx) in enumerate(matches):
            prev_end = 0 if i == 0 else matches[i - 1][2] + len(matches[i - 1][1])
            next_start = len(sentence) if i + 1 >= len(matches) else matches[i + 1][2]
            clause = sentence[prev_end:next_start]
            built = _build_candidate(
                action_type,
                clause,
                verb,
                known_names,
                sentence,
                ai_reply.find(sentence),
                turn_ref,
                ordinal,
                context=context_text,
            )
            if built is None:
                continue
            action, _qty = built
            if action.dedupe_key in seen_dedupes:
                continue
            seen_dedupes.add(action.dedupe_key)
            candidates.append(action)
            ordinal += 1

    return ExtractionResult(
        candidates=candidates,
        channel="lexicon",
        notes=notes,
    )
