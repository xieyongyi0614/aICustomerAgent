# V3.0.0 Agent Runtime 人工回归清单

> 配套：`docs/version/v3.0.0/acceptance-report.md`（自动化验收结果）
> 上游：`docs/version/v3.0.0/tasks.md` §4.2（灰度顺序）· §6.1（版本级 Gate）· `tasks/RT-020.md` §5 步骤 6
> 执行时机：**G6 / G7 收口之后**，发布之前
> 执行人：具备真实模型与真实 PG 实例的工程师（本清单全部场景**无法**由内存 SQLite + FakeLLM 覆盖）

---

## 1. 适用范围与前置

### 1.1 本清单覆盖什么

自动化测试（`tests/v30` 357 例 + 全量套件）已覆盖**契约、边界、零写入、降级语义、影子路径**。本清单只覆盖**自动化无法判定**的六类场景：真实模型输出质量、真实通道投递、真实 PG 迁移、跨进程/跨重启行为、开关灰度与回滚、以及「同一句话在纳管前后是否真的没变」。

### 1.2 前置条件（缺一不可）

| # | 前置 | 校验方式 |
|---|---|---|
| P-1 | 真实 PG 16 实例可连；`TEST_DATABASE_URL` 已配置 | `alembic current` 能读出 `0052` |
| P-2 | 真实 LLM 凭据已配置（`.env` 中 provider key） | 一次前台对话能返回非兜底文案 |
| P-3 | 飞书应用凭据齐全（`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / 验签与 Encrypt Key 按部署形态） | 飞书后台「事件订阅」回调可达 |
| P-4 | **所有 `runtime_*` 开关为默认值**（见 §4 影子矩阵） | `RUNTIME_*` 未出现在部署 `.env` 中 |
| P-5 | 迁移链尾 `0052`，且 `alembic upgrade head` 已执行 | `alembic heads` 输出 `0052 (head)` |
| P-6 | 备份当前库 | 可在 §5 回滚验证后恢复 |

> ⚠️ **P-4 是硬前置**：本清单 §2 的 A~F 全部要求**先在全 off 下跑一遍**（对照基线），再按 §3 逐级开启重跑。跳过对照则无法判定「开关是否改变了行为」。

---

## 2. 六类端到端场景清单

> 记录模板见 §9。每场景需记录：**执行时间 / 开关状态 / 观测点 / 实际结果 / 与预期是否一致 / 证据（截图 / run_id / 日志行）**。

### A. 前台多轮对话（Web 通道）

| # | 步骤 | 预期观测 | 判定 |
|---|---|---|---|
| A-1 | 开关全 off，Web 控制台连发 5 轮同一会话消息 | 每轮有流式 token；`turn_meta` 键集与顺序与 V2.6.1 一致；无报错 | 对照基线 |
| A-2 | 开启 `RUNTIME_SESSION_TRACKING_ENABLED=true`，重发同样 5 轮 | 回复内容**逐字节一致**（同一随机种子下）；`loop_runs.session_id` 有值 | 等价 |
| A-3 | 查 `SELECT id, session_id, run_kind, status, steps FROM loop_runs ORDER BY started_at DESC LIMIT 5` | 5 行 `run_kind='foreground_chat'`，`status ∈ {done, degraded}`，`steps` 含六段环节落账（`phase` 可由 `STAGE_TO_PHASE` 推出） | 台账完整 |
| A-4 | 查 `SELECT count(*) FROM runtime_traces WHERE correlation_id = '<run_id>'` | ≥ 1（RT-019 起 `correlation_id` 落库；此前恒为 NULL） | 可观测 |
| A-5 | 用 `trace_query.by_run_id('<run_id>')`（或 `/api/v1/debug` 对应端点）还原该轮 | 段顺序 = Profile 声明顺序；每段有 `duration_ms`；无段缺失 | G10 |
| A-6 | 人为让一次回复失败（如临时断网 / 非法 key） | 前台**不崩**；Run 记 `aborted` 或 `degraded`；错误落 Trace；HTTP 错误映射与 V2.6.1 一致 | G8 |

### B. 后台 tick 观察（自治周期）

| # | 步骤 | 预期观测 | 判定 |
|---|---|---|---|
| B-1 | 全 off，观察一个完整 tick 周期（≥ `life_loop_*` 间隔 ×2） | 维护步按既有清单与间隔执行（`world_maintenance` / `world_simulation` / `action_retry` / `action_schedule` / `outbox_consume` / `trigger_reconcile`） | 零改动 |
| B-2 | 开启 `RUNTIME_AUTONOMOUS_CYCLE_ENABLED=true`，重跑一个 tick 周期 | `loop_runs` 出现 `run_kind='autonomous_tick'`；段序列 = `autonomous_tick` Profile 声明（含 `reflection_check` 在 `decision` **之前**）；终态与 legacy 路径一致 | 等价 |
| B-3 | 制造「无 due 工作」的空转 tick | **0 LLM 调用**（`llm_call_repository` 无新增行）；Run 仍落账（或按既有语义跳过） | G9 空转 |
| B-4 | 查 `decision` 段是否被执行 | `steps` 中 `decision` 状态 ∈ `{ok, skipped}`；`skipped` 时 `skip_reason ∈ {quota_circuit_open, step_budget, gateway_denied}` | 三道闸 |
| B-5 | 观察 budget 超限（把 `life_loop_cycle_llm_budget` 调到 0） | `decision` 段 `skipped` + `skip_reason='step_budget'`；Run 记 `degraded` 而非 `aborted`；**零 LLM 调用** | G9 预算 |

### C. 主动行为投递

| # | 步骤 | 预期观测 | 判定 |
|---|---|---|---|
| C-1 | 全 off，触发一次主动行为（或用既有触发条件等待） | 投递经既有端口；`proactive_actions.dedupe_key` 生成 | 对照基线 |
| C-2 | 开启 `RUNTIME_OUTBOUND_GATEWAY_CHANNELS=feishu`，重复 C-1 | 投递经 Outbound Gateway（日志出现 `deliver_proactive`）；外部收到**恰好一条**消息 | RT-014 |
| C-3 | 同 `dedupe_key` 重复触发 | **不重复投递**（`feishu_deliveries` 幂等台账命中）；返回 `SendResult(ok=False, ...)` 而非抛异常 | 幂等 |
| C-4 | 在免打扰窗口内触发 | **不产生投递**（`_should_skip_user_facing` 既有判定零差异） | RT-017 |
| C-5 | 查 `runtime_traces.correlation_id = 'proactive:<dedupe_key>'` | ≥ 1 行；`trace_query.by_correlation` 可串出 trace + decision + action | 可追溯 |

### D. 渠道切换（飞书纳管）

| # | 步骤 | 预期观测 | 判定 |
|---|---|---|---|
| D-1 | `RUNTIME_INBOUND_GATEWAY_CHANNELS=''`（未纳管），向飞书机器人发一条私聊 | 正常回复；记录 `session_id` 派生结果（预期 `feishu:<open_id>`）、回复内容、`user_id` | 基线样本 |
| D-2 | 改为 `RUNTIME_INBOUND_GATEWAY_CHANNELS=feishu` 并重启 | 发**同一条**消息 | — |
| D-3 | 比对 D-1 与 D-2 | `session_id` / `user_id` / 回复内容 **逐字节一致**；`runtime_traces` 新增行 `correlation_id` 非空 | **等价断言（RT-013 核心）** |
| D-4 | 再改为 `feishu,web` | Web 与飞书入站产出**同 schema** 的 `RuntimeInput`（仅 `source` / `channel_identity` 不同） | 渠道无关 |
| D-5 | 飞书侧异常路径：重复 `event_id`、超长消息、非文本消息、限流触发 | 去重命中静默吞掉；非文本回兜底文案；限流返回 **200 + 兜底文案**（**不得**改回 429）；消息不丢失 | 飞书闸门 |
| D-6 | 多实例（`FEISHU_INSTANCE_COUNT=2`） | 启动期硬闸要求同时声明 `FEISHU_INGRESS_SHARDED_ROUTING_ENABLED` + `FEISHU_DEDUPE_PERSISTENT_ENABLED`；非本分片返 **503**（**不得**返 200）；回调地址指向 `/api/v1/feishu/ingress/events` | 分片路由 |

### E. 孤儿 Run 恢复

| # | 步骤 | 预期观测 | 判定 |
|---|---|---|---|
| E-1 | 手工插一条 `loop_runs`：`status='running'`、`started_at = now() - 2h`、`steps=[{"step":"perception","status":"ok"}]` | — | 造现场 |
| E-2 | 等待一个维护步周期（或直接调 `recovery.sweep_orphan_runs()`） | 该 Run 变 `aborted`；`steps` 保留原 `perception` 且追加 `{"step":"orphan_sweep","status":"error","error":"orphan_timeout"}` | G11 |
| E-3 | 再次扫掠 | **返回空**（幂等），`orphan_sweep` 不重复追加 | 幂等 |
| E-4 | 造一条**新鲜**的 `running`（`started_at = now()`） | **不被扫掠**（阈值 30 分钟） | 不误杀 |
| E-5 | 重启进程 | **零自动重放**：无未完成 Run 被重新执行；不恢复 Run 内中间态 | 不重放 |
| E-6 | 用同一 `session_id` 发下一条消息 | 开启新 Run（续接 Session），不复用旧 `run_id` | 恢复语义 |

### F. 回放取材抽查

| # | 步骤 | 预期观测 | 判定 |
|---|---|---|---|
| F-1 | 任取一次前台 Run 与一次后台 Run 的 `run_id` | `trace_query.by_run_id` 返回完整段序列 + 耗时 + 降级 + `ErrorKind` | G10 |
| F-2 | `trace_query.replay_bundle('<run_id>')` | 含 `snapshot_anchor`（`agent_state_snapshots` 锚点）+ `decisions` + `actions` + `state_changes` + `traces` | 取材完整 |
| F-3 | 调用前后比对全库行数 | **完全不变**（只读，零写入） | AC4 |
| F-4 | 取一次主动行为的 `proactive:<dedupe_key>` | `by_correlation` 串出 trace + decision + action 三层 | 因果链 |
| F-5 | 观测保留期：把 `observability_trace_retention_days` 调到 1，跑一次 `prune_all()` | 带 `correlation_id` 的旧行**同样被清理**（新字段不影响清理策略） | 保留期零变化 |

---

## 3. 开关灰度顺序（tasks.md §4.2，严格按序）

每级开启后**观察一个完整周期**再进下一级；每级记录 §9 模板。

| 序 | 开关 / 动作 | 观察点 | 回退动作 |
|---|---|---|---|
| 1 | `RUNTIME_SESSION_TRACKING_ENABLED=true` | 只加列与写值，读路径不变；`loop_runs.session_id` 有值 | 置回 `false`（列保留 NULL，无迁移回退） |
| 2 | `RUNTIME_STATE_VERSIONING_ENABLED=true` | 读路径增强；同 Run 内 `snapshot_version` 一致 | 置回 `false` |
| 3 | `RUNTIME_CONTEXT_FREEZE_ENABLED=true` | Run 内上下文冻结，内容哈希稳定 | 置回 `false` |
| 4 | `RUNTIME_EVENT_BUS_ENABLED=true` | 旁路通知；订阅者失败不影响主循环 | 置回 `false` |
| 5 | `RUNTIME_INBOUND_GATEWAY_CHANNELS=feishu` → 观察 → `feishu,web` | 见 §2 D 等价断言 | 置回 `''` |
| 6 | 前台收编（RT-015）随第 5 级**同批发布，不单独灰度** | `turn_meta` / 流式 / 错误映射逐字段一致 | 同批回退 |
| 7 | `RUNTIME_AUTONOMOUS_CYCLE_ENABLED=true` | 见 §2 B | 置回 `false` |
| 8 | `RUNTIME_LOOP_OPTIONAL_STAGES=plan` → 观察 → 追加 `reflect` + `RUNTIME_REFLECT_IN_LOOP_ENABLED=true` | Plan / Reflect 段进入循环；Insight 与周期任务不重复 | 置回 `''` |
| 9 | `RUNTIME_ORPHAN_RUN_SWEEP_ENABLED`（建议始终 `True`） | 见 §2 E；仅阈值为可调项 | 置回 `false` |

**回滚顺序：与开启顺序严格逆序。** 开关关闭后必须回到 V2.6.1 行为（各 Task 已断言），故**回滚不需要数据迁移回退**——`0052` 两列可空，保留不回滚。

---

## 4. 影子矩阵（Flag 全 off 三重对照）

### 4.1 默认值核对表（11 字段）

| 字段 | 默认 | 部署侧必须为 |
|---|---|---|
| `RUNTIME_SESSION_TRACKING_ENABLED` | `False` | 未设置 / `false` |
| `RUNTIME_STATE_VERSIONING_ENABLED` | `False` | 未设置 / `false` |
| `RUNTIME_CONTEXT_FREEZE_ENABLED` | `False` | 未设置 / `false` |
| `RUNTIME_EVENT_BUS_ENABLED` | `False` | 未设置 / `false` |
| `RUNTIME_LOOP_OPTIONAL_STAGES` | `""` | 未设置 / 空 |
| `RUNTIME_REFLECT_IN_LOOP_ENABLED` | `False` | 未设置 / `false` |
| `RUNTIME_INBOUND_GATEWAY_CHANNELS` | `""` | 未设置 / 空 |
| `RUNTIME_OUTBOUND_GATEWAY_CHANNELS` | `""` | 未设置 / 空 |
| `RUNTIME_AUTONOMOUS_CYCLE_ENABLED` | `False` | 未设置 / `false` |
| `RUNTIME_ORPHAN_RUN_TIMEOUT_MINUTES` | `30` | 未设置 / `30` |
| `RUNTIME_ORPHAN_RUN_SWEEP_ENABLED` | `True` | 未设置 / `true`（**唯一默认 on**，RT-018 定义） |

> env 名 = 字段名大写（`_shared.py` 无 alias 层）。**改名必须同批同步部署侧 `.env`**，否则 `extra="ignore"` 会静默吞掉、闸门假关。

### 4.2 三重对照（必做）

| 对照 | 做法 | 判据 |
|---|---|---|
| ① 全 off vs V2.6.1 代码 | 全 off 部署 + 全量回归 | 与 V2.6.1 逐字节一致（影子路径） |
| ② 单开 vs 全 off | 逐级单开（§3），比较同一输入的输出 | 除该开关声明的能力外，无其他行为差异 |
| ③ 全开 vs 单开 | 全开后比较 | 无相互干扰 / 无二次写 / 无重复投递 |

### 4.3 零版本前缀复核

```bash
grep -rn "v30_\|V30_" apps/backend/app apps/backend/tests    # 期望 0 命中
grep -n "env_prefix\|alias" apps/backend/app/core/settings/_shared.py   # 期望无 env_prefix / 无 alias
```

---

## 5. 回滚验证

| # | 步骤 | 预期 |
|---|---|---|
| R-1 | 按 §3 逆序把全部 `runtime_*` 置回默认 | 服务正常启动；无启动期硬闸报错 |
| R-2 | 重跑 §2 A-1 / B-1 / C-1 / D-1 | 与 V2.6.1 基线**逐字节一致** |
| R-3 | 保留 `0052` 两列不回滚 | `loop_runs.session_id` / `runtime_traces.correlation_id` 为 NULL；既有查询不受影响 |
| R-4 | 若需回滚迁移：`alembic downgrade 0051` | 两列被删除；服务可启动；无数据完整性错误 |
| R-5 | 回滚后再 `alembic upgrade head` | 回到 `0052`，幂等无残留 |

---

## 6. Gate 判定清单（人工侧）

| Gate | 人工判定点 | 关联场景 |
|---|---|---|
| G6 迁移可逆 | `alembic upgrade head` / `downgrade 0051` 双向空跑 | R-4 / R-5 |
| G7 零回归 | 全 off 与 V2.6.1 逐字节一致 | §4.2 ① + §2 A-1 / B-1 / C-1 / D-1 |
| G9 预算纪律 | 空转 0 LLM；超预算降级不抛错 | B-3 / B-5 |
| G10 全链可观测 | 前台 / 后台各一次 Run 可由 `run_id` 还原 | A-5 / F-1 |
| G11 恢复语义 | 孤儿收敛幂等；重启零重放 | E-2 / E-3 / E-5 |
| G12 多渠道可扩展 | 纳管前后逐字节等价 | D-3 |
| 边界不变量 1/2 | 域写只经合法通道；查询零写入 | F-3 |
| 边界不变量 6 | `ChannelAdapter` 契约零改动 | D-1~D-4 未改任何 Adapter 签名 |
| 边界不变量 8/9 | 前后台同一循环；无第二套 Pipeline | A-3 / B-2 段序列同源 |

---

## 7. 兼容性红线（评审一票否决项）

1. 前台 `turn_meta` 键集 / 顺序 / `done` 字段 / 错误 → HTTP 映射发生任何变化。
2. 飞书入站限流改回 **429**（会导致飞书重投已去重的 `event_id` → 消息永久丢失）。
3. 飞书非本分片返回 **200**（而非 503）。
4. 任何域被 Runtime 直写（`memories` / `relationship_state` / `personality_state` / `world_*` / 计划）。
5. 引入 MQ / Redis / Event Sourcing / 分布式锁 / 第二套 Pipeline / LangGraph / CrewAI。
6. 新增表承载执行语义（超出 `0052` 两列）。
7. Channel 直接控制 Runtime（绕过 `RuntimeInput` / `SessionContext` 契约）。

---

## 8. 上线前待办

| # | 待办 | 归属 |
|---|---|---|
| ~~1~~ | ~~G6：配 `TEST_DATABASE_URL`，执行 `0052` 双向空跑~~ → **已执行并通过**（真实 PG 16.15；过程中修复 `0045` 发布阻断缺陷，见 `acceptance-report.md` §缺陷记录 D-1） | 已完成 |
| 2 | G7：既存 18 项失败清零或显式豁免登记 | 后端（独立缺陷簇） |
| 3 | 本清单 §2 A~F 六类场景全部执行并留痕 | 人工回归 |
| 4 | 运维侧：飞书回调地址指向 `/api/v1/feishu/ingress/events`；配置 `FEISHU_ROUTER_INSTANCE_URLS`；router 与实例 `FEISHU_ENCRYPT_KEY` 一致 | 运维 |
| 5 | PG 用例债（`acceptance-report.md` D-2 / D-3）：修 `test_channel_identity` 的 0036 快照口径、补 `test_http_lifecycle_on_postgres` 的 memory2 monkeypatch、`test_ws002_migration` fixture 加前置清库 | 后端 |
| 6 | 环境侧：容器 `template1` 排序规则已刷新（D-4）；**新环境部署时若出现 `collation version mismatch` 需同样处理**，否则整批 PG 用例静默 skip | 运维 |
| 7 | 回写 `docs/current-system-architecture-baseline.md`（需用户确认） | 后端 |
| 8 | 更新 `AGENTS.md` / `apps/backend/AGENTS.md`：版本入口指向 V3.0.0；迁移链尾 `0050` → `0052`（需用户确认） | 后端 |
| 9 | C3 分区队列（未修登记，演进选项） | 排期 |

---

## 9. 记录模板

```text
场景：<A-2 前台多轮（session tracking on）>
时间：<YYYY-MM-DD HH:MM>
开关状态：RUNTIME_SESSION_TRACKING_ENABLED=true，其余默认
观测点：回复内容 / loop_runs.session_id / runtime_traces.correlation_id
实际结果：<逐字节比对结论；run_id 列表；SQL 输出摘要>
与预期是否一致：是 / 否
不一致时的判定：回归 / 既存 flaky / 新发现缺陷（附 run_id 与日志行）
证据：<截图路径 / run_id / 日志行号>
```

---

> **文档结束**。本清单与 `acceptance-report.md` 构成 V3.0.0 的完整验收证据；自动化可判定部分见前者，人工可判定部分见后者。
