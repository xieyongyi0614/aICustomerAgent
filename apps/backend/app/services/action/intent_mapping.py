"""Intention → ActionIntent 域映射（R-8 / M-1）。

Runtime Act 段只调用；映射/参数完备性/去重键策略属 Action 域语义。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.models.action import ActionIntent
from app.services import character_assets

logger = logging.getLogger(__name__)


def action_type_for_tool(
    tool_id: str | None, *, character_id: str = character_assets.DEFAULT_CHARACTER_ID
) -> str | None:
    if not tool_id:
        return None
    for action_type, tool_ids in character_assets.action_tool_map(character_id).items():
        if tool_id in tool_ids:
            return action_type
    return None


def missing_params(
    action_type: str,
    params: Mapping[str, Any],
    *,
    character_id: str = character_assets.DEFAULT_CHARACTER_ID,
) -> list[str]:
    required = character_assets.required_params(character_id).get(action_type, ())
    return [name for name in required if not params.get(name)]


def dedupe_key(
    goal_id: str | None,
    intention_text: str | None,
    action_type: str,
    session_id: str | None,
) -> str:
    basis = goal_id or intention_text or session_id or ""
    return f"act:{action_type}:{basis}"


def winning_candidate(intention: Any) -> Mapping[str, Any] | None:
    audit = getattr(intention, "audit", None) or {}
    for candidate in audit.get("candidates") or []:
        if candidate.get("won"):
            return candidate
    return None


def intent_to_action_intent(
    intention: Any,
    *,
    session_id: str | None,
    goal_id: str | None,
    character_id: str | None = None,
) -> ActionIntent | None:
    """`Intention` → `ActionIntent`（只映射，不做「做不做」判断）。"""
    character_id = character_id or character_assets.DEFAULT_CHARACTER_ID
    candidate = winning_candidate(intention)
    if candidate is None:
        return None
    action_type = action_type_for_tool(
        candidate.get("tool_id"), character_id=character_id
    )
    if action_type is None:
        return None
    params = dict(candidate.get("params") or {})
    missing = missing_params(action_type, params, character_id=character_id)
    return ActionIntent(
        action_type=action_type,  # type: ignore[arg-type]
        confidence="ambiguous" if missing else "confident",
        params=params,
        missing_params=missing,
        evidence=str(getattr(intention, "intention", None) or ""),
        dedupe_key=dedupe_key(
            goal_id or getattr(intention, "goal_id", None),
            getattr(intention, "intention", None),
            action_type,
            session_id,
        ),
        trigger_source="lexicon",
    )
