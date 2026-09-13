# V2.1.0 Agent Evolution Regression Checklist（真实模型人工回归）

> 前置：AGENT-001~007 已实现（迁移链尾 0043）。真实模型下验证 Evolution Loop 全链贯通与三条成长主线。
> 执行前：`alembic upgrade head`（0043），`.env` 开启五 Flag。

## 1. 开关准备

| 环境变量 | 取值 | 目的 |
|---|---|---|
| `V21_AGENT_RUNTIME_ENABLED` | true（总闸） | 统一 Run 模型 + LLM Gateway |
| `V21_UNIFIED_RUN_ENABLED` | true | 前台对话收编为 foreground_chat Run |
| `V21_GOAL_STACK_ENABLED` | true | 四层目标栈 + 对齐度评分 |
| `V21_AGENT_METRICS_ENABLED` | true | Agent 级指标快照 + 演化议题 |
| `V21_PERSONALITY_EVOLUTION_ENABLED` | true | 人格轴演化 + Goal Rebalance |
| 对照轮 | 全部 false | 行为与 v2.0.0 逐字节一致 |

## 2. 基础主线下钻

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| A1 | 发送一条用户消息 | 回复正常流式；`loop_runs` 出现 `run_kind=foreground_chat` 行（kind=chat），profile 含 foreground 档 | ☐ |
| A2 | 观察回复内容 | 上下文含 `【当前感兴趣】`/`【当前关注】` 段（有来源时），角色表达自然 | ☐ |
| A3 | 关闭灯等后台 tick 触发（闲置/到期 trigger） | `loop_runs` 出现 `autonomous_tick` 行；steps 含 perception→state_snapshot→goal_check→goal_stack→…→world_experience | ☐ |
| A4 | 触发主动行为 | 主动消息经管线选择（decision_records.candidates 可见候选来源/六维得分/闸结果/落选清单） | ☐ |
| A5 | 断网/超预算场景 | Gateway 熔断：后台 decision skip（gateway_denied / quota_circuit_open），Run 终态 degraded；前台软降级不报错 | ☐ |
| A6 | 等待慢时钟 tick（默认 1h；可将 `V21_AGENT_EVOLUTION_INTERVAL_SECONDS` 调小验证） | 日志出现 agent evolution worker；`agent_metric_snapshots` 当日窗口落行（同窗口不重复落）；`personality_state.current` 与 `evolution.ledger` 随时间变化 | ☐ |
| A7 | 查前台 Run 台账与决策审计 | `loop_runs` 中 `profile.stages` 与 `steps` 阶段序列**完全一致**；`decision_records.candidates`（TURN_INTENTION 行）可见前台候选来源/六维得分/逐闸结果 | ☐ |

## 3. 成长主线（V2.1.0 核心）

### 主线 A：偏好跟随

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| A1 | 多轮明确表达某话题偏好 | Development preference 生成（Insight→编译，trace 可见 before/after） | ☐ |
| A2 | 后续对话与主动消息 | `agent_state_snapshots.interest_focus` 榜含该话题且回复内容跟随 | ☐ |

### 主线 B：人格缓变（谨慎→主动）

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| B1 | 构造多窗口正向证据（Insight 含主动类关键词） | `personality_state.assertiveness` 分阶段爬升，单窗 ≤ 限速 | ☐ |
| B2 | 观察行为 | 主动性类行为参数调制可见（trace before/after），行为仍像亚丝娜（bound 内） | ☐ |
| B3 | 查 Ledger | `evolution.ledger` 可沿时间线指认每次漂移的 Insight 来源 | ☐ |

### 主线 C：评估反馈

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| C1 | 注入低质量行动/回复样本 | `agent_metric_snapshots` 对应指标走低且趋势记录 | ☐ |
| C2 | 连续窗口越限 | 演化议题产生（日志 + Reflection 证据窗口触发） | ☐ |
| C3 | Reflection 产出 Insight | 编译后行为参数变化可观测；未过三闸则零变更 | ☐ |

## 4. 回滚与对照

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| R1 | 逐档关闭 ④→③→②→① | 每档既有套件全绿、无脏数据、行为面收敛 | ☐ |
| R2 | 全关对照轮 | 前台/后台/维护/投递/评估/记忆行为与 v2.0.0 逐字节一致 | ☐ |
| R3 | 迁移回滚演练 | 0043→0038 逆放可执行，旧行为恢复 | ☐ |

## 5. 上线判定

- 三条成长主线 + 基础主线全部通过；
- 对照轮零差异；
- 性能预算（Snapshot ≤150ms、Run 台账 ≤20ms、前台 LLM ≤4 次、事件预闸 0 LLM）抽测达标；
- 遗留问题 Q1~Q5 裁决已回填 architecture.md 附表。
