"""services 包门面：旧顶层模块名 → 现行路径的 PEP 562 惰性映射。

本门面只做旧名惰性兼容（`from app.services import <旧名>` 仍可用），不急切
导入任何业务模块；新代码一律 import 真实路径。
"""

from importlib import import_module

_LEGACY = {
    "agent_evaluation": "app.services.evaluation.agent",
    "analytics": "app.services.observability.analytics",
    "autonomy_policy": "app.engines.autonomy",
    "behavior_engine": "app.engines.behavior",
    "channel_identity_service": "app.services.identity.channel",
    "character_assets": "app.engines.character",
    "context_builder": "app.services.conversation.context",
    "conversation_service": "app.services.conversation.service",
    "decision_pipeline": "app.engines.decision",
    "domain_ledger": "app.services.ledger.domain",
    "evolution": "app.services.development.evolution",
    "evaluation_context": "app.services.evaluation.context",
    "evaluation_engine": "app.services.evaluation.engine",
    "evaluation_rules": "app.services.evaluation.rules",
    "feishu_dedupe_service": "app.services.delivery.dedupe",
    "feishu_delivery_ledger_service": "app.services.delivery.ledger",
    "goal_alignment": "app.engines.goal_alignment",
    "goal_arbitration": "app.services.goal.arbitration",
    "goal_execution": "app.services.goal.execution",
    "goal_observation": "app.services.goal.observation",
    "goal_planning": "app.services.goal.planning",
    "goal_service": "app.services.goal.service",
    "goal_stack": "app.services.goal.stack",
    "habit_runtime": "app.engines.habit",
    "history_service": "app.services.conversation.history",
    "intention_policy": "app.services.goal.intention",
    "life_loop_budget": "app.services.life.budget",
    "llm_budget_gate": "app.services.life.gate",
    "memory_conflict": "app.engines.memory_conflict",
    "memory_policy": "app.engines.memory_policy",
    "memory_refs": "app.services.memory.refs",
    "mode_service": "app.engines.mode",
    "offline_evaluator": "app.services.evaluation.offline",
    "outbox_service": "app.services.delivery.outbox",
    "proactive_delivery": "app.services.delivery.outbound",
    "proactive_executor": "app.services.autonomy.executor",
    "relationship_audit": "app.services.relationship.audit",
    "relationship_conflict": "app.engines.relationship_conflict",
    "relationship_evaluation": "app.services.relationship.evaluation",
    "relationship_evolution": "app.engines.relationship_evolution",
    "relationship_milestone": "app.services.relationship.milestone",
    "relationship_narrative": "app.services.relationship.narrative",
    "relationship_patterns": "app.services.relationship.patterns",
    "relationship_shared": "app.services.relationship.shared",
    "relationship_signal": "app.engines.relationship_signal",
    "scene_service": "app.services.conversation.scene",
    "state_engine": "app.engines.state",
    "state_service": "app.services.conversation.state",
    "summary_service": "app.services.conversation.summary",
    "tasks": "app.services.life.tasks",
    "trace_collector": "app.services.observability.collector",
    "trigger_evaluator": "app.services.autonomy.trigger",
    "weather": "app.services.briefing.weather",
}


def __getattr__(name: str):
    target = _LEGACY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(target)
    globals()[name] = module
    return module


def __dir__():
    return sorted(set(globals()) | set(_LEGACY))
