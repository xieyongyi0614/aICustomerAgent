"""人设资产只读解析（R-8 / M-2）：Runtime 按 `character_id` 取能力映射，零 `character.<id>` 硬编码。"""

from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any

DEFAULT_CHARACTER_ID = "asuna"


@lru_cache(maxsize=8)
def _action_module(character_id: str) -> Any:
    return importlib.import_module(f"app.character.{character_id}.action")


def action_tool_map(character_id: str = DEFAULT_CHARACTER_ID) -> dict[str, tuple[str, ...]]:
    return dict(_action_module(character_id).ACTION_TOOL_MAP)


def required_params(character_id: str = DEFAULT_CHARACTER_ID) -> dict[str, tuple[str, ...]]:
    return dict(_action_module(character_id).REQUIRED_PARAMS)


def action_capability_map(character_id: str = DEFAULT_CHARACTER_ID) -> dict[str, str]:
    return dict(_action_module(character_id).ACTION_CAPABILITY_MAP)
