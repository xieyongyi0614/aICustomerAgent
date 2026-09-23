"""V4.0 测试支撑：V3.0.0 开关基线冻结 + V4.0 新增设置登记。

约定同 V3.0（`tests/v30/runtime_support.py`）：

- `V30_ENABLED_FLAGS` 是 **V3.0.0 冻结基线**（PLA-018 AC6 / PLA-001 AC6）。V4.0
  禁止新增任何功能开关（v4.0.0 `architecture.md` 铁律 5 / 不变量 11），故 `core/settings/`
  的 `*_enabled` 字段集合必须与它**完全一致**——本版只允许改既有字段的默认值。
  基线是**静态快照**而非运行时计算：动态计算会让「防新增」的断言退化为同义反复。
- `V40_SETTINGS_FIELDS`（字段名 → 归属 Task）：V4.0 新增的**参数类**字段登记处。
  新增 `*_enabled` 字段一律违规，不在此登记。
"""

from __future__ import annotations

V30_ENABLED_FLAGS: frozenset[str] = frozenset(
    {
        "action_detector_enabled",
        "action_memory_policy_enabled",
        "action_outbox_enabled",
        "action_relationship_enabled",
        "autonomy_action_enabled",
        "character_action_sync_enabled",
        "evaluation_action_enabled",
        "evaluation_autonomy_enabled",
        "evaluation_behavior_enabled",
        "evaluation_emotion_enabled",
        "evaluation_enabled",
        "evaluation_goal_enabled",
        "evaluation_llm_judge_enabled",
        "evaluation_memory_enabled",
        "evaluation_persona_enabled",
        "evaluation_reflection_enabled",
        "evaluation_relationship_enabled",
        "evaluation_world_consistency_enabled",
        "feishu_dedupe_persistent_enabled",
        "feishu_enabled",
        "feishu_ingress_sharded_routing_enabled",
        "feishu_router_enabled",
        "inventory_grounding_enabled",
        "observability_persist_enabled",
        "plan_context_digest_enabled",
        "rel_conflict_enabled",
        "rel_evolution_enabled",
        "rel_milestone_enabled",
        "runtime_autonomous_cycle_enabled",
        "runtime_context_freeze_enabled",
        "runtime_event_bus_enabled",
        "runtime_foreground_loop_enabled",
        "runtime_orphan_run_sweep_enabled",
        "runtime_reflect_in_loop_enabled",
        "runtime_session_tracking_enabled",
        "runtime_six_stage_loop_enabled",
        "runtime_state_versioning_enabled",
        "scene_idle_reset_enabled",
        "world_enabled",
        "world_household_autoseed_enabled",
        "world_interpreter_enabled",
        "world_memory_bridge_enabled",
    }
)

V40_SETTINGS_FIELDS: dict[str, str] = {
    "ledger_default_currency": "PLA-004",
    "ledger_extraction_min_confidence": "PLA-007",
    "ledger_category_fallback": "PLA-008",
    "ledger_confirm_threshold_amount": "PLA-010",
}
"""V4.0 新增参数类字段（字段名 → 归属 Task）。禁止登记 `*_enabled`。"""
