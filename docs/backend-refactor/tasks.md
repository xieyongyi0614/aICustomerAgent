# Backend Refactor Task Registry

> 执行策略与 V4/V5 相同：一次一个 Task → 测试 → 全量回归（V2/V3/V4/V5 零回归）→ commit/push → 汇报。
> 全局验收：`uv run pytest tests/ -v` 全绿（~560 项）；功能不变、API 不变、schema 不变、Prompt 行为不变。

## Phase 1 — 止血（P0，低风险高收益）

### REF-001 修复 Prompt 模板注入崩溃（P0）
- **状态：DONE（865f010）**

- **Goal**：用户消息/历史消息含 `{...}` 不再导致 `KeyError` 500。
- **Current Problem**：`prompts/builder.py:152-153,167` 把用户原文作为模板消息传入 `ChatPromptTemplate.from_messages`（已实测复现 KeyError）。
- **Files**：`app/prompts/builder.py`。
- **Changes**：历史消息与 current_input 改用 `MessagesPlaceholder` / `("human"/"ai", content)` 非模板通道（或对内容做 literal 转义）；其余静态段落保持模板。
- **Dependencies**：无。
- **Acceptance**：含 `{}`、`{topic}`、连续花括号的输入全链路返回正常；现有全部 prompt 测试不变绿转红。
- **Tests**：新增含花括号输入的 builder 单测 + e2e 一例（golden 输入）。

### REF-002 日志脱敏（P0）
- **状态：DONE（8c7b50c）**

- **Goal**：日志不再输出对话原文与记忆候选内容。
- **Current Problem**：`agent_service.py:219`（reply 全文 INFO）、`memory_service.py:124,169,171`（候选内容）。
- **Files**：`app/services/agent_service.py`、`app/services/memory_service.py`。
- **Changes**：reply/候选内容改为长度摘要（前 N 字符截断 + 长度），或降 DEBUG 级；增加 settings `log_content_preview_chars`（默认 0 = 不输出原文）。
- **Dependencies**：无。
- **Acceptance**：INFO 级日志 grep 不到完整对话原文；debug 能力不丢失（DEBUG 级仍可开）。
- **Tests**：caplog 断言 INFO 级不含原文、DEBUG 级含截断预览。

### REF-003 forget 隐私指令补偿（P0）
- **状态：DONE（d5b6b11）**

- **Goal**：用户"忘了吧"执行失败不可静默。
- **Current Problem**：`memory_service.py:132-133` 吞错。
- **Files**：`app/services/memory_service.py`、`app/services/trace_collector.py`。
- **Changes**：失败重试 1 次；仍失败 trace `memory_privacy` status=error 且 logger.error；debug trace 可见。
- **Dependencies**：无。
- **Acceptance**：注入删除失败 → trace 可见 error；正常路径行为不变。
- **Tests**：失败注入单测（trace 断言）。

### REF-004 配置收编与死代码清理（P1，低风险）
- **状态：DONE（751c68c）**

- **Goal**：阈值/魔法数归位，删除死代码。
- **Current Problem**：`default-user` 3 处硬编码；recent 窗口 `-4` vs `analysis_recent_messages=6` 不一致；检索权重 0.45/0.25/0.20/0.10、半衰期 30、limit 200/500、`max_chars=400` 散落；`RELATIONSHIP_BUDGET_CHARS` 死常量；`_resolve_mode`、`db.get_session` 死代码。
- **Files**：`app/core/settings.py`、`app/core/db.py`、`app/services/*`、`app/prompts/builder.py`、`app/api/v1/*`。
- **Changes**：新增 settings 字段（memory_retrieval_weights、memory_context_char_budget、recent_context_turns、default_user）；state_engine 数值表移 `core/constants.py`（仅搬家不改值）；删除两处死代码。
- **Dependencies**：REF-001（同文件避免冲突）。
- **Acceptance**：grep 无 default-user 硬编码散落；全量测试绿。
- **Tests**：既有测试保持；settings 覆盖测试补充。

## Phase 2 — 编排与边界（P1）

### REF-005 ChatPipeline 编排拆分（P1）
- **状态：DONE（82a7118）**

- **Goal**：关键路径编排独立成层，agent_service 不再是唯一上帝。
- **Current Problem**：`_stream_chat_inner` 14 件事（audit §1）。
- **Files**：新增 `app/application/chat_pipeline.py`；`app/services/agent_service.py` 瘦身为兼容壳（保留 `stream_chat` 符号与 `EmptyLLMResponseError`）。
- **Changes**：步骤①②③④⑤⑥⑦⑨⑩ 按现有顺序平移为 `run_chat_pipeline` 显式分段函数（build_context / run_detectors / resolve_scene / stream_answer），`_timed` 助手随迁；**不改执行顺序、不改 trace step 名**。
- **Dependencies**：REF-001、REF-004。
- **Acceptance**：agent_service ≤ 80 行；SSE 事件序列与 trace 逐字节等价（现有 turn_meta/e2e 测试不动全绿）。
- **Tests**：现有 e2e 即回归；新增 pipeline 纯编排单测（FakeLLM 注入断言调用顺序）。

### REF-006 PostProcess 编排拆分（P1）
- **状态：DONE（5f96218）**

- **Goal**：后台任务注册与容错收口。
- **Current Problem**：`_post_process` 5 件事内联在 agent_service。
- **Files**：新增 `app/application/post_process.py`；agent_service 调用它。
- **Changes**：四步改为步骤注册表（name → coroutine factory），统一计时 + try/except + trace 模板；`_background_tasks` 集合移入（conftest 引用同步更新 `agent_service._background_tasks = post_process.background_tasks` 别名保持兼容）。
- **Dependencies**：REF-005。
- **Acceptance**：新增后台步骤（V6）只需注册一项；四步独立容错语义不变。
- **Tests**：现有失败注入测试（Case 9/14/15）保持；新增"任一步骤崩溃其余仍执行"的注册表测试。

### REF-007 Context 总预算（P1）
- **状态：DONE（501b175）**

- **Goal**：Prompt 总量有硬上界。
- **Current Problem**：无跨段落预算；`RELATIONSHIP_BUDGET_CHARS` 未生效；摘要无上限。
- **Files**：`app/prompts/builder.py`、`app/core/settings.py`。
- **Changes**：新增 `context_total_char_budget`（默认 12000）；builder 组装后统计，超限按 历史窗口 > 记忆条数 > 摘要 顺序裁剪；关系段预算实际生效。
- **Dependencies**：REF-001。
- **Acceptance**：构造超长输入，最终 prompt 字符数 ≤ 预算；正常输入行为不变。
- **Tests**：预算裁剪单测（各段命中顺序）。

### REF-008 API 分层收口（P1）
- **状态：DONE（1d08193）**

- **Goal**：api 不再直连 repository。
- **Current Problem**：history.py/state.py 直 import 6 个 repository；llm.py 穿透 llm_factory.get_settings；default-user 已在 REF-004 收编。
- **Files**：`app/api/v1/history.py`、`app/api/v1/state.py`、`app/api/v1/llm.py`、services 层对应读函数。
- **Changes**：读路径经 `history_service`/`state_service`（或薄 query service）转发；schemas 不变。
- **Dependencies**：REF-004。
- **Acceptance**：grep api/ 无 repository import；API 响应逐字节不变（现有 debug/e2e 测试不动）。
- **Tests**：现有 API 测试即回归。

### REF-009 账本-状态事务一致性（P2）
- **状态：DONE（8022500）**

- **Goal**：relationship_events 与 relationship/character_state 不再部分成功。
- **Current Problem**：`create_event` 先提交、upsert 后写（`state_service.py:132,160-161`），失败即漂移；memory supersede 两事务。
- **Files**：`app/repositories/relationship_repository.py`、`relationship_event_repository.py`、`character_state_repository.py`、`app/services/state_service.py`、`app/services/memory_service.py`。
- **Changes**：新增组合 repo 函数（同 session 多写单提交）：`commit_relationship_update(state, events)`；supersede 同事务。
- **Dependencies**：REF-006（在编排层改调用）。
- **Acceptance**：注入 upsert 失败 → 账本无孤儿行；日上限不重复扣。
- **Tests**：失败注入 + 对账断言（impact 总和 == 状态差）。

### REF-010 并发写串行化（P0 的最小治理）
- **状态：DONE（fba4cc4）**

- **Goal**：同用户 character_state/relationship 无 lost update。
- **Current Problem**：get→compute→upsert 无锁无版本（audit P0-2）。
- **Files**：`app/application/post_process.py`（Phase 2 后归属正确）、`app/core/settings.py`。
- **Changes**：应用层 per-user 写锁（asyncio.Lock 字典，按 user_id），后台状态写路径串行；不做 DB 行锁/版本号（规模不需要）。
- **Dependencies**：REF-006。
- **Acceptance**：并发两请求模拟（asyncio.gather 两个 apply_and_save）最终分数 = 两次增量之和而非覆盖。
- **Tests**：并发单测（gather 两次更新断言累积）。

## Phase 3 — 可观测与质量

### REF-011 Observability 增强（P1）
- **状态：DONE（f9a5093）**

- **Goal**：能回答"这轮为什么 OOC"。
- **Changes**：trace step 增补 token usage（langchain response.usage）、llm profile、request_id（SSE header `x-request-id` 贯穿）；`/debug/turns/{id}/trace` 支持查 pending；删除 trace_collector 过度防御 try。
- **Dependencies**：REF-005/006。
- **Tests**：trace 快照断言扩展。

### REF-012 遗留与边界清理（P2）
- **状态：DONE（8b49e2f）**

- **Changes**：删除 V1 `extract`/`MemoryDecision` 生产链（test_extractor 同步退役或改标注 legacy）；`memory_repository.exists_similar` 移除/迁 `memory_conflict`；repo 内类型映射校验移 services；`scripts/dev_fake_llm_server.py` 不再 import tests.conftest（内联 FakeLLM 或提 core/testing）。
- **Dependencies**：REF-005 后执行。
- **Tests**：全量回归 + 被移除符号的 grep 零残留。

### REF-013 测试分层与 Golden Prompt 回归（P3）
- **状态：DONE（5adeb40）**

- **Changes**：tests/ 顶层分 unit/ integration/ e2e/（conftest 留根）；新增 golden prompt 快照测试（builder 全段落 + 各版本场景输入 → 快照文件，变更需显式更新并 diff 审查）。
- **Dependencies**：REF-001/007（模板修复后快照才稳定）。
- **Tests**：golden 测试自身；目录调整后全量绿。

## 依赖图

```text
REF-001 → REF-004 → REF-005 → REF-006 → REF-009/010/011/012
REF-001 → REF-007 → REF-013
REF-004 → REF-008
REF-002 / REF-003（独立）
```

## 执行顺序建议

Phase 1（REF-001~004，1 次会话可完成）→ Phase 2（REF-005~010）→ Phase 3（REF-011~013）。
若决定先做 V6：Phase 1 必须先行（P0-1 是功能 bug），REF-005/006 与 V6 首个 Task 合并推进（V6 正需要编排层）。
