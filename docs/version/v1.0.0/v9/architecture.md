# V9 架构设计

> Action Capability System 是 Character Runtime 的**执行层**：检出、决策、执行、整合四段全部旁路挂载。本篇定义分层归属、与既有管线的挂载点、与 V8 interpreter 的分工、失败契约与开关矩阵。

## 1. 总体架构

```text
User Request ──→ Character Runtime（V2~V8，零修改）
                  │  四链并行 / Behavior / Answer（言语层，照旧）
                  │
                  │  H-A1  确定性检出（纯函数，读 user content + 场景）
                  ▼
        ┌──────── Action Domain（V9 新增）────────────────────┐
        │  ActionIntent ──→ Action Planner ──→ ActionPlan     │
        │                    （六闸门 + 装配，纯函数）           │
        │                          ↓                          │
        │                 Capability Runtime                  │
        │  Registry（能力注册）+ Executor（超时/重试/幂等）        │
        │   Reminder / Memory / WorldAction / EnvQuery         │
        │   Search / Notification（接口预留，占位）              │
        └───────────────┬────────────────────────────────────┘
                        │ ActionResult（效果清单）
                        ▼
   ┌── Result Integration 四通道（post_process 第 9 步内）──┐
   │  World Update（world_engine 既有 API，零修改）          │
   │  Memory Decision（Action Memory Policy → 既有仓储）     │
   │  Relationship Impact（RelationshipEvent，默认关）       │
   │  Action Note（下轮行动上下文段 + 自治事实包）             │
   └────────────────────────────────────────────────────┘
                        ▼
                 Response（后续轮次基于真实行动事实）
```

数据流（一次前台 turn）：

```text
t1  既有管线步骤不变；四链并行后新增一步：
    action_intent = detect_action_intent(content, scene_state)   ← H-A1，纯函数，门控+降级 None
    （进入 turn_meta，供前端与评估观测；不进入本轮 prompt——检出不影响本轮言语）
t2~tn  answer 照旧生成回复（对行动一无所知，回复只能说进行时承诺）
tn+1  save_turn（现状）
tn+2  schedule_post_process：既有 8 步不变，末尾追加 run_action_planning（第 9 步）← H-A2
      ├─ intent 校验 + 六闸门 → ActionPlan（created→planned）
      ├─ ActionEngine 执行 → CapabilityExecutor → ActionResult（executing→succeeded/failed）
      └─ 结果整合：世界写回 / 记忆候选 / 关系信号 / 行动 note
tn+3  下一轮：Context Builder 渲染【行动】段 action_ctx → prompt ← H-A3
```

数据流（自治 tick，V7 照旧 + 两个只读增量）：

```text
autonomy_worker.tick ──→ autonomy_engine._process_user
                          ├─ trigger_evaluator：新增 poll_due_actions（WorldEvent(type=reminder).due
                          │   → TriggerSignal(trigger_type="action_due")）← H-A6
                          ├─ _snapshot_for：PolicySnapshot.action_facts（进行中/最近行动）← H-A5
                          └─ 八步裁决照旧 → act 仍产出 ProactiveAction(send_message)（零回归）
                             （自治直接产 ActionPlan 的分支由 autonomy_action_enabled 门控，默认关）
```

## 2. 分层归属（Domain / Application / Infrastructure）

沿用 `api → application → services → repositories → core` 单向依赖：

| 层 | 位置 | 内容 | 约束 |
|---|---|---|---|
| Domain | `app/models/action.py` | ActionIntent / ActionPlan / ActionStep / ActionResult / ActionEffect / ActionRecord + 枚举（ActionStatus、ActionType、ActionSource、GateReason、FailureKind）+ 状态迁移纯函数 | 纯 Pydantic，零 IO；六态状态机为纯函数 |
| Character 资产 | `app/character/asuna/action.py` | 行动触发词表、时间短语模式、能力描述文案、记忆模板 | 行动"设定"属于角色资产，与行动"状态"分离 |
| Services | `app/services/action/` | `detector.py`（ActionIntentDetector）、`planner.py`（闸门 + 装配纯函数）、`registry.py`（CapabilityRegistry）、`executor.py`（CapabilityExecutor）、`memory_bridge.py`、`relationship_bridge.py`、`capabilities/*.py`（各能力实现） | 纯计算或经仓储读写行动自身；世界/记忆/关系只调既有写通道 |
| Application | `app/application/action_engine.py` | ActionEngine：intent→plan→execute→integrate 编排、post_process 第 9 步 run_action_planning、自治 due 行动查询封装 | 只做调度与容错；检出/闸门/执行逻辑在 services |
| Infrastructure | `app/repositories/action_repository.py` + 迁移 0018 + `core/settings.py` | action_records 单表读写、去重查询、统计 | 沿用模块级函数仓储惯例 |
| Chains | `app/chains/action_assist_chain.py`（P2，可选） | LLM 辅助意图澄清（采样启用），schema `ActionAssistResult` | 走 build_structured_chain；失败返回 None；**默认关** |
| Interfaces | `app/api/v1/action.py` | /debug/actions 列表 / 详情 / 手动执行 / 取消 | 只读为主，手动端点显式标注 |
| Character 资产 | — | — | 同上，见 Character 资产行 |

明确不改的文件：`answer_chain` 生成逻辑（只增可选 action_ctx 透传）、`autonomy_policy.evaluate` 既有八步裁决（只增可选输入）、`proactive_executor`、`world_engine` 全部既有方法、`memory_service/extractor`、`state_service` 既有语义、`evaluation_engine` 引擎骨架（只注册新规则）。

## 3. 挂载点清单（全部是加法）

| # | 挂载点 | 文件 | 变更形态 | 归属 Task |
|---|---|---|---|---|
| H-A1 | turn 内行动意图检出 | `app/application/chat_pipeline.py` | 四链并行后 +3 行 `action_intent = detect_action_intent(...)`（门控 + try/except 降级 None），进 turn_meta | 002 |
| H-A2 | post_process 第 9 步 | `app/application/post_process.py::STEP_HANDLERS` | 追加 `run_action_planning`（官方扩展点；与 run_world_update 同构） | 005 |
| H-A3 | 行动上下文段 | `services/context_builder.py` + `prompts/builder.py::build` + `chains/answer_chain.py` | Context Builder 增 action_ctx 装配；PromptBuilder 增可选 `action_ctx=None`；answer_chain 透传（world_ctx 同构三连） | 006 |
| H-A4 | trace 步骤名 | `app/services/trace_collector.py::TRACE_STEP_NAMES` | 追加 `action_detect`、`action_execute` 两个规范名 | 005 |
| H-A5 | 自治裁决事实 | `app/application/autonomy_engine.py::_snapshot_for` | PolicySnapshot 增 `action_facts` 字段（默认空 dict，行为不变） | 009 |
| H-A6 | 自治触发器 | `app/services/trigger_evaluator.py` | 增 `poll_due_actions`（优先级排在 poll_due_followup 之前，同款幂等） | 009 |
| H-A7 | Router 注册 | `app/api/v1/router.py` | action debug router | 005 |
| H-A8 | 评估上下文切片 | `app/services/evaluation_context.py` | EvaluationContext 增 `action: dict \| None`（`_collect_action` 装配，默认 None） | 005 |
| H-A9 | 记忆候选投递 | `app/services/action/memory_bridge.py` | 只调用既有 memory 仓储/policy，不改 extractor | 007 |

## 4. 与 V8 World Update Interpreter 的分工

| | V8 interpreter（既有） | V9 Action System（新增） |
|---|---|---|
| 触发 | 每轮用户消息（被动解释） | 检出的行动意图（主动执行） |
| 输入 | 消息文本 + 世界现状 | ActionIntent + 闸门裁决 + 能力 schema |
| 输出 | 世界迁移提案（拿/吃/放回…） | ActionPlan（带参数、可审计、可重试） |
| 副作用 | 直接应用迁移，无记录 | ActionRecord 全程留痕 + 效果清单 |
| 时序 | 第 8 步 | 第 9 步（在 interpreter 之后，见下） |
| 失败语义 | 宁可不迁移（不造事实） | 宁可不执行（不虚假承诺），失败留痕 |

**执行顺序契约**：第 9 步在第 8 步之后运行——用户"帮我买牛奶放冰箱"先由 interpreter 造出牛奶实体（若命中规则），planner 的 world_action 检出会因"世界已满足"而闸门否决（G6 场景适宜：效果已达成），避免双重执行。两者对同一消息可能同时命中的场景矩阵与优先规则见 world-integration.md §5。

## 5. 失败与降级契约（与 V7.5/V7.8/V8 同源）

1. V9 任何异常（检出、闸门、执行、整合、写库）只 log + 降级：**回复不受影响**，post_process 第 9 步失败不影响其余步骤。
2. 检出不确定 → 不产生 intent（宁缺毋滥）；参数不全 → intent 置 ambiguous 不执行（回复如旧，不虚假承诺）。
3. 能力执行失败 → ActionRecord 置 failed（attempt + 退避重试，超限终态）；失败行动进入下一轮行动上下文段（待补救），由评估规则 action_failed_unreported 观测"失败却宣称成功"。
4. `action_enabled=false` 或数据缺失（迁移未跑/表为空）→ 全部挂载点短路：无检出、无第 9 步、无 action_ctx、无 action_facts。
5. 单条 ActionStep 失败不影响同 plan 其余 step（MVP 单步，多步预留）；结果整合单通道失败不影响其他通道。
6. per-user 写锁内执行（复用 `post_process.get_user_write_lock`），与聊天落库/主动消息互斥——行动创建的世界事件不会与进行中的 turn 交错。

## 6. 开关矩阵（action_* 配置组，完整清单见 tasks.md V9-001）

| 开关 | 默认 | 作用 |
|---|---|---|
| `action_enabled` | **false** | 总开关；false 时全部挂载点短路（回到 V8.5 行为）。出厂关闭，人工回归后开启 |
| `action_detector_enabled` | true | 确定性检出开关（独立于总开关，便于只观测不执行） |
| `action_llm_assist_enabled` | false | LLM 辅助意图澄清（采样），默认关——成本与确定性双考虑（V8 同款） |
| `action_plan_max_steps` | 1 | 计划步数上限（MVP 单步；多步留待后续版本） |
| `action_max_active_per_user` | 5 | 单用户非终态行动上限，超限拒新建 |
| `action_dedupe_window_hours` | 24 | 同 (user, action_type, dedupe_key) 去重窗口 |
| `action_execution_timeout_seconds` | 10 | 单次能力执行超时 |
| `action_retry_max_attempts` | 2 | 可重试失败的最大尝试次数（含首次） |
| `action_retry_backoff_seconds` | 30 | 重试退避基数（指数） |
| `action_context_char_budget` | 400 | 行动段 prompt 字符预算 |
| `action_memory_policy_enabled` | true | 行动 → 记忆候选投递 |
| `action_memory_policy_json` | 内置边界表 | 行动类型 × 是否沉淀 × importance 映射 |
| `action_relationship_enabled` | false | 行动 → 关系信号（默认关，见 relationship-impact.md） |
| `autonomy_action_enabled` | false | 自治直接产 ActionPlan 分支（默认关，见 autonomy-integration.md） |
| `action_record_retention_days` | 180 | 行动记录保留期 |

测试默认约定：action 夹具显式开启 `action_enabled` 并播种所需世界数据；既有测试在 `action_enabled=false` 下运行 → 行为与 V8.5 全量一致。

## 7. 验收底线（全局）

- `action_enabled=false` 时既有全量测试（1120+）零回归；`tests/golden/` 字节不变——"没改行为"的机器可证证据。
- `action_enabled=true` 时**非行动类消息**（检出不命中）全链路字节不变——V9 只在确凿行动意图上改变行为。
- 回复宣称与 ActionRecord 一致性由评估兜底：宣称完成时行动无 succeeded 记录 → action_overclaim（warning）。
- V9 对 Character 状态（character_state / relationship_state / emotion_history 直写路径）**零写入**——关系影响只经 RelationshipEvent 投递通道（H-A8 之外的直接写一律禁止），以测试断言固化。
- 行动产生的世界/记忆副作用全部走既有写通道（world_engine / memory_repository），V9 不新增事实存储（仅 action_records 审计表）。
