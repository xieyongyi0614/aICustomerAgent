# 朝夕 AI Companion — 当前态架构理解

> **快照**：2026-10-23 · HEAD `e07669d7`（`feat/design-car-album`）
> **性质**：当前态（current-state），不是目标态、不是设计提案。
> **主证据**：`docs/current-system-architecture-baseline.md`（下称 baseline）+ 代码 / 配置 / 迁移。
> **产出技能**：`system-modeler`（主）+ `flow-visualizer`；格式基础：`c4model` + `graphviz`。

## 1. 这个系统是什么

面向个人用户的「角色对话 Agent」：让单一角色「亚丝娜」具备记忆、情绪与关系、目标与自主行为，并通过移动 App、Web API 与飞书机器人持续陪伴用户。除对话外，系统还承载一组生活域能力：账本、车辆、任务、简报，以及免商店自动更新。

业务上可以概括为四层价值：

| 用户价值 | 已实现的产品能力 |
|---|---|
| 被记得 | 7 类长期记忆、混合检索、反思与成长、跨会话/跨通道身份 |
| 被陪伴 | 角色人设、8 值情绪、六维关系、场景连续性、行为策略 |
| 被主动关心 | 后台自治周期、目标与计划、主动消息、世界事件触发 |
| 生活事务可管理 | 账本、车辆、任务、简报；记忆与关系贯穿其中 |

## 2. 系统边界与参与者

**系统边界**：一个后端系统 + 两个客户端 + 三类数据/制品存储。角色资产与 Prompt 属于系统内部，不是独立系统。

| 参与者 | 交互方式 | 证据 |
|---|---|---|
| App 用户 | 邮箱验证码或飞书授权登录；调用聊天、生活域、记忆、更新等 API | `apps/mobile/`；`app/api/v1/auth.py` |
| 飞书用户 | 企业团队成员私聊机器人；可把飞书身份绑定到 App 账号 | `app/channels/feishu/`；`app/services/identity/feishu/` |
| 开发者 / 运维 | Debug Console、迁移、发布与运维脚本 | `apps/frontend/`；`scripts/` |

**外部系统**（均为主链路可选依赖，失败可降级或返回明确错误）：

- **LLM Providers**：OpenAI 兼容接口，按 profile 切换（MiniMax / LongCat / OpenRouter / 阿里云 MaaS 等）。证据：`core/llm_factory.py`、`llm_profiles.example.json`。
- **Feishu Open Platform**：Webhook、消息发送、OAuth。证据：`channels/feishu/`、`services/identity/feishu/`。
- **SMTP 邮件服务**：邮箱验证码；MVP 为 163 个人邮箱。证据：`core/settings/email.py`、`services/email/sender.py`。
- **Open-Meteo**：天气与地理编码。证据：`core/settings/weather.py:15-18`。
- **外部 API 工具**：声明式 `ext.api.*`，域名 allowlist。证据：`services/tool/ext_api/`、`TOOL_EXT_ALLOWED_HOSTS`。
- **移动系统能力**：本地通知、相册、安装器、安全存储。证据：`apps/mobile/pubspec.yaml`。

## 3. 容器与职责

| 容器 | 职责 | 技术 |
|---|---|---|
| 朝夕 App | 产品客户端：聊天、生活域、记忆、简报、车辆、更新 | Flutter + Riverpod + GoRouter + Dio + Drift |
| Debug Console | 调试与观测控制台；**不是产品 UI**。Docker 镜像中由后端托管静态产物 | React 19 + TypeScript + Vite |
| Backend API | 通道接入、HTTP API、Agent Runtime、领域服务、后台循环、发布服务 | Python 3.13 + FastAPI + LangChain |
| PostgreSQL 16 + pgvector | 57 张表；Schema 唯一真相 = Alembic 迁移链（head `0010`） | SQL / SQLAlchemy / Alembic |
| Redis 7 | 验证码、OAuth state、雪花 ID 高水位等短生命状态 | Redis |
| 发布制品存储 | APK 与更新说明；本地卷 `/srv/backend/releases` | Filesystem |

后端内部按层拆分：`api/v1` → `application/` → `agent_runtime/` → `services/` → `repositories/` → `core/`。`chains/` 是 LLM 链，`channels/` 是通道适配器。依赖方向与「禁止反向依赖」见 `backend-module-dependencies.dot`。

## 4. 三条 Run Profile（唯一的 Agent Pipeline）

`application/agent_runtime/profiles.py` 是阶段序列的**唯一声明处**，禁止另开第二套管线。

| Profile | 触发 | 阶段 | LLM |
|---|---|---|---|
| `foreground_chat` | 用户消息（Web / 飞书） | perception → context_assembly → turn_decisions → mode_stabilize → scene_resolve → behavior_resolve → action_planning → reply_generation → record_handoff | 仅 `turn_decisions` / `reply_generation` |
| `autonomous_tick` | life_loop 后台 tick | perception → state_update → state_snapshot → goal_check → goal_stack → goal_supply → goal_advance → memory_retrieval → reflection_check → decision → world_experience | 仅 `decision`（critical） |
| `event_driven` | 白名单世界事件 | event_pregate | 0 |

**重要边界**：六段认知循环（observe / reason / plan / act / reflect / update）当前是影子/测试实现；**默认生产走 Profile 阶段序列**。`runtime_six_stage_loop_enabled=True` 时 `run()` 可切换为六段方法，但该路径不属于默认生产基线，不应画成主路径。

## 5. 关键运行链路

### 5.1 前台对话（一次用户消息）

Web 与飞书最终都收敛到 `services/agent_service.stream_chat` → `application/chat_pipeline.run_chat_pipeline`，整链包裹为 `foreground_chat` Run。整链由 9 个 Profile 段包裹（`perception` → `context_assembly` → `turn_decisions` → `mode_stabilize` → `scene_resolve` → `behavior_resolve` → `action_planning` → `reply_generation` → `record_handoff`）；下面 21 步是段内业务步骤，段序列唯一声明在 `profiles.py`。

1. 通道归一为 `InboundMessage`。
2. `open_foreground_run` 建 `loop_runs` 行 + Profile 快照。
3. 装配角色状态 / 世界切片 / 历史窗口 / 记忆召回 / 场景状态 / 目标选择。
4. 四链并行：role_router、turn_analyzer、scene_intent、intention。
5. 模式稳定、场景收敛、意图校验、统一决策管线、行为与风格装配。
6. 流式回答：先出 `turn_meta`，再逐 token 产出；LLM 经 Gateway 做预算与降级裁决。
7. 回答结束后落库本轮；随后调度后台后处理（scene / state / goal / summary / memory），独立容错。
8. 观测收口：trace、decision、turn 审计；关闭 Run（终态 + 成本汇总）。

**数据流纪律**：读取进链、写入出链；DB 写入在流式回答结束后执行，后处理失败不影响已产出回答。世界读取只经 `world_repository`，异常降级 `None`。

### 5.2 后台自治（life_loop tick）

`life_loop` 常驻循环先 sleep 后 tick：工作发现（0 LLM）→ 逐用户 `run_autonomous_cycle`（`autonomous_tick` Profile）→ tick 尾部事件预闸与维护步。维护步按间隔调度：world_maintenance、world_simulation、action_retry、action_schedule、**outbox_consume（常开）**、trigger_reconcile、ledger_digest。

其它常驻后台循环（`main.py` lifespan）：memory job worker、agent evolution worker、observability retention、ID 高水位刷写。baseline §4.2 另提及「memory reclaim」常驻循环，但当前 lifespan 未见独立任务（只有 `memory_reclaim_*` 设置字段无读取点），需按代码现状验证。

## 6. 业务能力（当前态）

| 能力域 | 现状要点 | 证据 |
|---|---|---|
| 对话与角色 | 流式对话、场景连续性、行为策略、风格契约 | baseline §3.1、§4.1 |
| 情绪与关系 | 8 值情绪 + 能量/强度；六维关系 + 四阶段 + 冲突状态机；账本/状态/快照三分离 | baseline §3.3 |
| 记忆与成长 | 7 规范类型、四源摄取、三段评估、混合检索、六态生命周期、分层配额、1-hop 图谱、关系抽取 | baseline §3.6、§8.2 |
| 目标与规划 | 目标栈、计划生成、七闸引擎（仅可选段接入）、决策审计、计划审批闸门 | baseline §3.4、§8.6 |
| 行动与工具 | 六类内置能力 + 通道/外部 API 工具；权限 → 确认 → 校验 → 归一 → 健康度 | baseline §3.5、§8.1 |
| 世界模拟 | 世界状态、物品状态机、时间推进、日计划、处境、简报、事件影响 | baseline §3.2 |
| 生活域 | 账本、车辆、任务、简报；财务数据 L1 受控保存，明细不进 Prompt | baseline §3.3 数据治理、§6.1 |
| 身份与通道 | 邮箱验证码 + 飞书 OAuth；**全通道统一凭据绑定表**；雪花 ID | baseline §5、§8.4、§8.5、ADR-16/19 |
| 评估与观测 | trace / decision / llm_call / prompt snapshot；规则 + LLM Judge 双路 | baseline §11.3 |
| 发布与更新 | 制品入库、版本检查、断点续传、双校验链、dev 只检测不安装 | baseline ADR-20 |

**已实现 vs 规划中**：计划审批闸门已实现（`plan_require_approval`，默认 OFF）；计划澄清闸门（L1 澄清）仍在规划中，**未实现**。

## 7. 数据与状态

- **Schema 唯一真相**：Alembic 迁移链（`0001` 基线 + `0002`~`0010` 增量）。`create_all` 只在测试内存 SQLite 豁免。
- **单一写面**：业务层不直接操作 ORM，一律经 `repositories/`；计划落库只经 `goal_repository`；Run 唯一写面 = `loop_runs`。
- **账本与状态分离**：`relationship_events`（append-only 时序权威）、`relationship_state`（当前态，version 乐观锁）、`relationship_snapshots`（版本化快照）。
- **版本化表**：`goal_plans`、`relationship_snapshots`、`agent_state_snapshots`、`world_snapshots`。
- **身份 ID**：全仓雪花 ID；`users.id` 与 37 张 `user_id` 列保持 `VARCHAR` 存十进制串；**ID 出 JSON 必须为字符串**（JS 精度硬约束）。
- **数据域关系**见 `data-domains.dot`。所有领域表以 `user_id` 归属；关系事件 / 行动 / 决策 / Run 台账 append-only。

## 8. 架构规则（读图时最需要知道的）

1. **无第二套 Agent Pipeline**：三种 Run Profile 只在 `profiles.py` 声明。
2. **通道层不包含 Agent / Memory / World 逻辑**：只做消息归一与出站发送。
3. **application 只做编排**：状态计算下沉领域服务 / 纯函数引擎。
4. **DB 唯一写面 = repositories**：业务层禁止直接操作 ORM。
5. **世界旁路纪律**：世界读写异常只 log + 降级，永不阻断聊天或主动链路。
6. **能力是手脚不是逻辑**：Capability 只执行，调度 / 重试 / 回复生成在引擎。
7. **前台 / 后台同一决策代码路径**：`decision_pipeline`；前台目标栈只读，长期化写入只在后台。
8. **飞行中不换引擎**：前台 / 后台回退位已物理删除；回退 = git revert。

## 9. 证据强度与待验证项

**高置信（代码 / 配置 / 迁移直接支持）**：容器划分、分层依赖、三条 Profile、前台 21 步、后台 tick 阶段与维护步、57 张表、外部系统接入点。

**中置信（文档描述 + 代码部分印证）**：业务能力地图中的用户价值归类；部分生活域端到端路径；评估域的在线/离线统一程度。

**当前必须标注为「非生产」或「未实现」**：

- 六段认知循环：影子/测试实现；默认生产走 Profile 阶段序列，开关可切换但不属于默认基线。
- 计划七闸引擎：`PlanningEngine` 仅由默认关闭的可选段接入，尚未接管主路径。
- 计划澄清闸门：规划中，未实现。
- 计划审批超时策略、审批触达、审批审计归因行、前端 plans 页面：未实现。
- 飞书绑定接管壳账号后的旧数据归并：未实现（归并脚本登记为后续项）。
- Debug Console 端点多用户隔离：无；产品面已隔离。
- 移动端 3 个 golden 基线漂移：P1 已知问题（baseline §9）。

**低置信 / 需要运行时验证**：

- `backend-module-dependencies.dot` 中的「禁止反向依赖」是基线规则，不是自动静态检查结果；若需确认是否存在实际违规，应运行依赖扫描 / 架构测试。
- `capability-map.dot` 是产品能力归纳，不是运行链路；具体行为以代码与基线为准。
- 外部 LLM provider 的可用性与配额属于运行时状态，不在当前静态模型中。

## 10. 阅读顺序

1. `system-model.structurizr.dsl` → 系统上下文 / 容器 / 后端组件（用 Qoder 的 Structurizr DSL viewer 打开）。
2. `backend-module-dependencies.dot` → 分层与依赖方向。
3. `foreground-chat-flow.dot` → 一次用户消息的同步主链路 + 异步后处理。
4. `autonomous-tick-flow.dot` → 后台自治与维护步。
5. `data-domains.dot` → 数据域与 Source of Truth。
6. `capability-map.dot` → 用业务语言回看系统价值。
7. `evidence.md` → 逐项证据、假设与验证方式。

## 11. Business Application Fitness（简要）

| 维度 | 结论 | 依据 |
|---|---|---|
| 业务模型清晰度 | 高 | 明确定义角色、关系、记忆、目标、世界、生活域；baseline 与版本文档完整 |
| 数据与状态理解 | 高 | 57 张表、迁移链、账本/状态/快照分离、生命周期状态机 |
| 端到端路径落地 | 高（对话/自治/记忆）；中（部分生活域） | 前台 21 步、后台 tick、四源摄取均有代码路径；生活域部分路径只到 API/服务层 |
| Agent 指令覆盖 | 中高 | `AGENTS.md` 说明架构、版本、文档导航与回归清单；但业务规则分散在各版本文档，缺少单一业务规则索引 |
| 业务验证就绪 | 中高 | 后端分层测试（unit / api / integration / e2e / golden）；已知移动端 golden 漂移 |

**最需要向读者说明的限制**：这张模型能解释「系统怎么组成、消息怎么流动、数据归谁管」，但不能替代对真实模型的人工回归；baseline 已明确多项上线前回归清单尚未执行。

---

> 维护：架构演进先更新 `docs/current-system-architecture-baseline.md`，再同步本目录的 DSL / DOT。不要把目标态直接画进当前态视图。
