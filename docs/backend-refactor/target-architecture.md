# Target Architecture

> 原则：Same Behavior, Better Architecture。不推倒目录、不引入 DDD 全家桶（Entity/Aggregate/CQRS/Event Sourcing 均不引入）；在现有 packages 上做职责归位，为 V6 Character Engine 准备编排层。

## 1. 规模判断（为什么不做大拆分）

- 后端 app/ 共 78 个文件、~5600 行业务代码、单 Provider、8 张表、单人用户模型（default-user）。
- 依赖方向已无环，LLM/Prompt/Repository 边界大体清晰——**问题集中在"编排层缺失"与"少数边界泄漏"，不是分层缺失**。
- 结论：采用**轻量 feature-保持 + 新增 application 编排层**，不采用完整 backend/{api,application,domain,ai,infrastructure} 五层目录（搬家成本 > 收益，且 git 历史与 48 个测试文件的 import 全部要改）。

## 2. 目标模块图

```text
app/
├── api/v1/                  # HTTP only：schema、SSE 装配、错误→HTTP 映射
│   └── (不再直接 import repositories；统一走 application/services)
│
├── application/             # ★ 新增：编排层（自 agent_service 拆出，agent_service 变薄壳或删除）
│   ├── chat_pipeline.py     #   前台关键路径：context → 3 链并行 → scene resolve → answer stream → save_turn
│   └── post_process.py      #   后台编排：scene_update ‖ state_update ‖ summary ‖ memory（任务注册 + 独立容错）
│
├── services/                # 领域服务（保持现有文件）
│   ├── memory_service.py    #   拆为 retrieve / pipeline / reclaim 三组（可先同文件分区）
│   └── state_service.py     #   情绪/关系/V2 状态（保持）
├── engines/                 # ★ 改名归位：state_engine、memory_policy、memory_conflict（纯函数，无 IO）
│
├── chains/                  # LLM 链（保持；统一经 structured 获取 LLM）
├── prompts/                 # prompt 数据 + 渲染（builder 收敛为纯渲染，模板注入修复）
├── repositories/            # 持久化（业务校验/相似度判断移回 services 层）
├── models/                  # 领域模型（保持；LLM Decision 模型与 API schema 不混用——现状已合规）
└── core/                    # settings / db / llm_factory / errors(新) / constants(新，数值表)
```

## 3. 职责与依赖方向

| 层 | 允许依赖 | 禁止 |
|---|---|---|
| api | application、services、schemas | repositories、langchain |
| application | services、engines、chains（编排调用） | 直接 SQL、prompt 文本 |
| services | engines、repositories、chains、core | api |
| engines | models、core.settings/constants | repositories、chains、IO |
| chains | prompts、models、core.llm_factory | repositories、services |
| repositories | core.db、models | 一切业务判断 |

## 4. LLM Boundary

- 保持现状：Provider 构造仅在 `core/llm_factory`（单 Provider，profile 机制即抽象层，**不做 Adapter 层**）。
- 补齐：① chains 统一经 structured 获取 LLM；② `core/errors.py` 定义最小错误集：`LLMError`（含空响应）、`DegradedError`（辅助模块降级用）、`PersistenceError`——不做异常层级树；③ 每次结构化调用在 trace 记录 usage（prompt/completion tokens）与 profile id。

## 5. State Boundary

- SceneState / MemoryState / EmotionState / RelationshipState 继续互相零调用，各走各的 service + repository + trace step。
- 编排层只做"调度与容错"，不做任何状态计算（计算在 engines）。
- V6 Character Engine 的入口即 `application/` 编排层：新增能力以注册新 post-process 步骤/新 context 段的方式接入，不再改 agent_service。

## 6. Persistence Boundary

- repositories 只做 CRUD/Query；`memory_repository` 的类型映射校验移到 services 层，`exists_similar` 移入 `memory_conflict`（或删除）。
- 事务策略（不强求大事务）：
  - **强一致族**：`relationship_events.create_event` 与 `relationship/character_state` 的 upsert → 提供组合函数（同 session 多写一次提交），账本与状态要么都成功要么都不落；
  - **允许最终一致**：memory supersede 双写（失败保留旧行 active 可接受，补幂等重试）、scene/state/summary/memory 四个后台步骤之间（本来就是独立容错设计）。
- 并发：**单用户写串行化**（应用层 per-user asyncio.Lock 或按 user_id 分片的写队列）作为最小方案，替代 DB 行锁（规模不需要）。

## 7. Streaming Boundary

- 保持现状（后台 asyncio.create_task 与 SSE 严格分离，已验证健康）。
- 唯一变更：编排拆分后 `_background_tasks` 集合与 done 回调收进 `post_process.py`，对测试 conftest 暴露同一符号（避免测试大面积改动）。

## 8. Error Boundary

| 错误 | 处理 | 位置 |
|---|---|---|
| LLMError（含空响应） | 前台：按现有降级（router/analysis/scene_intent 降级、answer 转 SSE detail）；后台：丢弃本轮 | chains/api |
| 辅助模块失败（scene/memory/state 后台） | logger.exception + trace error + 继续其余步骤 | application/post_process |
| PersistenceError | 前台读路径：降级默认值（现状保持）；后台写路径：trace error；**账本-状态族同事务** | repositories/application |
| 隐私 forget 失败 | 不允许静默：重试 1 次 + trace `privacy_forget` status=error + debug 可见 | memory pipeline |
| 日账本读取失败 | **保守 fail-safe**：视为当日额度已满（阻止加分）而非清零（阻止漏扣） | state_service |

## 9. Observability

- Trace 保持内存 + turn_id 键，补：token usage、llm profile、request_id（uuid 贯穿 SSE header `x-request-id`）；
- `GET /debug/turns/{turn_id}/trace` 支持查 pending；
- 容量可配置不变；不做持久化/结构化日志（规模不需要，日志脱敏先做）。

## 10. Context Budget

- 新增 `core/settings`：`context_total_char_budget`（如 12000）+ 各段既有上限保留；
- `PromptBuilder` 组装后统计总长，超预算按固定优先级裁剪：历史窗口 > 记忆条数 > 摘要（身份/场景/情绪/关系段不裁——它们是角色一致性核心且体量小）；
- 修复模板注入后，历史消息与 current_input 走非模板消息通道，天然消除一个膨胀源。

## 11. 不做的事（明确排除）

- 不引入 UnitOfWork/CQRS/Event Sourcing/DomainEvent 框架；
- 不为多 Provider 预写 Adapter（llm_factory 已够）；
- 不把 48 个测试文件机械搬目录（只在 Phase 3 顶层分 unit/integration/e2e 三个子目录 + conftest 保持根级）；
- 不改数据库 schema（审计期内无 schema 问题）。
