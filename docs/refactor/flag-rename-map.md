# vXX_ 字段改名对照表（旧名 → 新名）

> 生成时间 **2026-09-18**（批次 1 之后、批次 2 之前）；「新名」列由脚本从 `app/core/settings/*` 实测导出，非手抄。
> **执行状态：轨道 A 已执行完毕并提交 `992f05c`** —— 200 个字段的去前缀已落地，`app/core/settings/*` 中已无 `vXX_` 前缀；本表转为**读历史文档 / 查旧 env 名**的对照表。执行记录见 §九。
> **⚠ 其中 3 个字段在「第 0 步」被直接删除、未进入在存清单**：`v23_habit_time_enabled` / `v26_action_abstraction_enabled` / `v26_action_multistep_enabled`（`app/` 侧无行为分支，见配套文档附录 F.7）。§四 表格中对应行的「新名」列即该字段曾用于代码中的名字，现已不存在。
> 配套文档：`docs/refactor/flag-removal-audit.md`（成本审查 + 附录 F 批次台账 + 附录 G 验收判据）。

---

## 一、这张表解决什么问题

`docs/` 下 169 个文件、1,589 处 `vXX_` 引用按约定**不改写**（历史设计文档是事实记录，改写即篡改历史）。于是改造完成后会留下一个断层：**代码里已无版本次命名，文档里仍全是旧名**。本表是那座桥。

| 场景 | 用法 |
|---|---|
| 读历史设计文档 | 文档里的旧名 → 查表 → 新名；标注「已删除」的字段表示其 ON 路径已转常开，不再有配置面 |
| 轨道 A（去前缀）执行 | 按「新名」列批量替换；本表即替换清单与验收对象 |
| 排查线上静默回落 | 启动告警或运营侧 `.env` 中出现的旧 env 名 → 查表定位（旧名会被 `extra="ignore"` 静默吞掉） |
| 复核改造完整性 | 用 §八 的命令重建字段清单，与本表逐条比对 |

---

## 二、命名空间约定

| 维度 | 规则 |
|---|---|
| 字段名 | 去掉 `v<版本>_` 前缀后的领域名（本表「新名」列） |
| 环境变量名 | 字段名全大写——`DOMAIN_MODEL_CONFIG` 无 `env_prefix`、无 `alias_generator`，全仓库无 `Field(alias=...)`，故字段改名必然连带 env 改名 |
| 唯一性 | `Settings` 由 25 个领域类多继承组合成**扁平命名空间**，字段名必须全局唯一；撞名分析见 §六 |
| 表外字段 | 不带 `vXX_` 前缀的既有字段（227 个）保持不变，不在本表内 |

---

## 三、批次 1 已处理（12 个字段）

### 3.1 已改名（5）

| 旧名 | 新名 | 新 env | 说明 |
|---|---|---|---|
| `v2_action_outbox_enabled` | `action_outbox_enabled` | `ACTION_OUTBOX_ENABLED` | outbox 灰度保留（报告附录 E 方案③） |
| `v2_character_action_sync_enabled` | `character_action_sync_enabled` | `CHARACTER_ACTION_SYNC_ENABLED` | `.env` 中为 `true` |
| `v2_character_action_sync_context_lines` | `character_action_sync_context_lines` | `CHARACTER_ACTION_SYNC_CONTEXT_LINES` | 调参字段 |
| `v2_inventory_grounding_enabled` | `inventory_grounding_enabled` | `INVENTORY_GROUNDING_ENABLED` | `.env` 中为 `true` |
| `v2_inventory_grounding_mode` | `inventory_grounding_mode` | `INVENTORY_GROUNDING_MODE` | 调参字段，取值 off/rewrite/annotate |

### 3.2 已删除（7）

| 旧名 | 旧 env | 删除后的语义 |
|---|---|---|
| `v2_life_loop_enabled` | `V2_LIFE_LOOP_ENABLED` | ON 路径转常开；连带删除 `app/application/autonomy_worker.py` 与 `main.py` 旧三循环 |
| `v2_autonomy_advanced_enabled` | `V2_AUTONOMY_ADVANCED_ENABLED` | ON 路径转常开（自治步） |
| `v2_memory_enabled` | `V2_MEMORY_ENABLED` | ON 路径转常开（Memory V2 摄取 / 评估 / 检索） |
| `v2_memory_vector_enabled` | `V2_MEMORY_VECTOR_ENABLED` | ON 路径转常开（向量召回） |
| `v2_reflection_enabled` | `V2_REFLECTION_ENABLED` | ON 路径转常开（反思层） |
| `v2_development_enabled` | `V2_DEVELOPMENT_ENABLED` | ON 路径转常开（成长层） |
| `v2_relationship_evolved_enabled` | `V2_RELATIONSHIP_EVOLVED_ENABLED` | ON 路径转常开（关系演化） |

> 删除的字段**没有新名**：其 ON 路径已转常开，配置面不复存在。读到这些旧名时应理解为「该能力现在无条件生效」。

---

## 四、开关字段（51 个，已去前缀；其中 3 个已删除，在存 48）

按版本段分组。这些字段同时是**门控**，去前缀已完成；**去门控**（固化 ON）仍按审查报告 §八 / 附录 F 的批次顺序推进。

| 段 | 旧名 | 新名 | 旧 env | 默认 | 备注 |
|---|---|---|---|---|---|
| v21 | `v21_agent_metrics_enabled` | `agent_metrics_enabled` | `V21_AGENT_METRICS_ENABLED` | `False` | — |
| v21 | `v21_agent_runtime_enabled` | `agent_runtime_enabled` | `V21_AGENT_RUNTIME_ENABLED` | `False` | — |
| v21 | `v21_foreground_gateway_enforced` | `foreground_gateway_enforced` | `V21_FOREGROUND_GATEWAY_ENFORCED` | `False` | — |
| v21 | `v21_goal_stack_enabled` | `goal_stack_enabled` | `V21_GOAL_STACK_ENABLED` | `False` | 含 OFF 回退路径 |
| v21 | `v21_personality_evolution_enabled` | `personality_evolution_enabled` | `V21_PERSONALITY_EVOLUTION_ENABLED` | `False` | — |
| v21 | `v21_unified_run_enabled` | `unified_run_enabled` | `V21_UNIFIED_RUN_ENABLED` | `False` | — |
| v22 | `v22_emotion_transition_enabled` | `emotion_transition_enabled` | `V22_EMOTION_TRANSITION_ENABLED` | `False` | — |
| v22 | `v22_experience_enabled` | `experience_enabled` | `V22_EXPERIENCE_ENABLED` | `False` | — |
| v22 | `v22_habit_runtime_enabled` | `habit_runtime_enabled` | `V22_HABIT_RUNTIME_ENABLED` | `False` | — |
| v22 | `v22_relationship_addressing_enabled` | `relationship_addressing_enabled` | `V22_RELATIONSHIP_ADDRESSING_ENABLED` | `False` | — |
| v22 | `v22_style_contract_enabled` | `style_contract_enabled` | `V22_STYLE_CONTRACT_ENABLED` | `False` | — |
| v23 | `v23_daily_life_enabled` | `daily_life_enabled` | `V23_DAILY_LIFE_ENABLED` | `False` | 含 OFF 回退路径 |
| v23 | `v23_debug_tick_enabled` | `debug_tick_enabled` | `V23_DEBUG_TICK_ENABLED` | `False` | — |
| v23 | `v23_event_detection_enabled` | `event_detection_enabled` | `V23_EVENT_DETECTION_ENABLED` | `False` | 含 OFF 回退路径 |
| v23 | `v23_habit_time_enabled` | `habit_time_enabled` | `V23_HABIT_TIME_ENABLED` | `False` | ✅ 已删除（第 0 步，见报告 F.7） |
| v23 | `v23_scene_expansion_enabled` | `scene_expansion_enabled` | `V23_SCENE_EXPANSION_ENABLED` | `False` | 含 OFF 回退路径 |
| v23 | `v23_time_advance_enabled` | `time_advance_enabled` | `V23_TIME_ADVANCE_ENABLED` | `False` | — |
| v23 | `v23_world_llm_assist_enabled` | `world_llm_assist_enabled` | `V23_WORLD_LLM_ASSIST_ENABLED` | `False` | ⚠ 撞名，见 §6.1 |
| v23 | `v23_world_simulation_enabled` | `world_simulation_enabled` | `V23_WORLD_SIMULATION_ENABLED` | `False` | 含 OFF 回退路径 |
| v24 | `v24_tool_channel_enabled` | `tool_channel_enabled` | `V24_TOOL_CHANNEL_ENABLED` | `False` | — |
| v24 | `v24_tool_confirm_ttl_reuse` | `tool_confirm_ttl_reuse` | `V24_TOOL_CONFIRM_TTL_REUSE` | `True` | 默认 ON（策略位） |
| v24 | `v24_tool_external_api_enabled` | `tool_external_api_enabled` | `V24_TOOL_EXTERNAL_API_ENABLED` | `False` | — |
| v24 | `v24_tool_memory_enabled` | `tool_memory_enabled` | `V24_TOOL_MEMORY_ENABLED` | `False` | — |
| v24 | `v24_tool_observation_enabled` | `tool_observation_enabled` | `V24_TOOL_OBSERVATION_ENABLED` | `False` | — |
| v24 | `v24_tool_permission_enabled` | `tool_permission_enabled` | `V24_TOOL_PERMISSION_ENABLED` | `False` | — |
| v24 | `v24_tool_reflection_enabled` | `tool_reflection_enabled` | `V24_TOOL_REFLECTION_ENABLED` | `False` | — |
| v24 | `v24_tool_schema_validation_enabled` | `tool_schema_validation_enabled` | `V24_TOOL_SCHEMA_VALIDATION_ENABLED` | `False` | — |
| v24 | `v24_tool_surface_enabled` | `tool_surface_enabled` | `V24_TOOL_SURFACE_ENABLED` | `False` | — |
| v24 | `v24_tool_system_enabled` | `tool_system_enabled` | `V24_TOOL_SYSTEM_ENABLED` | `False` | 含 OFF 回退路径 |
| v24 | `v24_tool_user_defined_enabled` | `tool_user_defined_enabled` | `V24_TOOL_USER_DEFINED_ENABLED` | `False` | — |
| v25 | `v25_plan_autonomy_enabled` | `plan_autonomy_enabled` | `V25_PLAN_AUTONOMY_ENABLED` | `False` | — |
| v25 | `v25_plan_context_digest_enabled` | `plan_context_digest_enabled` | `V25_PLAN_CONTEXT_DIGEST_ENABLED` | `True` | 默认 ON（策略位） |
| v25 | `v25_plan_context_enabled` | `plan_context_enabled` | `V25_PLAN_CONTEXT_ENABLED` | `False` | 含 OFF 回退路径 |
| v25 | `v25_plan_debug_enabled` | `plan_debug_enabled` | `V25_PLAN_DEBUG_ENABLED` | `False` | — |
| v25 | `v25_plan_execution_enabled` | `plan_execution_enabled` | `V25_PLAN_EXECUTION_ENABLED` | `False` | 含 OFF 回退路径 |
| v25 | `v25_plan_memory_enabled` | `plan_memory_enabled` | `V25_PLAN_MEMORY_ENABLED` | `False` | — |
| v25 | `v25_plan_observation_enabled` | `plan_observation_enabled` | `V25_PLAN_OBSERVATION_ENABLED` | `False` | 含 OFF 回退路径 |
| v25 | `v25_plan_reflection_enabled` | `plan_reflection_enabled` | `V25_PLAN_REFLECTION_ENABLED` | `False` | — |
| v25 | `v25_plan_revision_enabled` | `plan_revision_enabled` | `V25_PLAN_REVISION_ENABLED` | `False` | — |
| v25 | `v25_plan_scheduler_enabled` | `plan_scheduler_enabled` | `V25_PLAN_SCHEDULER_ENABLED` | `False` | 含 OFF 回退路径 |
| v25 | `v25_plan_step_binding_enabled` | `plan_step_binding_enabled` | `V25_PLAN_STEP_BINDING_ENABLED` | `False` | — |
| v25 | `v25_plan_tool_required` | `plan_tool_required` | `V25_PLAN_TOOL_REQUIRED` | `True` | 含 OFF 回退路径；默认 ON（策略位） |
| v25 | `v25_plan_world_feedback_enabled` | `plan_world_feedback_enabled` | `V25_PLAN_WORLD_FEEDBACK_ENABLED` | `False` | — |
| v25 | `v25_planning_enabled` | `planning_enabled` | `V25_PLANNING_ENABLED` | `False` | 含 OFF 回退路径 |
| v26 | `v26_action_abstraction_enabled` | `action_abstraction_enabled` | `V26_ACTION_ABSTRACTION_ENABLED` | `False` | ✅ 已删除（第 0 步，见报告 F.7） |
| v26 | `v26_action_debug_enabled` | `action_debug_enabled` | `V26_ACTION_DEBUG_ENABLED` | `False` | — |
| v26 | `v26_action_execution_enabled` | `action_execution_enabled` | `V26_ACTION_EXECUTION_ENABLED` | `False` | 含 OFF 回退路径 |
| v26 | `v26_action_feedback_enabled` | `action_feedback_enabled` | `V26_ACTION_FEEDBACK_ENABLED` | `False` | — |
| v26 | `v26_action_multistep_enabled` | `action_multistep_enabled` | `V26_ACTION_MULTISTEP_ENABLED` | `False` | ✅ 已删除（第 0 步，见报告 F.7） |
| v26 | `v26_action_result_enabled` | `action_result_enabled` | `V26_ACTION_RESULT_ENABLED` | `False` | — |
| v26 | `v26_action_scheduler_enabled` | `action_scheduler_enabled` | `V26_ACTION_SCHEDULER_ENABLED` | `False` | — |

> 备注列含义：**含 OFF 回退路径** = 该开关旁边并存一条当前实际生效的旧路径，固化 ON 意味着删掉正在跑的代码（见报告 §四）；**✅ 已删除** = 无门控读取点的死开关，已按「删除而非转正」处理完（见报告 §5.1、§5.2 与 F.7）；**默认 ON（策略位）** = 语义更接近策略修饰位，删除时需逐个确认（见报告 §5.4）。

---

## 五、调参字段（149 个，已去前缀）

无语义变更，纯机械去前缀，已执行。按 settings 模块分组（模块名即字段定义所在文件）。

| 模块 | 旧名 | 新名 | 默认 | 备注 |
|---|---|---|---|---|
| `life_loop.py` | `v2_life_loop_budget_cache_seconds` | `life_loop_budget_cache_seconds` | `60` | — |
| `life_loop.py` | `v2_life_loop_cycle_llm_budget` | `life_loop_cycle_llm_budget` | `1` | — |
| `life_loop.py` | `v2_life_loop_daily_llm_call_budget` | `life_loop_daily_llm_call_budget` | `200` | — |
| `life_loop.py` | `v2_life_loop_daily_llm_token_budget` | `life_loop_daily_llm_token_budget` | `0` | — |
| `life_loop.py` | `v2_life_loop_degraded_usage_ratio` | `life_loop_degraded_usage_ratio` | `0.8` | — |
| `life_loop.py` | `v2_life_loop_memory_digest_chars` | `life_loop_memory_digest_chars` | `600` | — |
| `life_loop.py` | `v2_life_loop_memory_limit` | `life_loop_memory_limit` | `5` | — |
| `life_loop.py` | `v2_life_loop_memory_min_salience` | `life_loop_memory_min_salience` | `0.8` | — |
| `life_loop.py` | `v2_life_loop_outbox_backoff_seconds` | `life_loop_outbox_backoff_seconds` | `30` | — |
| `life_loop.py` | `v2_life_loop_outbox_max_attempts` | `life_loop_outbox_max_attempts` | `5` | — |
| `life_loop.py` | `v2_life_loop_reflection_check_interval_minutes` | `life_loop_reflection_check_interval_minutes` | `240` | — |
| `life_loop.py` | `v2_life_loop_storm_daily_limit` | `life_loop_storm_daily_limit` | `3` | — |
| `life_loop.py` | `v2_life_loop_tick_seconds` | `life_loop_tick_seconds` | `60` | — |
| `life_loop.py` | `v2_life_loop_trigger_backoff_seconds` | `life_loop_trigger_backoff_seconds` | `300` | — |
| `life_loop.py` | `v2_life_loop_trigger_max_attempts` | `life_loop_trigger_max_attempts` | `3` | — |
| `memory.py` | `v2_embedding_batch_size` | `embedding_batch_size` | `32` | — |
| `memory.py` | `v2_embedding_batch_window_seconds` | `embedding_batch_window_seconds` | `60` | — |
| `memory.py` | `v2_embedding_dimensions` | `embedding_dimensions` | `768` | — |
| `memory.py` | `v2_embedding_max_input_chars` | `embedding_max_input_chars` | `2000` | — |
| `memory.py` | `v2_embedding_model` | `embedding_model` | `（空）` | — |
| `memory.py` | `v2_embedding_profile` | `embedding_profile` | `（空）` | — |
| `memory.py` | `v2_job_max_attempts` | `job_max_attempts` | `5` | — |
| `memory.py` | `v2_job_poll_interval` | `job_poll_interval` | `60` | — |
| `memory.py` | `v2_job_retry_backoff_seconds` | `job_retry_backoff_seconds` | `60` | — |
| `memory.py` | `v2_job_running_timeout` | `job_running_timeout` | `600` | — |
| `memory.py` | `v2_memory_decay_batch_size` | `memory_decay_batch_size` | `200` | — |
| `memory.py` | `v2_memory_decay_lambda_json` | `memory_decay_lambda_json` | `{"user_preference": 0…` | — |
| `memory.py` | `v2_memory_eval_threshold_high` | `memory_eval_threshold_high` | `0.75` | — |
| `memory.py` | `v2_memory_eval_threshold_low` | `memory_eval_threshold_low` | `0.35` | — |
| `memory.py` | `v2_memory_eval_weight_affinity` | `memory_eval_weight_affinity` | `0.20` | — |
| `memory.py` | `v2_memory_eval_weight_novelty` | `memory_eval_weight_novelty` | `0.30` | — |
| `memory.py` | `v2_memory_eval_weight_salience` | `memory_eval_weight_salience` | `0.15` | — |
| `memory.py` | `v2_memory_eval_weight_source` | `memory_eval_weight_source` | `0.35` | — |
| `memory.py` | `v2_memory_forget_retention_days` | `memory_forget_retention_days` | `30` | — |
| `memory.py` | `v2_memory_hypothetical_triggers_json` | `memory_hypothetical_triggers_json` | `["假装", "如果", "假如", "要…` | — |
| `memory.py` | `v2_memory_ingest_max_per_turn` | `memory_ingest_max_per_turn` | `10` | — |
| `memory.py` | `v2_memory_llm_fallback_rate_cap` | `memory_llm_fallback_rate_cap` | `0.3` | — |
| `memory.py` | `v2_memory_penalty_contradicts` | `memory_penalty_contradicts` | `0.2` | — |
| `memory.py` | `v2_memory_penalty_rejected` | `memory_penalty_rejected` | `0.2` | — |
| `memory.py` | `v2_memory_reinforce_boost` | `memory_reinforce_boost` | `0.1` | — |
| `memory.py` | `v2_memory_rejected_cooldown_hours` | `memory_rejected_cooldown_hours` | `24.0` | — |
| `memory.py` | `v2_memory_retrieval_budget` | `memory_retrieval_budget` | `800` | — |
| `memory.py` | `v2_memory_salience_floor` | `memory_salience_floor` | `0.1` | — |
| `memory.py` | `v2_memory_temporal_recency_boost` | `memory_temporal_recency_boost` | `0.2` | — |
| `memory.py` | `v2_memory_transient_triggers_json` | `memory_transient_triggers_json` | `["帮我拿", "帮我递", "递给我",…` | — |
| `memory.py` | `v2_memory_vector_recall_k` | `memory_vector_recall_k` | `20` | — |
| `memory.py` | `v2_memory_weight_affinity` | `memory_weight_affinity` | `0.20` | — |
| `memory.py` | `v2_memory_weight_semantic` | `memory_weight_semantic` | `0.45` | — |
| `memory.py` | `v2_memory_weight_structured` | `memory_weight_structured` | `0.35` | — |
| `autonomy_advanced.py` | `v2_autonomy_abandon_min_progress_days` | `autonomy_abandon_min_progress_days` | `14` | — |
| `autonomy_advanced.py` | `v2_autonomy_arbitration_interval_minutes` | `autonomy_arbitration_interval_minutes` | `60` | — |
| `autonomy_advanced.py` | `v2_autonomy_goal_max_active_hours` | `autonomy_goal_max_active_hours` | `168` | — |
| `autonomy_advanced.py` | `v2_autonomy_observation_window_minutes` | `autonomy_observation_window_minutes` | `120` | — |
| `autonomy_advanced.py` | `v2_autonomy_planning_llm_profile` | `autonomy_planning_llm_profile` | `（空）` | — |
| `autonomy_advanced.py` | `v2_autonomy_planning_max_attempts` | `autonomy_planning_max_attempts` | `3` | — |
| `autonomy_advanced.py` | `v2_autonomy_priority_layer_weight_long` | `autonomy_priority_layer_weight_long` | `1.0` | — |
| `autonomy_advanced.py` | `v2_autonomy_subgoal_execute_cooldown_minutes` | `autonomy_subgoal_execute_cooldown_minutes` | `30` | — |
| `autonomy_advanced.py` | `v2_autonomy_subgoal_failure_threshold` | `autonomy_subgoal_failure_threshold` | `3` | — |
| `autonomy_advanced.py` | `v2_autonomy_subgoal_max_count` | `autonomy_subgoal_max_count` | `5` | — |
| `autonomy_advanced.py` | `v2_autonomy_subgoal_max_depth` | `autonomy_subgoal_max_depth` | `2` | — |
| `autonomy_advanced.py` | `v2_autonomy_supply_interval_minutes` | `autonomy_supply_interval_minutes` | `720` | — |
| `autonomy_advanced.py` | `v2_autonomy_supply_personal_min_weight` | `autonomy_supply_personal_min_weight` | `0.3` | — |
| `autonomy_advanced.py` | `v2_autonomy_supply_relationship_min_strength` | `autonomy_supply_relationship_min_strength` | `0.6` | — |
| `autonomy_advanced.py` | `v2_autonomy_supply_templates_json` | `autonomy_supply_templates_json` | `{"personal": "在用户在意的话…` | — |
| `autonomy_advanced.py` | `v2_autonomy_supply_world_min_salience` | `autonomy_supply_world_min_salience` | `0.85` | — |
| `reflection_development.py` | `v2_development_answer_min_tokens` | `development_answer_min_tokens` | `300` | — |
| `reflection_development.py` | `v2_development_belief_habit_templates_json` | `development_belief_habit_templates_json` | `{"加班": {"id": "dev_ha…` | — |
| `reflection_development.py` | `v2_development_belief_topic_rules_json` | `development_belief_topic_rules_json` | `{"加班": "工作压力", "压力": …` | — |
| `reflection_development.py` | `v2_development_pattern_goal_tier_delta_max` | `development_pattern_goal_tier_delta_max` | `0.5` | — |
| `reflection_development.py` | `v2_development_preference_max_token_delta` | `development_preference_max_token_delta` | `200` | — |
| `reflection_development.py` | `v2_development_preference_tone_rules_json` | `development_preference_tone_rules_json` | `{"简短": "更简练、直给，不绕弯子"}` | — |
| `reflection_development.py` | `v2_reflection_ai_inferred_cap` | `reflection_ai_inferred_cap` | `0.5` | — |
| `reflection_development.py` | `v2_reflection_cluster_cosine` | `reflection_cluster_cosine` | `0.82` | — |
| `reflection_development.py` | `v2_reflection_confidence_count_curve_json` | `reflection_confidence_count_curve_json` | `{"3": 0.65, "4": 0.75…` | — |
| `reflection_development.py` | `v2_reflection_context_max_items` | `reflection_context_max_items` | `5` | — |
| `reflection_development.py` | `v2_reflection_context_scopes_json` | `reflection_context_scopes_json` | `["user", "relationshi…` | — |
| `reflection_development.py` | `v2_reflection_context_statement_chars` | `reflection_context_statement_chars` | `120` | — |
| `reflection_development.py` | `v2_reflection_event_cooldown_hours` | `reflection_event_cooldown_hours` | `24.0` | — |
| `reflection_development.py` | `v2_reflection_event_threshold` | `reflection_event_threshold` | `3` | — |
| `reflection_development.py` | `v2_reflection_evidence_content_chars` | `reflection_evidence_content_chars` | `200` | — |
| `reflection_development.py` | `v2_reflection_evidence_max_members` | `reflection_evidence_max_members` | `12` | — |
| `reflection_development.py` | `v2_reflection_invalidate_match_threshold` | `reflection_invalidate_match_threshold` | `0.7` | — |
| `reflection_development.py` | `v2_reflection_llm_profile` | `reflection_llm_profile` | `（空）` | — |
| `reflection_development.py` | `v2_reflection_max_insights_per_run` | `reflection_max_insights_per_run` | `3` | — |
| `reflection_development.py` | `v2_reflection_min_coherence` | `reflection_min_coherence` | `0.5` | — |
| `reflection_development.py` | `v2_reflection_min_confidence` | `reflection_min_confidence` | `0.6` | — |
| `reflection_development.py` | `v2_reflection_min_evidence` | `reflection_min_evidence` | `3` | — |
| `reflection_development.py` | `v2_reflection_min_span_hours` | `reflection_min_span_hours` | `24.0` | — |
| `reflection_development.py` | `v2_reflection_run_timeout_minutes` | `reflection_run_timeout_minutes` | `10` | — |
| `reflection_development.py` | `v2_reflection_schedule_hour` | `reflection_schedule_hour` | `4` | — |
| `reflection_development.py` | `v2_reflection_statement_max_chars` | `reflection_statement_max_chars` | `200` | — |
| `reflection_development.py` | `v2_reflection_window_days` | `reflection_window_days` | `30` | — |
| `reflection_development.py` | `v2_relationship_narrative_daily_cap` | `relationship_narrative_daily_cap` | `1` | — |
| `reflection_development.py` | `v2_relationship_narrative_min_confidence` | `relationship_narrative_min_confidence` | `0.75` | — |
| `reflection_development.py` | `v2_relationship_narrative_whitelist_json` | `relationship_narrative_whitelist_json` | `{"narrative:all_night…` | — |
| `reflection_development.py` | `v2_relationship_pattern_budget_chars` | `relationship_pattern_budget_chars` | `120` | — |
| `reflection_development.py` | `v2_relationship_pattern_max_items` | `relationship_pattern_max_items` | `2` | — |
| `reflection_development.py` | `v2_relationship_pattern_min_strength` | `relationship_pattern_min_strength` | `0.6` | — |
| `reflection_development.py` | `v2_relationship_shared_budget_chars` | `relationship_shared_budget_chars` | `200` | — |
| `reflection_development.py` | `v2_relationship_shared_limit` | `relationship_shared_limit` | `3` | — |
| `reflection_development.py` | `v2_relationship_shared_min_salience` | `relationship_shared_min_salience` | `0.6` | — |
| `agent_runtime.py` | `v21_agent_evolution_interval_seconds` | `agent_evolution_interval_seconds` | `3600.0` | — |
| `agent_runtime.py` | `v21_decision_weight` | `decision_weight` | `1.0` | — |
| `agent_runtime.py` | `v21_event_escalation_types` | `event_escalation_types` | `（空）` | ⚠ 撞名，见 §6.2 |
| `agent_runtime.py` | `v21_evolution_max_drift_per_week` | `evolution_max_drift_per_week` | `0.05` | — |
| `agent_runtime.py` | `v21_evolution_window_days` | `evolution_window_days` | `7` | — |
| `agent_runtime.py` | `v21_foreground_run_llm_budget` | `foreground_run_llm_budget` | `8` | — |
| `agent_runtime.py` | `v21_goal_medium_timeout_days` | `goal_medium_timeout_days` | `7` | — |
| `agent_runtime.py` | `v21_goal_short_timeout_hours` | `goal_short_timeout_hours` | `24` | — |
| `agent_runtime.py` | `v21_interest_top_n` | `interest_top_n` | `3` | — |
| `agent_runtime.py` | `v21_interest_weight_goal` | `interest_weight_goal` | `1.0` | — |
| `agent_runtime.py` | `v21_interest_weight_memory` | `interest_weight_memory` | `1.0` | — |
| `agent_runtime.py` | `v21_interest_weight_preference` | `interest_weight_preference` | `1.0` | — |
| `agent_runtime.py` | `v21_interest_weight_world` | `interest_weight_world` | `1.0` | — |
| `agent_runtime.py` | `v21_light_llm_profile` | `light_llm_profile` | `（空）` | — |
| `agent_runtime.py` | `v21_metric_breach_streak` | `metric_breach_streak` | `2` | — |
| `agent_runtime.py` | `v21_metric_floor_action_quality` | `metric_floor_action_quality` | `0.5` | — |
| `agent_runtime.py` | `v21_metric_floor_decision_quality` | `metric_floor_decision_quality` | `0.5` | — |
| `agent_runtime.py` | `v21_metric_floor_goal_progress` | `metric_floor_goal_progress` | `0.5` | — |
| `agent_runtime.py` | `v21_metric_floor_persona_consistency` | `metric_floor_persona_consistency` | `0.9` | — |
| `agent_runtime.py` | `v21_metric_trend_windows` | `metric_trend_windows` | `7` | — |
| `agent_runtime.py` | `v21_state_snapshot_min_interval_minutes` | `state_snapshot_min_interval_minutes` | `15` | — |
| `agent_runtime.py` | `v21_state_snapshot_retention_days` | `state_snapshot_retention_days` | `90` | — |
| `world_simulation.py` | `v23_event_escalation_types` | `event_escalation_types` | `user_condition,weathe…` | ⚠ 撞名，见 §6.2 |
| `world_simulation.py` | `v23_interest_confidence_threshold` | `interest_confidence_threshold` | `0.7` | — |
| `world_simulation.py` | `v23_llm_assist_sample_rate` | `llm_assist_sample_rate` | `0.2` | — |
| `world_simulation.py` | `v23_part_boundaries_json` | `part_boundaries_json` | `{"morning":360,"noon"…` | — |
| `tool.py` | `v24_tool_audit_retention_days` | `tool_audit_retention_days` | `180` | — |
| `tool.py` | `v24_tool_breaker_cooldown_seconds` | `tool_breaker_cooldown_seconds` | `300` | — |
| `tool.py` | `v24_tool_breaker_threshold` | `tool_breaker_threshold` | `3` | — |
| `tool.py` | `v24_tool_confirm_timeout_hours` | `tool_confirm_timeout_hours` | `24` | — |
| `tool.py` | `v24_tool_disabled_ids` | `tool_disabled_ids` | `（空）` | — |
| `tool.py` | `v24_tool_ext_allowed_hosts` | `tool_ext_allowed_hosts` | `（空）` | — |
| `tool.py` | `v24_tool_ext_manifest_path` | `tool_ext_manifest_path` | `（空）` | — |
| `tool.py` | `v24_tool_surface_max_tools` | `tool_surface_max_tools` | `12` | — |
| `plan.py` | `v25_plan_context_insight_limit` | `plan_context_insight_limit` | `5` | — |
| `plan.py` | `v25_plan_context_memory_limit` | `plan_context_memory_limit` | `5` | — |
| `plan.py` | `v25_plan_llm_profile` | `plan_llm_profile` | `（空）` | — |
| `plan.py` | `v25_plan_max_depth` | `plan_max_depth` | `2` | — |
| `plan.py` | `v25_plan_max_steps` | `plan_max_steps` | `5` | — |
| `plan.py` | `v25_plan_memory_importance_floor` | `plan_memory_importance_floor` | `0.6` | — |
| `plan.py` | `v25_plan_observation_window_minutes` | `plan_observation_window_minutes` | `120` | — |
| `plan.py` | `v25_plan_reflection_min_samples` | `plan_reflection_min_samples` | `3` | — |
| `plan.py` | `v25_plan_replan_min_confidence` | `plan_replan_min_confidence` | `0.7` | — |
| `plan.py` | `v25_plan_revision_budget` | `plan_revision_budget` | `3` | — |
| `plan.py` | `v25_plan_step_cooldown_minutes` | `plan_step_cooldown_minutes` | `30` | — |
| `plan.py` | `v25_plan_step_max_attempts` | `plan_step_max_attempts` | `2` | — |
| `plan.py` | `v25_plan_ttl_hours` | `plan_ttl_hours` | `168` | — |
| `action_execution.py` | `v26_action_schedule_default_priority` | `action_schedule_default_priority` | `100` | — |

---

## 六、撞名裁决（2 处，**已执行**）

### 6.1 `world_llm_assist_*` 重复对 → 采用「删除未接线对」

| 位置 | 字段 | 是否接线 |
|---|---|---|
| `world.py`（`WorldSettings`） | `world_llm_assist_enabled`、`world_llm_assist_sample_rate` | **未接线**：`app/` 中除定义外无任何门控读取点；仅 `tests/conftest.py:390` 的 `env_map` 条目与 `tests/unit/test_world_models.py:143` 的默认值断言引用 |
| `world_simulation.py`（`WorldSimulationSettings`） | `v23_world_llm_assist_enabled`、`v23_llm_assist_sample_rate` | **已接线**：`app/services/world/user_situation.py:213,215` |

**裁决（已执行，步骤 0，先于批量改名）**：删除 `world.py` 的两个未接线字段；`v23_*` 两个字段改名为无前缀的 `world_llm_assist_enabled` / `world_llm_assist_sample_rate`。因两个字段的 env 名（`WORLD_LLM_ASSIST_ENABLED` / `WORLD_LLM_ASSIST_SAMPLE_RATE`）与既有 `tests/conftest.py:390` 的 `env_map` 条目、`tests/unit/test_world_models.py:143` 的默认值断言一致，删改后**无需改动任何测试**。

理由：保留一个从未接线的同名字段，只会让人误以为该能力可配置——这比改名本身更危险。

### 6.2 `event_escalation_types` → 采用「按域加前缀」

两处**都在使用**，且语义不同。`app/application/agent_runtime/trigger_router.py:26-33` 的 `escalation_whitelist()` 同时读两者：

| 旧名 | 语义 | 建议新名 |
|---|---|---|
| `v21_event_escalation_types` | Agent 事件白名单（`controller.py:272` 单独读取） | `agent_event_escalation_types` |
| `v23_event_escalation_types` | 世界事件白名单 | `world_event_escalation_types` |

---

## 七、命名一致性建议（**轨道 A 未采纳，待裁决**）

轨道 A 只做机械去前缀，本节各项**均未执行**（保持「新名」列的机械结果）。若采纳，需再走一次改名（含 env 与契约同步），建议与后续批次合并决策：

本表的「新名」列是**机械去前缀**结果，可直接脚本执行。但 `Settings` 是扁平命名空间，部分字段去前缀后丧失域归属，与同域既有字段的命名风格不一致。以下为建议项，**不影响本表的可执行性**，逐条需人工裁决：

| 域 | 机械结果的问题 | 建议 | 理由 |
|---|---|---|---|
| v23 | `time_advance_enabled`、`daily_life_enabled`、`event_detection_enabled`、`debug_tick_enabled`、`habit_time_enabled`、`part_boundaries_json`、`interest_confidence_threshold` 等裸名 | 加 `world_` 前缀 | `world.py` 既有 23 个字段**全部**以 `world_` 开头；裸名在扁平命名空间里看不出归属 |
| v21 | `decision_weight`、`light_llm_profile`、`interest_*`、`metric_*`、`unified_run_enabled`、`foreground_*` | 加 `agent_` 前缀 | 该域定义在 `agent_runtime.py`，裸名过泛 |
| v21 | `goal_stack_enabled`、`goal_short_timeout_hours`、`goal_medium_timeout_days` | 建议 `agent_goal_*` | 否则会与 `goal.py`（V6 Goal 域，9 个 `goal_*` 字段）**同前缀不同义**，极易误读 |
| v25 | `planning_enabled` | 建议 `plan_enabled` | 13 个子闸均为 `plan_*`，master 词干应一致（对比 `tool_system_*` / `world_*` / `agent_*` / `action_*` 族均为同词干） |
| v2 memory | `embedding_*`（7）、`job_*`（4） | 建议 `memory_embedding_*`、`memory_job_*` | `memory.py` 既有 16 个字段**全部**以 `memory_` 开头 |
| v2 relationship | `relationship_*` | 二选一：`relationship_*` 或 `rel_*` | `relationship.py` 既有 23 个字段用缩写 `rel_*`；而 `v2_relationship_*` 属于 `RelationshipEvolvedSettings`（V2.0.0 深化），两者不是同一层 |
| v22 | `emotion_transition_enabled` 等 4 个子闸 | 可选加 `experience_` 前缀 | master 为 `experience_enabled`，子闸无共同词干 |

---

## 八、一致性校验与再生成

**残留校验（轨道 A 的 done 判据，两条都应输出 0）**：

```bash
cd apps/backend && .venv/Scripts/python.exe -c "import re,pathlib; d=pathlib.Path('app/core/settings'); rows=[(p.name,n) for p in sorted(d.glob('*.py')) for n in re.findall(r'^\s{4}(v\d+_[a-z_]+)\s*:', p.read_text(encoding='utf-8'), re.M)]; print(len(rows)); [print(p, n) for p, n in rows]"
```

```bash
cd apps/backend && .venv/Scripts/python.exe -c "import re; from app.core.settings import Settings; n=list(Settings.model_fields); pre=[x for x in n if re.match(r'^v[0-9]+_',x)]; print('总数',len(n),'带前缀',len(pre))"
```

**轨道 B 的在存开关清单**（每批开动前用它导出该批的开关与 `app/` 侧引用数，替代已过时的报告附录 A）：

```bash
cd apps/backend && .venv/Scripts/python.exe -c "import re,pathlib; mods={'agent_runtime':'v21','experience':'v22','world_simulation':'v23','tool':'v24','plan':'v25','action_execution':'v26'}; f={n:mods[p.stem] for p in pathlib.Path('app/core/settings').glob('*.py') if p.stem in mods for n in re.findall(r'^\s{4}([a-z_0-9]+)\s*:\s*bool\s*=',p.read_text(encoding='utf-8'),re.M)}; t={p:p.read_text(encoding='utf-8') for p in pathlib.Path('app').rglob('*.py') if 'core/settings' not in p.as_posix()}; [print(f[n], n, sum(len(re.findall(r'\b'+n+r'\b',x)) for x in t.values())) for n in sorted(f, key=lambda k:(f[k],k))]"
```

预期：48 行，按版本段汇总为 v21 6 / v22 5 / v23 7 / v24 11 / v25 14 / v26 5（2026-09-18 实测 app 引用合计 234 处 / 53 个模块）。

**再生成算法**（本表若需重建）：

1. 扫描 `app/core/settings/*.py` 中 **4 空格缩进**的 `name: type = default` 行（跳过 `__init__.py` / `_shared.py` / `enablement.py`）；多行默认值需按括号配对合并；
2. 按注解是否 `bool` 分成「开关表」与「调参表」；
3. **旧名 = 在存名加回 `v<版本>_`**（版本段由定义所在模块推出：`agent_runtime`→v21、`experience`→v22、`world_simulation`→v23、`tool`→v24、`plan`→v25、`action_execution`→v26，其余模块→v2）；env = 在存名全大写；
4. 备注列由三份清单驱动：§六 撞名表、报告 §5.1/§5.2 无行为开关（**已全部处理完，见 §九 步骤 2**）、报告 §四 含 OFF 回退路径的开关。

> 生成脚本与校验脚本的负向测试均为本地临时件，不入库；方法已固化在上文四条规则里，复现无需依赖那些文件。

改造完成后的残留扫描与 done 判据见 `flag-removal-audit.md` 附录 G.1 / G.2。

---

## 九、执行记录（轨道 A，2026-09-18）

| 项 | 值 |
|---|---|
| 步骤 0 | 删除 `world.py` 的未接线字段 `world_llm_assist_enabled` / `world_llm_assist_sample_rate`（§6.1 裁决前置条件） |
| 步骤 1 | 200 个字段批量去前缀：**265 个文件、2367 处替换**（含字段名、env 名、契约 key、测试字面量、文档串） |
| 替换范围 | `app/`、`tests/`、`scripts/`、`apps/frontend/src/`、`.env`、`.env.example`；**不含 `docs/`**（历史文档按约定不改写） |
| 人工修正 | 4 处按前缀发现字段的测试改用 `PlanSettings.model_fields` 锚定；1 处动态拼接 `f"v21_metric_floor_{name}"` 改为 `f"metric_floor_{name}"`；6 处内嵌版本号的标识符改名；7 处叙述性前缀片段改为新前缀（`plan_*` / `tool_*` / `action_*`）；`.env.example` 覆盖率用例正则由 `V24_TOOL_` 改为 `TOOL_` |
| 冻结哈希重建 | 12 条源码哈希同步（8 条本次重构引发 + 4 条既有失配基线重建），见 `flag-removal-audit.md` 附录 G.3 |
| 字段集合 | 427 → **425**（仅步骤 0 删除 2 个）；带 `vXX_` 前缀 **200 → 0** |
| 后端全量 | `16 failed, 6443 passed, 22 skipped`（改造前基线 `24 failed, 6434 passed, 22 skipped`；差额 = 8 条冻结哈希修复 − 0 新增，另 2 条 v7.8 计时类用例经 3 次单跑确认为 flaky） |
| 前端 | `vitest run` 29 文件 / 149 用例全绿；`tsc -b` 通过 |
| 提交 | **已提交 `992f05c`**（`refactor: 设置字段去版本号前缀`），与批次 1 的 `68d85ac` / `93dcb1e` 一并在 `feat/feishu_bot` 上，已推 origin |

**步骤 2（第 0 步，2026-09-18，零行为变化）**：删除 3 个死开关 `habit_time_enabled` / `action_abstraction_enabled` / `action_multistep_enabled`，连带 `RESERVED_V23_SUB_FLAGS` / `RESERVED_V26_SUB_FLAGS`、`enablement.py` 的两个 reserved warning 函数、`_V23_FLAG_NAMES` 中的对应条目（快照 8 键 → 7 键）。字段总数 425 → **422**；在存开关 51 → **48**。详见 `flag-removal-audit.md` F.7。

**遗留（不在轨道 A 范围）**：`enablement.py` 内部版本桶常量（`V25_SUB_FLAGS` 等，收尾批随文件删除）、测试目录名与测试函数名中的版本标记（`v24_tool_env` / `v21_on` 等 fixture 名，测试侧残留 188 处全是这类标识符，非失效 env key）、`_V23_FLAG_NAMES`（v23 批删除）——这些不影响「配置层与契约层不出现 `v[0-9]+_`」的 done 判据。

---

## 附录：字段计数

计数来源为 `Settings.model_fields`（权威）与 `app/core/settings/*.py` 源码扫描，**两法结果一致**：

| 口径 | 数量 |
|---|---|
| 改造前 settings 字段总数（报告 §2.1 口径） | 434 |
| 改造前其中带 `vXX_` 前缀 | 212 |
| 批次 1 已处理 | 12（5 改名 + 7 删除） |
| 轨道 A 处理 | 200 去前缀（51 开关 + 149 调参）+ 步骤 0 删 2 个未接线字段 |
| 第 0 步删除死开关 | 3（见 §九 步骤 2） |
| **当前** settings 字段总数 | **422** |
| 其中带 `vXX_` 前缀 | **0** |
| 原带前缀、现仍在存的字段 | 197（**48 开关** + 149 调参） |
| 唯一性例外（撞名，见 §六） | 2 组（均已裁决并执行） |

**对账**：`434 − 7 − 2 − 3 = 422`；`212 = 200 + 12`；`200 = 197 + 3`（3 个死开关未进入改名后在存清单）。
