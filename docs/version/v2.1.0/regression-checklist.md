# V2.1.0 Agent Evolution Regression Checklist（真实模型人工回归）

> 前置：AGENT-001~007 已实现。真实模型下验证 Evolution Loop 全链贯通与三条成长主线。
> 执行前：`alembic upgrade head`（链尾现为 0048）。
> **本清单已随 `vXX_` 开关体系删除改写**：V2.1.0 的功能不再靠 env 打开。

## 1. 生效确认（开关已删除，功能无条件生效）

四个 Flag 的配置面已消失、ON 路径常开：`agent_runtime_enabled`、`goal_stack_enabled`、`agent_metrics_enabled`、`personality_evolution_enabled`。
`unified_run_enabled` 已随 F.12 固化删除：前台 chat 恒包裹为 `foreground_chat` Run 台账（无配置面）。
仍在场的只有 `foreground_gateway_enforced`（按裁决保留门控，见 F.10）。

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| P1 | 起服务并看启动日志 | 出现 `agent evolution worker 已启动（指标快照 + 人格编译 + goal rebalance）`——该 task 原受 `enabled()` 门控，现无条件注册 | ☐ |
| P2 | 查部署侧 `.env` 副本 | **不得残留** `V21_*` 或 `AGENT_RUNTIME_ENABLED` / `GOAL_STACK_ENABLED` / `AGENT_METRICS_ENABLED` / `PERSONALITY_EVOLUTION_ENABLED` / `UNIFIED_RUN_ENABLED`：`V21_*` 会触发启动告警，无前缀的旧键则**静默无效** | ☐ |
| P3 | 确认前台恒收编 | 每次 chat 后 `loop_runs` **应**出现 `run_kind=foreground_chat` 行（F.12 固化后无开关可关） | ☐ |
| P4 | 后台自治已换实现 | `autonomous_tick` 台账行的 `run_kind` / `profile` 字段有值（v2.0.0 的 `life_loop._run_user_cycle` 已删除，唯一入口是 `agent_runtime.run_autonomous_cycle`） | ☐ |

## 2. 基础主线下钻

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| A1 | 发送一条用户消息 | 回复正常流式；`loop_runs` 出现 `run_kind=foreground_chat` 行（kind=chat），profile 含 foreground 档 | ☐ |
| A2 | 观察回复内容 | 上下文含 `【当前感兴趣】`/`【当前关注】` 段（有来源时），角色表达自然 | ☐ |
| A3 | 关闭灯等后台 tick 触发（闲置/到期 trigger） | `loop_runs` 出现 `autonomous_tick` 行；steps 含 perception→state_snapshot→goal_check→goal_stack→…→world_experience | ☐ |
| A4 | 触发主动行为 | 主动消息经管线选择（decision_records.candidates 可见候选来源/六维得分/闸结果/落选清单） | ☐ |
| A5 | 断网/超预算场景 | Gateway 熔断：后台 decision skip（gateway_denied / quota_circuit_open），Run 终态 degraded；前台软降级不报错 | ☐ |
| A5.1 | **固化专项（本批新增风险面）**：连跑 ≥20 个自治周期（把 `life_loop_tick_seconds` 调小即可），统计 decision 步骤的 `skip_reason` 分布 | `gateway_denied` 占比可解释（对应 run 级 LLM 预算与日配额熔断）。**占比 > 5%、或主动消息/目标推进量明显低于对照轮 → 判 FAIL**：这道 run 级 Gateway 闸是本次固化新引入的静默跳过来源，且软模式豁免只覆盖 `budget_type == "foreground"`，自治能力不在其内 | ☐ |
| A6 | 等待慢时钟 tick（默认 1h；可将 `AGENT_EVOLUTION_INTERVAL_SECONDS` 调小验证） | 日志出现 agent evolution worker；`agent_metric_snapshots` 当日窗口落行（同窗口不重复落）；`personality_state.current` 与 `evolution.ledger` 随时间变化 | ☐ |
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
| R1 | ~~逐档关闭 ④→③→②→①~~ **已不可行**：四个 Flag 无配置面 | 回滚 = `git revert` 去门控提交（F.10 记的 `51ffca8` 与 A 组提交），因此本清单**必须先在独立库上跑完**再切主库 | ☐ |
| R2 | 对照轮（与固化前留档的同一组输入比对） | 前台/后台/维护/投递/评估/记忆的行为差异**只应**出现在「V2.1.0 能力开始生效」这一预期范围内；范围外差异即 FAIL | ☐ |
| R3 | 迁移回滚演练 | 本次改造零迁移（链尾 0048）；如需回退代码，旧行为随 `git revert` 恢复 | ☐ |

## 5. 上线判定

- 三条成长主线 + 基础主线（含 A5.1 固化专项）全部通过；
- 对照轮差异只落在「V2.1.0 能力开始生效」的预期范围内（§4 R2）；
- 性能预算（Snapshot ≤150ms、Run 台账 ≤20ms、前台 LLM ≤4 次、事件预闸 0 LLM）抽测达标；
- 遗留问题 Q1~Q5 裁决已回填 architecture.md 附表。
