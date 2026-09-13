"""Agent Runtime 域设置（V2.1.0 AGENT-001）：统一 Run 模型总闸、前台收编、Gateway 旋钮。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class AgentRuntimeSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    v21_agent_runtime_enabled: bool = False
    v21_unified_run_enabled: bool = False
    v21_foreground_run_llm_budget: int = 8
    v21_foreground_gateway_enforced: bool = False
    v21_light_llm_profile: str = ""
    v21_event_escalation_types: str = ""
