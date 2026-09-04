# Backend Architecture Audit

> 审计范围：apps/backend 全部 84 个 Python 文件（app/ 78 + tests 48 + scripts 4 + migrations）。
> 审计方式：全量逐文件阅读 + grep 交叉验证，关键结论均带 file:line 证据，并以脚本实测复现了 P0-1。
> 审计日期：2026-08-29（V5-001~013 完成后）。
> **架构健康度：B**（依赖方向无环、LLM 边界干净、降级体系完善；但存在 1 个功能级 P0 bug、并发 lost update 风险、Context 无总量预算、编排职责持续膨胀）。

---

## 1. 当前架构（依据代码，非 README）

```text
HTTP (POST /api/v1/chat/message, NDJSON streaming)
 │
 ▼
app/api/v1/chat.py ────────── deps.py(get_chat_llm DI) ── schemas.py(13 个 Pydantic)
 │
 ▼
app/services/agent_service.py  ★ 编排中枢（320 行）
 │
 ├─ 前台 Critical Path
 │   ├─ context_builder.build ──┬─ conversation_service → conversation_repository
 │   │                          ├─ summary_service → summary_repository
 │   │                          ├─ memory_service.retrieve_v4 + select_for_context
 │   │                          │        └─ memory_repository(+touch_last_accessed 写)
 │   │                          └─ state_service.load_states（idle recovery + emotion decay 读侧写回）
 │   │                                   └─ character_state_repository / relationship_repository
 │   ├─ scene_service.load → scene_state_repository
 │   ├─ asyncio.gather：router_chain / turn_analysis_chain / scene_intent_chain（3 次 LLM 并行）
 │   ├─ scene_service.resolve（纯函数）
 │   └─ answer_chain.astream（第 4 次 LLM，流式）→ conversation_service.save_turn
 │
 └─ 后台 Background Path（asyncio.create_task，SSE 不等）
     ├─ scene_service.update_and_persist（scene_update_chain LLM）
     ├─ state_service.apply_and_save（state_update_chain LLM → state_engine 情绪/关系
     │        → character_state / relationship / relationship_events / emotion_history 落库
     │        → memory replay 折价补记）
     ├─ summary_service.update（条件触发，summary_chain LLM）
     └─ memory_service.extract_and_save（extractor_chain LLM → memory_policy →
              memory_conflict → memory_repository）

纯函数规则层（无 IO）：state_engine、memory_policy、memory_conflict、scene_service.resolve
LLM 层：app/chains/*（经 chains/structured.build_structured_chain 统一），Provider 构造仅在 core/llm_factory
Prompt 层：app/prompts/*（10 个文件）+ app/character/asuna/*（角色资产）
持久化：app/repositories/*（8 个，每函数独立 SessionLocal 事务）
```

每次请求 LLM 调用：前台 4（router / turn_analysis / scene_intent / answer）+ 后台 3~4（scene_update / state_update / memory_extract / 条件 summary）= **典型 7 次，最坏 13 次**（结构化链带 fallback 重试）。

---

## 2. 当前模块职责

| Module | Responsibility | Problem |
|---|---|---|
| `api/v1/chat.py` | SSE 装配、错误→SSE 映射、LLM profile 解析 | 职责基本干净 |
| `api/v1/history.py` / `state.py` | 读路径查询 | **绕过 service 直接 import 4+2 个 repository**，与 chat 路径分层不一致 |
| `api/v1/llm.py` | profile 元数据 | 穿透 `llm_factory.get_settings()` 隐性依赖 |
| `services/agent_service.py` | 前台编排 + 后台编排 + 降级 + trace + SSE | **God Service 前兆**：`_stream_chat_inner` 14 件事、`_post_process` 5 件事、聚合 7 个 service；每个版本都在往里加（V3 加 scene、V4 加 memory 上下文、V5 加 recent_context 拼接） |
| `services/context_builder.py` | 上下文聚合 | 基本干净；但读路径含写（touch_last_accessed、衰减写回） |
| `services/memory_service.py` | 检索 + 四段管线 + 回收循环 + replay 触发 | 职责过多（检索/写入管线/回收循环三种生命周期混在一文件）；检索权重等参数硬编码 |
| `services/state_service.py` | V2 状态 + V5 情绪/关系 + 日上限聚合 + replay 执行 | 日账本失败会把"已用额度清零"等效放宽上限；replay 每条记忆 2 次 list_events |
| `services/scene_service.py` | resolve 纯函数 + LLM 更新 | 干净 |
| `services/state_engine.py` / `memory_policy` / `memory_conflict` | 纯函数规则层 | **架构优点**；但数值设计表（EMOTION_EVENTS 等）与 settings 阈值两处分离 |
| `chains/*` | LLM 链 | 干净，LLM 获取集中在 chains+llm_factory，**无泄漏到 services/api** |
| `prompts/builder.py` | Prompt 组装 | **P0 bug：用户原文直接进 ChatPromptTemplate 模板位**；RELATIONSHIP_BUDGET_CHARS 死常量；prompt 层直接依赖 langchain |
| `repositories/*`（8 个） | CRUD | 7 个干净；memory_repository 混入类型校验/映射与 `exists_similar` 相似度业务判断（threshold 参数收了不用） |
| `core/db.py` | ORM + engine | `get_session()` 定义后全仓未用（死代码）；check 约束/索引齐全 |
| `core/llm_factory.py` | Provider 构造 + profile 缓存 | 干净，单 Provider（LongCat/OpenAI 兼容），无过度抽象 |
| `core/settings.py` | 55 字段集中配置 | 优点；但 state_engine 数值表未入 settings |

---

## 3. 主要架构问题（P0~P3）

### P0（阻塞/严重）

- **P0-1 Prompt 模板注入崩溃（功能级 bug，已实测复现）**：`prompts/builder.py:152-153,167` 把对话历史与 `current_input` 原文作为 `(role, content)` 传入 `ChatPromptTemplate.from_messages`，内容含 `{...}` 会被当作模板变量。实测：用户消息 `含 {braces} 的输入` → `KeyError` → 请求 500。聊天是自由文本，花括号必然出现。
- **P0-2 并发 Lost Update**：`character_state/relationship` 为 get→compute→upsert 三段独立事务（`character_state_repository.py:28-45`），读在前台、写在后台，中间隔 4+ 次 LLM 调用（秒级）；grep `for_update|version_id` 全仓 0 命中。同用户并发请求时后写覆盖先写（情绪/关系分数回跳）。
- **P0-3 日志输出对话原文**：`agent_service.py:219` 将 AI 回复全文 INFO 落日志；`memory_service.py:124,169,171` 输出记忆候选内容（源自用户原话）。隐私/合规风险。
- **P0-4 forget 隐私指令失败静默**：`memory_service.py:132-133` 用户"忘了吧"硬删除失败仅留日志，无补偿、无状态可见——隐私合规风险。

### P1（明显影响维护与扩展）

- **P1-1 编排职责膨胀（God Service 前兆）**：agent_service 前后台编排+降级+trace+SSE 集中；V6 Character Engine 将继续加剧。目标不是拆文件而是拆"关键路径编排"与"后台编排"两类职责。
- **P1-2 Context 无总量预算**：各段独立上限（history 20 条/8000 字、memory 5 条/400 字、情绪 120、关系 150 定义了但**从未引用**、摘要/身份块无上限），无跨段落总预算，长会话+长摘要下 Prompt 可持续膨胀。
- **P1-3 事务边界与账本漂移**：8 个 repo 每函数一事务；`apply_and_save` 中 `create_event`（账本）先提交、`upsert_relationship`（状态）后写，后者失败则下轮 `_day_impact_totals` 重复计入该事件 → 日上限被多扣；memory `supersede` 新建与挂链两事务，中间失败则新旧双 active。
- **P1-4 API 分层不一致**：history/state 直接操作 repository；`default-user` 在 3 处硬编码；api 穿透 llm_factory 取 settings。
- **P1-5 可观测缺口**：trace 无 token usage、无 provider/model 元数据、无 request_id；进行中 trace（`_pending`）不可查询；容量 20 纯内存、重启即失。

### P2（中等技术债）

- **P2-1** 数值参数两处分离：state_engine 常量表（EMOTION_EVENTS/DELTA 表）与 settings 阈值（0.6 强情绪/0.4 上限等）分离；builder 内分档阈值（0.3/0.6/0.5/0.7）散落。
- **P2-2** memory_repository 越界：类型映射/范围校验/`exists_similar`（threshold 未生效、仅测试在用）；V1 `extract`/`MemoryDecision` 遗留链仍在。
- **P2-3** 错误分类缺失：`state_update_chain`/`scene_update_chain` 失败 `return None` 静默；日账本读取失败清零已用额度（P1-3 的另一面）。
- **P2-4** 窗口不一致：memory 提取 recent_context 用 `state.messages[-4:]`（agent_service.py:296），turn_analysis 用 `analysis_recent_messages=6`。
- **P2-5** prompts/builder 依赖 langchain 构造 ChatPromptTemplate（prompt 应是数据，渲染应隔离）。
- **P2-6** `scripts/dev_fake_llm_server.py` import `tests.conftest.FakeLLM`——生产脚本依赖测试基建。

### P3（代码质量）

- **P3-1** 死代码：`agent_service._resolve_mode`（无调用）、`db.get_session`（无调用）、`RELATIONSHIP_BUDGET_CHARS`（未引用）。
- **P3-2** trace_collector 对 list.append 等不可能失败的操作包 try（过度防御，22 处 except Exception 中 3 处）。
- **P3-3** 测试无 unit/integration/e2e 目录分层（48 个文件平铺）；无 golden prompt 回归（角色行为回归无护栏）。
- **P3-4** 文档 drift 风险（AGENTS/README 与实现同步靠手工）。

---

## 4. Dependency Analysis

**Current**（实测无环，整体健康）：

```text
api → services → chains → (prompts, models, core)
api → repositories（仅 history/state，旁路）
services → repositories → core.db
prompts → character/models/settings；builder → langchain
models → models（最干净）；repositories 不知 LLM；chains 不知 repository ✓
```

问题点：① api→repositories 旁路；② api→llm_factory.get_settings 穿透；③ scripts→tests；④ prompts→langchain（方向没错，但渲染与数据未分离）。

**Target**：

```text
api（HTTP only：schema、错误映射）
 ↓
application（chat_pipeline 前台编排 / post_process 后台编排）   ← 新增，自 agent_service 拆出
 ↓
services（领域服务） + engines（纯函数规则层）
 ↓
repositories（持久化） + chains（LLM） + prompts（数据+渲染）
 ↓
core（settings / db / llm_factory / errors）
```

不引入 DDD 全家桶（详见 target-architecture.md §1）。

---

## 5. LLM Architecture

- **现状（好）**：`ChatOpenAI` 构造仅 `llm_factory.py:11`；`get_llm` 调用仅 chains/structured、answer_chain、summary_chain、api/deps（DI 入口）；services/api 不 import langchain；结构化输出统一走 `build_structured_chain`（with_structured_output + PydanticOutputParser fallback）。
- **问题**：① chains 内 `get_llm` 获取方式不一致（structured 传参 vs answer/summary 直取）；② 无 token usage 采集点；③ 结构化链 fallback 意味着一次失败变两次调用，但 trace 不区分；④ LLM Error 只有裸 Exception（`EmptyLLMResponseError` 是唯一自定义）。
- **目标**：维持"LLM 调用集中在 chains"的既有边界（**不需要** Provider Adapter 层——当前单 Provider，llm_factory 的 profile 机制已是足够抽象）；补 usage 采集与 LLM Error 最小分类。

## 6. State Architecture

| State | 归属 | 现状边界 | 结论 |
|---|---|---|---|
| SceneState | scene_service + scene_state_repository | 与 V4/V5 零耦合，仅共享 trace | ✓ 保持 |
| MemoryState | memory_service + 3 个纯函数层 | 与 scene/emotion 零耦合 | ✓ 保持 |
| EmotionState | state_service + state_engine（CharacterState 三列） | 与 Relationship 同一管线同一事务族 | ✓ 合理（同一 CharacterState 行） |
| RelationshipState | state_service + state_engine + relationship_events 账本 | 同上 | ✓ 保持 |
| CharacterState(V2) | state_service | mood 直写已退役，与 V5 融合 | 已收敛 |

**互相调用情况**：V5 各 State 更新互不调用（V4-008/V5-008 起即为并行独立 try/except）；唯一共享点是 trace collector 与 ConversationState 载体。**State 边界本身健康，问题在编排位置（都在 agent_service/_post_process 里内联）与事务族（P1-3）。**

## 7. Database / Performance

- Current DB Access Flow（前台正常路径）：10 次 repository 调用 ≈ 12 条 SQL（8 SELECT + 1 UPDATE + 2 INSERT + 2 refresh SELECT；条件 +衰减写回、+新会话 INSERT）。
- 无 N+1（各取一次列表）；可优化点：`_day_impact_totals` limit=500 全量拉取后按日过滤、replay 每条记忆 2 次 `list_events`（应一次拉取复用）。
- Background 四步各自独立写库，无跨步事务（见 P1-3）。

## 8. Observability / Testing（现状）

- Trace：17 个 step 名称、5 个后台完成判据；`TraceStep{name, duration_ms, status, first_token_ms, error}`；仅 `GET /debug/turns/{turn_id}/trace` 一个查询端点（pending 不可查）。缺：token usage、provider 元数据、request_id、持久化。
- 测试：560 passed / 3 skipped，FakeLLM + 内存 SQLite 机制成熟；unit/integration/e2e 可按依赖面划分但目录平铺；**无 golden prompt 快照回归**——对角色扮演系统这是行为回归的主要护栏缺口。

## 9. 同步/异步边界（现状，健康）

```text
Critical Path（首 token 前必经）：context_builder(8 SELECT) → 3 链并行 → answer astream
Background Path（SSE done 后）：scene_update ‖ state_update ‖ summary ‖ memory_extract（互相独立 try/except）
```

任一后台失败仅影响对应状态，不影响回答（Case 9/14/15 已有测试）。**无需重构流式边界，只需保持。**
