"""services 域间边界基线（T-32）——守卫的「既有违规」豁免清单。

## 为什么有基线

T-10（2026-10-09）在 `AGENTS.md` 立规：`services/<domain>` 不得直接 import
另一个域的内部模块，只能经契约面（`port.py` / `contracts.py` / `engine_port.py`）。

立规时仓库已积累 **232 条**跨域内部依赖（58 个域对，最大为 `planning`→`tool` 40 条、
`tool`↔`action` 双向 35 条）。一次清零需改动大量冻结面与测试契约，风险过高，
故采用**渐进策略**：把现状冻结成本清单，守卫只对**新增**违规 fail-closed。

## 数据结构

`(源文件相对路径, 被导入的目标模块)`，**不含行号** —— 这样在源文件内新增/删除
无关代码导致行号漂移时不会假红。

## 维护规则

- **不得**为了「让测试变绿」而把新违规塞进本清单。新增依赖应改走契约面。
- 修好一处违规 → 从清单删除对应项（守卫会以「基线已消失」提示，便于收紧）。
- 确需新增跨域调用 → 优先复用既有契约面；确需新面时在目标域新增
  `port.py` / `contracts.py`，而不是把消费方直连写进基线。
- 清单整体重采：`python -c "from tests.support.domain_boundary import scan; [print(v.render()) for v in scan()]"`

## 已知的域对规模（2026-10-09 采）

`planning`→`tool` 40 ｜ `tool`→`action` 19 ｜ `action`→`tool` 16 ｜ `action`→`ledger` 9
｜ `car`→`ledger` 8 ｜ `ledger`→`governance` 8 ｜ `relationship`→`evaluation` 8
｜ `planning`→`world` 7 ｜ 其余 50 对 1~6 条。
"""

BASELINE_VIOLATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # --- app/services/action/capabilities/__init__.py
        ("app/services/action/capabilities/__init__.py", "app.services.tool.channel_tools"),
        ("app/services/action/capabilities/__init__.py", "app.services.tool.channel_tools.channel_tools_enabled"),
        ("app/services/action/capabilities/__init__.py", "app.services.tool.channel_tools.get_channel_capability"),
        ("app/services/action/capabilities/__init__.py", "app.services.tool.ext_api"),
        ("app/services/action/capabilities/__init__.py", "app.services.tool.ext_api.get_external_api_capability"),
        # --- app/services/action/capabilities/ledger.py
        ("app/services/action/capabilities/ledger.py", "app.services.ledger"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.correction"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.correction.cancel_entry"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.correction.revise_entry"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.ensure_user_bootstrap"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.query"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.query.Period"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.query.summary"),
        ("app/services/action/capabilities/ledger.py", "app.services.ledger.record_entry"),
        # --- app/services/action/capabilities/world_action.py
        ("app/services/action/capabilities/world_action.py", "app.services.world.locations"),
        ("app/services/action/capabilities/world_action.py", "app.services.world.locations.resolve_location_alias"),
        # --- app/services/action/memory_bridge.py
        ("app/services/action/memory_bridge.py", "app.services.memory.ingest"),
        ("app/services/action/memory_bridge.py", "app.services.tool.memory_policy"),
        ("app/services/action/memory_bridge.py", "app.services.tool.registry"),
        ("app/services/action/memory_bridge.py", "app.services.tool.registry.get_tool_registry"),
        # --- app/services/action/planner.py
        ("app/services/action/planner.py", "app.services.tool.context"),
        ("app/services/action/planner.py", "app.services.tool.context.DEFAULT_RUN_KIND"),
        ("app/services/action/planner.py", "app.services.tool.context.ToolContext"),
        ("app/services/action/planner.py", "app.services.tool.registry"),
        ("app/services/action/planner.py", "app.services.tool.registry.get_tool_registry"),
        ("app/services/action/planner.py", "app.services.tool.surface"),
        ("app/services/action/planner.py", "app.services.tool.surface.ToolSelector"),
        ("app/services/action/planner.py", "app.services.tool.surface.ToolSurfaceResolver"),
        # --- app/services/action/relationship_bridge.py
        ("app/services/action/relationship_bridge.py", "app.services.conversation.state"),
        ("app/services/action/relationship_bridge.py", "app.services.conversation.state._day_impact_totals"),
        # --- app/services/autonomy/executor.py
        ("app/services/autonomy/executor.py", "app.services.conversation.service"),
        ("app/services/autonomy/executor.py", "app.services.delivery.outbound"),
        ("app/services/autonomy/executor.py", "app.services.evaluation.engine"),
        ("app/services/autonomy/executor.py", "app.services.evaluation.engine.schedule_proactive_evaluation"),
        ("app/services/autonomy/executor.py", "app.services.observability.collector"),
        ("app/services/autonomy/executor.py", "app.services.observability.collector.TurnTraceSession"),
        # --- app/services/briefing/compose.py
        ("app/services/briefing/compose.py", "app.services.car"),
        ("app/services/briefing/compose.py", "app.services.car.service"),
        ("app/services/briefing/compose.py", "app.services.ledger"),
        ("app/services/briefing/compose.py", "app.services.ledger.query"),
        ("app/services/briefing/compose.py", "app.services.life.tasks"),
        # --- app/services/car/aggregate.py
        ("app/services/car/aggregate.py", "app.services.ledger"),
        ("app/services/car/aggregate.py", "app.services.ledger.query"),
        # --- app/services/car/entries.py
        ("app/services/car/entries.py", "app.services.ledger"),
        ("app/services/car/entries.py", "app.services.ledger.category"),
        ("app/services/car/entries.py", "app.services.ledger.correction"),
        ("app/services/car/entries.py", "app.services.ledger.service"),
        # --- app/services/car/service.py
        ("app/services/car/service.py", "app.services.ledger"),
        ("app/services/car/service.py", "app.services.ledger.query"),
        # --- app/services/character_action/extractor.py
        ("app/services/character_action/extractor.py", "app.services.world.locations"),
        ("app/services/character_action/extractor.py", "app.services.world.locations.resolve_location_alias"),
        # --- app/services/conversation/context.py
        ("app/services/conversation/context.py", "app.services.development.aggregate"),
        ("app/services/conversation/context.py", "app.services.goal.service"),
        ("app/services/conversation/context.py", "app.services.memory.retriever"),
        ("app/services/conversation/context.py", "app.services.reflection.lifecycle"),
        ("app/services/conversation/context.py", "app.services.relationship.patterns"),
        ("app/services/conversation/context.py", "app.services.relationship.shared"),
        # --- app/services/conversation/state.py
        ("app/services/conversation/state.py", "app.services.relationship.milestone"),
        # --- app/services/development/attribution.py
        ("app/services/development/attribution.py", "app.services.reflection.attribution"),
        # --- app/services/development/audit.py
        ("app/services/development/audit.py", "app.services.memory.job_worker"),
        ("app/services/development/audit.py", "app.services.reflection.lifecycle"),
        # --- app/services/development/evaluation.py
        ("app/services/development/evaluation.py", "app.services.evaluation.context"),
        ("app/services/development/evaluation.py", "app.services.evaluation.context.DevelopmentChangeRef"),
        ("app/services/development/evaluation.py", "app.services.evaluation.context.DevelopmentSlice"),
        ("app/services/development/evaluation.py", "app.services.evaluation.context.DevelopmentStateRef"),
        ("app/services/development/evaluation.py", "app.services.memory.evaluator"),
        ("app/services/development/evaluation.py", "app.services.memory.ingest"),
        ("app/services/development/evaluation.py", "app.services.reflection.lifecycle"),
        ("app/services/development/evaluation.py", "app.services.reflection.reflector"),
        # --- app/services/development/policy.py
        ("app/services/development/policy.py", "app.services.memory.job_worker"),
        ("app/services/development/policy.py", "app.services.reflection.lifecycle"),
        # --- app/services/evaluation/agent.py
        ("app/services/evaluation/agent.py", "app.services.conversation.state"),
        ("app/services/evaluation/agent.py", "app.services.reflection.triggers"),
        # --- app/services/evaluation/context/collectors.py
        ("app/services/evaluation/context/collectors.py", "app.services.conversation.service"),
        ("app/services/evaluation/context/collectors.py", "app.services.conversation.state"),
        # --- app/services/evaluation/offline.py
        ("app/services/evaluation/offline.py", "app.services.development.evaluation"),
        ("app/services/evaluation/offline.py", "app.services.development.evaluation.build_db_report"),
        ("app/services/evaluation/offline.py", "app.services.reflection.evaluation"),
        ("app/services/evaluation/offline.py", "app.services.reflection.evaluation.build_db_report"),
        ("app/services/evaluation/offline.py", "app.services.relationship.evaluation"),
        ("app/services/evaluation/offline.py", "app.services.relationship.evaluation.build_db_report"),
        # --- app/services/evaluation/rules/reflection.py
        ("app/services/evaluation/rules/reflection.py", "app.services.reflection.reflector"),
        ("app/services/evaluation/rules/reflection.py", "app.services.reflection.reflector.confidence_ceiling"),
        # --- app/services/goal/arbitration.py
        ("app/services/goal/arbitration.py", "app.services.conversation.state"),
        ("app/services/goal/arbitration.py", "app.services.development.aggregate"),
        ("app/services/goal/arbitration.py", "app.services.world.event_bridge"),
        # --- app/services/goal/observation.py
        ("app/services/goal/observation.py", "app.services.memory.ingest"),
        ("app/services/goal/observation.py", "app.services.world.event_bridge"),
        # --- app/services/goal/planning.py
        ("app/services/goal/planning.py", "app.services.development.aggregate"),
        ("app/services/goal/planning.py", "app.services.memory.job_worker"),
        ("app/services/goal/planning.py", "app.services.observability.collector"),
        ("app/services/goal/planning.py", "app.services.observability.collector.TurnTraceSession"),
        ("app/services/goal/planning.py", "app.services.relationship.patterns"),
        # --- app/services/goal/stack.py
        ("app/services/goal/stack.py", "app.services.conversation.state"),
        ("app/services/goal/stack.py", "app.services.development.evolution"),
        # --- app/services/identity/verification.py
        ("app/services/identity/verification.py", "app.services.email.sender"),
        ("app/services/identity/verification.py", "app.services.email.sender.EmailContent"),
        ("app/services/identity/verification.py", "app.services.email.sender.EmailSendFailed"),
        ("app/services/identity/verification.py", "app.services.email.sender.EmailSender"),
        ("app/services/identity/verification.py", "app.services.email.sender.get_email_sender"),
        # --- app/services/ledger/alert.py
        ("app/services/ledger/alert.py", "app.services.delivery.outbound"),
        # --- app/services/ledger/budget.py
        ("app/services/ledger/budget.py", "app.services.planning.goal_contract"),
        ("app/services/ledger/budget.py", "app.services.planning.goal_contract.PLANNING_FAILURE_REASON_BUDGET_EXHAUSTED"),
        ("app/services/ledger/budget.py", "app.services.planning.goal_contract.PLANNING_FAILURE_REASON_OVER_BUDGET"),
        # --- app/services/ledger/digest.py
        ("app/services/ledger/digest.py", "app.services.delivery.outbound"),
        # --- app/services/ledger/memory_bridge.py
        ("app/services/ledger/memory_bridge.py", "app.services.governance.prompt_guard"),
        ("app/services/ledger/memory_bridge.py", "app.services.governance.prompt_guard.FinancialDetailInPrompt"),
        ("app/services/ledger/memory_bridge.py", "app.services.governance.prompt_guard.assert_no_financial_detail"),
        ("app/services/ledger/memory_bridge.py", "app.services.memory.ingest"),
        # --- app/services/ledger/service.py
        ("app/services/ledger/service.py", "app.services.governance.core"),
        ("app/services/ledger/service.py", "app.services.governance.core.DomainHandlers"),
        ("app/services/ledger/service.py", "app.services.governance.core.ProvenanceRef"),
        ("app/services/ledger/service.py", "app.services.governance.core.record_provenance"),
        ("app/services/ledger/service.py", "app.services.governance.core.register_domain"),
        # --- app/services/memory/ingest.py
        ("app/services/memory/ingest.py", "app.services.action.memory_bridge"),
        ("app/services/memory/ingest.py", "app.services.action.memory_bridge.has_memory_effect"),
        ("app/services/memory/ingest.py", "app.services.action.memory_bridge.to_memory_candidates"),
        ("app/services/memory/ingest.py", "app.services.relationship.milestone"),
        ("app/services/memory/ingest.py", "app.services.relationship.milestone.MILESTONES"),
        # --- app/services/planning/context.py
        ("app/services/planning/context.py", "app.services.memory.retriever"),
        ("app/services/planning/context.py", "app.services.reflection.lifecycle"),
        ("app/services/planning/context.py", "app.services.reflection.tool_feed"),
        ("app/services/planning/context.py", "app.services.tool.context"),
        ("app/services/planning/context.py", "app.services.tool.context.ToolContext"),
        ("app/services/planning/context.py", "app.services.tool.registry"),
        ("app/services/planning/context.py", "app.services.tool.registry.get_tool_registry"),
        ("app/services/planning/context.py", "app.services.tool.surface"),
        ("app/services/planning/context.py", "app.services.tool.surface.ToolSurfaceResolver"),
        ("app/services/planning/context.py", "app.services.tool.world_context"),
        ("app/services/planning/context.py", "app.services.tool.world_context.WorldContextBuilder"),
        ("app/services/planning/context.py", "app.services.tool.world_context.build_tool_context"),
        ("app/services/planning/context.py", "app.services.world.event_impact"),
        ("app/services/planning/context.py", "app.services.world.locations"),
        ("app/services/planning/context.py", "app.services.world.locations.build_location_context"),
        ("app/services/planning/context.py", "app.services.world.time_provider"),
        ("app/services/planning/context.py", "app.services.world.time_provider.TimeProvider"),
        ("app/services/planning/context.py", "app.services.world.world_brief"),
        # --- app/services/planning/decompose/__init__.py
        ("app/services/planning/decompose/__init__.py", "app.services.tool.surface"),
        ("app/services/planning/decompose/__init__.py", "app.services.tool.surface.ToolSelector"),
        # --- app/services/planning/decompose/constants.py
        ("app/services/planning/decompose/constants.py", "app.services.goal.planning"),
        # --- app/services/planning/decompose/decomposer.py
        ("app/services/planning/decompose/decomposer.py", "app.services.goal.planning"),
        ("app/services/planning/decompose/decomposer.py", "app.services.tool.registry"),
        ("app/services/planning/decompose/decomposer.py", "app.services.tool.registry.ToolRegistry"),
        ("app/services/planning/decompose/decomposer.py", "app.services.tool.registry.get_tool_registry"),
        ("app/services/planning/decompose/decomposer.py", "app.services.tool.surface"),
        ("app/services/planning/decompose/decomposer.py", "app.services.tool.surface.ToolSelector"),
        # --- app/services/planning/decompose/validator.py
        ("app/services/planning/decompose/validator.py", "app.services.tool.registry"),
        ("app/services/planning/decompose/validator.py", "app.services.tool.registry.TOOL_ID_PATTERN"),
        # --- app/services/planning/engine.py
        ("app/services/planning/engine.py", "app.services.goal.planning"),
        ("app/services/planning/engine.py", "app.services.life.budget"),
        ("app/services/planning/engine.py", "app.services.tool.registry"),
        ("app/services/planning/engine.py", "app.services.tool.registry.ToolRegistry"),
        ("app/services/planning/engine.py", "app.services.tool.registry.get_tool_registry"),
        # --- app/services/planning/executor_bridge.py
        ("app/services/planning/executor_bridge.py", "app.services.action.integration"),
        ("app/services/planning/executor_bridge.py", "app.services.action.manager"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.context"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.context.ToolContext"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.registry"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.registry.ToolRegistry"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.registry.get_tool_registry"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.surface"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.surface.ToolSurfaceResolver"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.world_context"),
        ("app/services/planning/executor_bridge.py", "app.services.tool.world_context.apply_world_facts"),
        # --- app/services/planning/memory_policy.py
        ("app/services/planning/memory_policy.py", "app.services.memory.commands"),
        ("app/services/planning/memory_policy.py", "app.services.memory.ingest"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.DEFAULT_CONFIDENCE"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.DEFAULT_IMPORTANCE"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.DEFAULT_MEMORY_TYPE"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.DEFAULT_SOURCE"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.FAILED_IMPORTANCE_FLOOR"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.MEMORY_CONTENT_MAX_CHARS"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.REASON_NO_POLICY_ROW"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.REASON_POLICY_DECLINED"),
        ("app/services/planning/memory_policy.py", "app.services.tool.memory_policy.REASON_POLICY_DEPOSIT"),
        # --- app/services/planning/observer.py
        ("app/services/planning/observer.py", "app.services.conversation.state"),
        ("app/services/planning/observer.py", "app.services.goal.arbitration"),
        ("app/services/planning/observer.py", "app.services.goal.observation"),
        ("app/services/planning/observer.py", "app.services.world.event_bridge"),
        # --- app/services/planning/revision_listener.py
        ("app/services/planning/revision_listener.py", "app.services.goal.planning"),
        ("app/services/planning/revision_listener.py", "app.services.reflection.lifecycle"),
        # --- app/services/reflection/evidence/collectors.py
        ("app/services/reflection/evidence/collectors.py", "app.services.memory.sources"),
        # --- app/services/reflection/reflector.py
        ("app/services/reflection/reflector.py", "app.services.memory.job_worker"),
        # --- app/services/reflection/triggers.py
        ("app/services/reflection/triggers.py", "app.services.memory.job_worker"),
        # --- app/services/relationship/evaluation.py
        ("app/services/relationship/evaluation.py", "app.services.conversation.context"),
        ("app/services/relationship/evaluation.py", "app.services.conversation.context._select_shared_entries"),
        ("app/services/relationship/evaluation.py", "app.services.development.aggregate"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.context"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.context.EvaluationContext"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.context.NarrativeFactRef"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.context.NarrativeMilestoneRef"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.context.NarrativeSlice"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.rules.relationship"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.rules.relationship.NarrativeFactProvenanceRule"),
        ("app/services/relationship/evaluation.py", "app.services.evaluation.rules.relationship.NarrativeMilestoneProvenanceRule"),
        ("app/services/relationship/evaluation.py", "app.services.memory.ingest"),
        # --- app/services/relationship/narrative.py
        ("app/services/relationship/narrative.py", "app.services.memory.ingest"),
        ("app/services/relationship/narrative.py", "app.services.memory.ingest.NARRATIVE_MILESTONE_PREFIX"),
        ("app/services/relationship/narrative.py", "app.services.memory.job_worker"),
        ("app/services/relationship/narrative.py", "app.services.reflection.lifecycle"),
        # --- app/services/relationship/patterns.py
        ("app/services/relationship/patterns.py", "app.services.development.aggregate"),
        ("app/services/relationship/patterns.py", "app.services.development.aggregate.list_active_modulations"),
        # --- app/services/tool/builtin.py
        ("app/services/tool/builtin.py", "app.services.action.registry"),
        ("app/services/tool/builtin.py", "app.services.action.registry.get_capability_registry"),
        # --- app/services/tool/channel_tools.py
        ("app/services/tool/channel_tools.py", "app.services.action.registry"),
        ("app/services/tool/channel_tools.py", "app.services.action.registry.ExecutionContext"),
        # --- app/services/tool/executor.py
        ("app/services/tool/executor.py", "app.services.action.executor"),
        ("app/services/tool/executor.py", "app.services.action.executor.CapabilityExecutor"),
        ("app/services/tool/executor.py", "app.services.action.registry"),
        ("app/services/tool/executor.py", "app.services.action.registry.ExecutionContext"),
        # --- app/services/tool/ext_api/handlers.py
        ("app/services/tool/ext_api/handlers.py", "app.services.action.registry"),
        ("app/services/tool/ext_api/handlers.py", "app.services.action.registry.ExecutionContext"),
        # --- app/services/tool/registry.py
        ("app/services/tool/registry.py", "app.services.action.registry"),
        ("app/services/tool/registry.py", "app.services.action.registry.Capability"),
        ("app/services/tool/registry.py", "app.services.action.registry.get_capability_registry"),
        # --- app/services/tool/user_defined.py
        ("app/services/tool/user_defined.py", "app.services.action.executor"),
        ("app/services/tool/user_defined.py", "app.services.action.executor.CapabilityExecutor"),
        ("app/services/tool/user_defined.py", "app.services.action.registry"),
        ("app/services/tool/user_defined.py", "app.services.action.registry.CapabilityRegistry"),
        ("app/services/tool/user_defined.py", "app.services.action.registry.ExecutionContext"),
        ("app/services/tool/user_defined.py", "app.services.action.registry.get_capability_registry"),
        # --- app/services/tool/world_context.py
        ("app/services/tool/world_context.py", "app.services.conversation.state"),
        ("app/services/tool/world_context.py", "app.services.conversation.state.load_relationship"),
        ("app/services/tool/world_context.py", "app.services.world.daily_plan"),
        ("app/services/tool/world_context.py", "app.services.world.locations"),
        ("app/services/tool/world_context.py", "app.services.world.locations.location_name"),
        ("app/services/tool/world_context.py", "app.services.world.time_provider"),
        ("app/services/tool/world_context.py", "app.services.world.time_provider.TimeProvider"),
        ("app/services/tool/world_context.py", "app.services.world.user_situation"),
        # --- app/services/world/event_bridge.py
        ("app/services/world/event_bridge.py", "app.services.reflection.lifecycle"),
        # --- app/services/world/memory_bridge.py
        ("app/services/world/memory_bridge.py", "app.services.memory.ingest"),
    }
)
