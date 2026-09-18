"""应用设置：按子系统拆分的领域设置组合（保持平铺字段名不变）。

- 各领域字段/校验/解析方法见同目录领域模块；
- `Settings` 只做组合与统一入口，跨域校验沿用各领域 validator；
- 环境变量名不变（.env / docker-compose 无需任何改动）。
"""

import os
import re
from collections.abc import Mapping
from functools import lru_cache

from pydantic_settings import BaseSettings

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, STAGE_KEYS, SettingsError
from app.core.settings.action import ActionSettings
from app.core.settings.action_execution import ActionExecutionSettings
from app.core.settings.agent_runtime import AgentRuntimeSettings
from app.core.settings.autonomy import AutonomySettings
from app.core.settings.autonomy_advanced import AutonomyAdvancedSettings
from app.core.settings.character import CharacterSettings
from app.core.settings.database import DatabaseSettings
from app.core.settings.evaluation import EvaluationSettings
from app.core.settings.experience import ExperienceSettings
from app.core.settings.feishu import FeishuSettings
from app.core.settings.goal import GoalSettings
from app.core.settings.life_loop import LifeLoopSettings
from app.core.settings.llm import LlmProfile, LlmSettings
from app.core.settings.memory import MemorySettings
from app.core.settings.observability import ObservabilitySettings
from app.core.settings.pipeline import PipelineSettings
from app.core.settings.plan import PlanSettings
from app.core.settings.reflection_development import (
    DevelopmentSettings,
    ReflectionSettings,
    RelationshipEvolvedSettings,
)
from app.core.settings.relationship import RelationshipSettings
from app.core.settings.tool import ToolSettings
from app.core.settings.world import WorldSettings
from app.core.settings.world_simulation import WorldSimulationSettings


class Settings(
    LlmSettings,
    DatabaseSettings,
    PipelineSettings,
    CharacterSettings,
    MemorySettings,
    ReflectionSettings,
    DevelopmentSettings,
    RelationshipEvolvedSettings,
    RelationshipSettings,
    GoalSettings,
    AutonomySettings,
    LifeLoopSettings,
    AutonomyAdvancedSettings,
    AgentRuntimeSettings,
    ActionSettings,
    ActionExecutionSettings,
    EvaluationSettings,
    ExperienceSettings,
    FeishuSettings,
    ObservabilitySettings,
    WorldSettings,
    WorldSimulationSettings,
    ToolSettings,
    PlanSettings,
    BaseSettings,
):
    model_config = DOMAIN_MODEL_CONFIG


__all__ = [
    "STAGE_KEYS",
    "Settings",
    "SettingsError",
    "LlmProfile",
    "get_settings",
    "unknown_versioned_env_keys",
]


_VERSIONED_ENV_KEY = re.compile(r"^V[0-9]+_")


def unknown_versioned_env_keys(environ: Mapping[str, str] | None = None) -> list[str]:
    """形如 `V2_*` / `V21_*` / … 但不对应任何 settings 字段的环境变量。

    环境变量名即字段名大写（无 alias 层），故字段改名会连带改 env 名；旧名随后被
    `extra="ignore"` 静默吞掉——服务照常启动、闸门却回落到代码默认值，日志中无任何
    痕迹。启动边界调用本函数，可把这种静默失效变成显式告警。
    """
    source = os.environ if environ is None else environ
    known = {name.upper() for name in Settings.model_fields}
    return sorted(
        key
        for key in source
        if _VERSIONED_ENV_KEY.match(key.upper()) and key.upper() not in known
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
