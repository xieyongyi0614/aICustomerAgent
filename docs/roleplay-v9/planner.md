# V9 Action Planner（检出、决策、计划装配）

> Planner 回答三个问题：**什么时候行动**（检出）、**该不该行动**（六闸门）、**怎么行动**（能力映射 + 参数装配）。全部确定性纯函数，零新增 LLM 调用——LLM 只在既有生成链里被调用，这是"Tool 是能力，不是逻辑"的第一体现：**Character Brain 的决策在 planner（代码 + 资产词表），不在工具里**。

## 1. ActionIntentDetector（检出器）

落点 `app/services/action/detector.py`，入口：

```text
detect_action_intent(content, scene_state, world_ctx=None, now) -> ActionIntent | None
```

- 纯函数 + 只读；门控 `action_enabled and action_detector_enabled`；任何异常返回 None（宁缺毋滥）。
- 挂载于 chat_pipeline 四链并行之后（H-A1），与既有 LLM 链互不依赖：检出失败不影响言语意图，言语意图失败不影响检出。

### 1.1 触发词表（角色资产 `app/character/asuna/action.py::ACTION_TRIGGER_LEXICON`）

| action_type | 触发模式（示例，完整表为角色资产） | 核心参数 |
|---|---|---|
| create_reminder | 提醒我 / 记得提醒 / 设个闹钟 / 到点叫我 / 别让我忘 | content（提醒内容）、due（时间短语） |
| cancel_reminder | 不用提醒了 / 取消提醒 / 算了别提醒 | target（提醒关键词） |
| remember_fact | 记住 / 帮我记着 / 我生日是 / 我的…是 | fact（事实原文） |
| create_object | 帮我买 / 去买 / 准备一个 / 拿一个…来 | object（物品名）、quantity |
| move_object | 把…放到 / 放进 / 收到…里 | object、location |
| use_object | 吃掉 / 喝掉 / 用掉 / 切开 | object、action 细分 |
| query_environment | 今天天气 / 外面多少度 / 现在几点了 | query 维度 |
| query_search | 搜一下 / 查一下…是什么 | query（MVP unavailable） |

词表纪律（与 V8 interpreter 同款，但门槛更高）：

1. **祈使优先**：触发词 + 用户主语（我/帮我/替我）才命中；角色自述或转述（"我昨天提醒过你"）不命中。
2. **问句守卫**："你能提醒我吗？"（询问能力）与"提醒我开会"（委托行动）用疑问语气 + 委托对象区分；无法区分时按 ambiguous 降级（可执行路径宁缺毋滥的反面——询问不应触发执行，存疑即不执行）。
3. **一轮至多一个 intent**：多条命中取词表优先级最高者，其余丢弃并记 evidence 摘要。
4. 词表属于**角色资产**（亚丝娜的说话习惯与能力边界），不是通用 NLP 词库——换角色换词表。

### 1.2 参数抽取

- **时间短语 → due_at**：扩展 V8 interpreter 既有解析（明天/后天/今晚，`services/world/interpreter.py`）为共享模块 `app/services/action/time_parse.py`（今晚 20:00 / 明天早上 8 点 / 半小时后 / 周五下午…），世界 interpreter 后续可反向复用。解析失败 → due 缺失进 `missing_params`。
- **内容/物品/地点**：触发词后置文本截取 + V8 实体名匹配（`world_engine.find_object_by_name` 语义的纯函数版），抽取结果进 params 草稿。
- 参数完整度判定：各 ActionType 的 `REQUIRED_PARAMS` 表（如 create_reminder 必需 content+due；query_environment 无必需）。缺必需 → confidence=ambiguous + missing_params 非空。

### 1.3 置信度与去重键

```text
confident  = 词表命中 + 必需参数齐全
ambiguous  = 词表命中但参数不全（不执行；evidence 供后续轮次澄清参考）
None       = 未命中（大多数轮次）
```

- `dedupe_key = sha1(action_type + 规范化核心参数)[:16]`——"提醒我晚上买牛奶"与"晚上提醒我买牛奶"同键；"提醒我开会"与"提醒我买牛奶"异键。

## 2. 六闸门（决策纯函数）

落点 `app/services/action/planner.py::evaluate_gates(intent, ctx) -> GateDecision`，按序短路（V7 八步裁决同构）：

| # | 闸门 | 条件 | 否决 → GateReason |
|---|---|---|---|
| G1 | 总开关 | `action_enabled` | disabled |
| G2 | 确凿度 | confidence == "confident" | ambiguous_params |
| G3 | 能力可用 | registry 已注册该能力且 action 存在 | capability_unavailable |
| G4 | 去重 | dedupe_window 内同键无 succeeded/scheduled 同型记录 | duplicate |
| G5 | 容量 | 非终态行动数 < `action_max_active_per_user` | quota_exceeded |
| G6 | 场景适宜 | 目标状态未达成（如 create_object 前世界已存在同名活跃物品 → 不重复创建；cancel 目标存在） | effect_already_satisfied / target_not_found |

- 全部输入为已读快照（世界现状 / 既有记录 / registry），闸门内零 IO。
- G6 是与 V8 interpreter 的**防双重执行闸**：interpreter 第 8 步已完成的迁移（如已造出牛奶），第 9 步行动闸门可见并否决（architecture.md §4）。
- 否决不静默：Record 置 cancelled + gate_reason，评估与 debug 端点可观测否决频率（调词表的依据）。

## 3. 计划装配

```text
assemble_plan(intent, gates_pass, registry) -> ActionPlan | None
```

1. **能力映射**：`ACTION_CAPABILITY_MAP: dict[ActionType, (capability, action)]` 纯函数表——

| ActionType | capability | action |
|---|---|---|
| create_reminder / cancel_reminder | reminder | create / cancel |
| remember_fact | memory | save |
| create_object / move_object / use_object | world_action | create / move / use |
| query_environment | environment_query | query |
| query_search | search | query（unavailable 占位） |
| send_notification | notification | send（unavailable 占位） |

2. **参数校验**：capability schema（capability-system.md §2）`validate(action, params)` 返回错误列表；非空 → 装配失败（理论不可达——G2/G6 已挡，防御性兜底，记 log）。
3. **参数定型**：时间短语已解析为 due_at、物品名已解析为 world entity 匹配候选、原始 evidence 保留进 intent 快照。
4. **plan 元数据**：goal_id 从本轮 selected_goal 透传（V6 动机审计）；expires_at = now + 5 分钟（第 9 步内瞬时执行，超时即 cancelled，防御调度堆积）。

MVP 单步（`action_plan_max_steps=1`）；steps 结构已支持多步（如"买牛奶并设提醒"= create_object + create_reminder），多步编排（依赖/失败回滚）留待后续版本，本阶段不做。

## 4. 与 V6 Intention 的边界

| | IntentionDecision / ValidatedIntention（V6） | ActionIntent（V9） |
|---|---|---|
| 问题 | 这轮**说什么**（言语行为） | 这轮**做什么**（状态改变） |
| 消费方 | behavior_engine → 预算/策略 → answer | planner → capability → 四通道 |
| 校验 | intention_policy.enforce（亲密度/场景规则） | 六闸门 |
| LLM | intention_chain 候选 | 纯函数词表 |

- **互斥并存，不互不改写**：一句话可同时含言语意图与行动意图（"别担心，我帮你设个提醒"→ comfort_user + create_reminder）。V9 不改写 ValidatedIntention，V6 不感知 ActionIntent。
- 行动检出**不进本轮 prompt**（H-A1 只入 turn_meta）——回复对行动一无所知，只能做进行时承诺；这是回复时序契约的基础（tool-integration.md §3）。
- 未来扩展点：`intention_policy` 可增规则"行动意图存在时言语意图让位"（如不再重复口头承诺），本阶段不做，留待评估数据说话。

## 5. LLM 辅助链（仅接口，默认关）

`app/chains/action_assist_chain.py`（P2）：ambiguous intent 的参数澄清建议（schema `ActionAssistResult`），走 build_structured_chain，采样启用（`action_llm_assist_sample_rate`），失败返回 None。**MVP 不实现**——ambiguous 的正确行为是"不执行 + 下轮自然澄清"（行动上下文段标注待补参数），零成本且无幻觉风险。
