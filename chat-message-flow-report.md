# 对话流程梳理报告

> 本文基于当前代码实现（`channels/`、`api/v1/chat.py`、`application/chat_pipeline.py`、`application/agent_runtime/profiles.py`、`application/post_process.py`、`chains/answer_chain.py`）重新梳理，不参考旧的 `chat-message-flow.html`。

## 一、流程全景（一句话）

一次用户消息，先由**通道层**归一为通道无关消息，再进入**前台 9 段对话管线**（上下文装配 → 四链并行检测 → 决策收敛 → 流式回答 → 落库交接），回答产出后由**后台 13 步后处理**异步完成状态/记忆/世界/行动等沉淀；前台回答与后台沉淀解耦，后台失败不影响已产出的回答。

```
User Message
  → 通道归一（Web REST / 飞书 Webhook → InboundMessage）
  → 前台 9 段管线（foreground_chat Profile，唯一 critical = 流式回答）
  → 流式输出（turn_meta → delta* → done）
  → 后台 13 步后处理（异步、独立容错）
```

## 二、总体架构与入口

- 两条通道最终都收敛到 `chat_pipeline.stream_chat`，对话逻辑唯一，通道只做「入站归一 + 出站发送」，不包含 Agent / Memory / World 逻辑。
- 前台整链被包裹为一个 `foreground_chat` Run（`loop_runs` 台账记账），由 `AgentLoop` 按 Profile 声明驱动段序列。

## 三、前台 9 段详解（每段作用）

| # | 段 | 作用 |
|---|---|---|
| 1 | perception | 感知锚点，入站已由网关归一，无额外业务（对齐自治 Profile 的占位段） |
| 2 | context_assembly | 装配一切上下文：Agent 状态快照、世界切片（只读、失败降级）、会话历史/摘要/记忆召回、场景状态，并选出本轮目标 |
| 3 | turn_decisions | 四条 LLM 链**并行**执行（角色路由 / 轮次分析 / 场景意图 / 意图决策），单链失败互不拖累、逐项降级 |
| 4 | mode_stabilize | 模式稳定：候选模式 vs 已确认模式，稳定器 R5 抑制「一句话就切语气」的抖动 |
| 5 | scene_resolve | 场景收敛 + 意图确定性校验 + 前台决策管线（目标栈只读，胜者恒为「回复用户」） |
| 6 | behavior_resolve | 决定「怎么回应」：关系上下文 → 行为引擎（策略/预算/习惯/解锁）→ 风格契约 |
| 7 | action_planning | 检出行动意图（可选），发出首帧 `turn_meta`（模式/分析/场景/意图/目标/行为） |
| 8 | reply_generation | **唯一 critical 段**：流式生成回答，逐 token 产出，可选库存 grounding 回溯修正 |
| 9 | record_handoff | 落库本轮、复位主动行为、调度后台后处理、观测收口、发出 `done` 帧 |

## 四、后台 13 步后处理（作用）

回答产出后异步执行，**每步独立容错**，per-user 写锁内串行：

| 步骤 | 作用 |
|---|---|
| scene_update | 场景状态更新持久化 |
| state_update | 角色状态（情绪/能量/强度）应用保存 |
| goal_review | 目标评审（创建/完成/过期/取消） |
| summary | 会话摘要更新（达阈值） |
| memory_extract | 记忆提取（显式命令优先，四源幂等入 candidates） |
| ledger_extraction | 账本抽取候选（零写库） |
| ledger_confirmation | 账本确认挂接（待确认登记/超时清理） |
| budget_observer | 行为预算观测（违规告警） |
| evaluation | 回合评估（规则 + LLM Judge 采样） |
| world_update | 世界状态迁移 + 用户处境检出 + 物品录入 |
| character_action_sync | 角色动作提取→校验→执行→写世界 notes |
| action_planning | 行动六闸门→计划→执行→整合 |
| memory_evaluate | 收尾记忆评估（本轮候选同轮转正） |

## 五、流式输出协议

NDJSON 帧序列：`turn_meta` → `delta`（增量 token，多次）→ `reply_replace`（可选，grounding 修正）→ `done`；工具步骤帧随时插入。

## 六、优点

1. **单管线唯一真相**：段序列只在 `profiles.py` 声明，前台/自治共用同一套循环内核，无第二套 Agent Pipeline，避免逻辑分叉。
2. **前台/后台解耦**：回答先产出（读进链、写流出链），13 步后处理异步独立容错，任何后台失败都不影响用户体验。
3. **四链并行 + 逐项降级**：路由/轮次/场景/意图四条 LLM 链并行且互不拖累，任一失败都走归一降级而非整体崩溃，鲁棒性强。
4. **关键段最小化**：只有 `reply_generation` 是 critical，其余段失败可跳过/降级，故障面收敛到最小。
5. **一键回退开关（已删除）**：`runtime_foreground_loop_enabled` 与线性旧链已于 2026-10-15 物理删除，前台固定走 AgentLoop，回退 = git revert。
6. **分层单向依赖**：通道/编排/领域服务/仓储/核心严格分层，通道层零业务逻辑，扩展新通道不动核心。
7. **可观测性贯穿**：全程 trace 记录（段耗时、LLM 首 token、token 用量、决策审计），排查与成本观测能力强。

## 七、缺点 / 风险

1. **闭包式段本体**：`run_chat_pipeline` 内 9 个段是捕获 25+ `nonlocal` 中间值的闭包，单函数体量巨大，可读性与单测粒度偏弱，中间值只活在本次 Run 内难以独立验证。
2. **延迟叠加**：前台回答前要串行完成「目标选择 + 四链并行 + 决策管线」，LLM 调用次数多（4 条并行链 + 1 条回答链），首 token 时延与成本偏高。
3. **双重路径并存**：AgentLoop 与线性旧链两套驱动、以及 `services/agent_service` 兼容壳仍在，属已知技术债，新同学易误入旧路径。
4. **后台步骤间隐式顺序依赖**：13 步按序执行，部分步骤（如 world/action 产物 → memory_evaluate 收尾评估）靠「后置补一次」来修正可见性，步骤间耦合与执行时机较隐晦。
5. **grounding 重写需整段缓冲**：inventory grounding 的 rewrite/annotate 模式必须缓冲完整回复才能纠错，牺牲了流式即时性，且客户端需支持 `reply_replace` 替换帧。
6. **账本/记忆等旁路收敛复杂**：确定性链路与 LLM 链路并存（如记账双写曾致重复入账），靠「待确认让位」等细节钩子保证单写面，规则分散、理解成本高。

## 八、小结

当前对话流程整体是一套**「通道归一 → 单管线前台 9 段 → 流式回答 → 后台异步沉淀」**的清晰分层架构，核心优点在于单管线唯一真相、前后台解耦与逐项降级的鲁棒性；主要代价是闭包式实现导致的可读性、多 LLM 链带来的时延/成本，以及双重路径与后台隐式耦合带来的维护成本。整体方向合理，后续可优先收敛兼容壳/旧链与段实现的模块化拆分。
