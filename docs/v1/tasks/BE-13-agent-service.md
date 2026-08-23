# BE-13 agent_service（主编排）

| 字段 | 内容 |
|---|---|
| Task ID | BE-13 |
| Task Name | agent_service（核心对话流程编排） |
| Type | BE |
| Priority | P0 |

## Description

实现 `app/services/agent_service.py`，编排完整对话流程：路由 → 上下文组装 → 流式回答 → post-process（存消息 / 触发摘要 / 提取记忆）。是本项目三层架构的收敛节点（V1 功能目标一~五的串接）。

## Scope

- 主流程：
  1. `context_builder.build()` 组装 state
  2. `router_chain.route()` 获取 mode
  3. `answer_chain.astream()` 流式输出（同时累计完整回答）
  4. 流结束后 post-process：
     - a. `conversation_service.save_turn()`（human + ai）
     - b. 消息数 ≥ 阈值 → `summary_service.update()`
     - c. `memory_service.extract_and_save()`（异步，不阻塞响应）
- 提供 `stream_chat(session_id, user_id, content)` 异步生成器

## Out of Scope

- HTTP 端点（API-01）
- 各子服务实现（BE-06 ~ BE-12）
- 错误码/响应格式（API-01）

## Dependencies

- BE-06（router_chain）
- BE-07（conversation_service）
- BE-08（summary_service）
- BE-10（memory_service）
- BE-11（context_builder）
- BE-12（answer_chain）

## Input

- 全部上游 service/chain 接口
- `settings`（阈值）

## Output

- `app/services/agent_service.py`

## Business Rules

1. 读取进链、写入出链：DB 读取在生成前，DB 写入在流结束后（架构文档核心决策）。
2. post-process 失败（摘要/记忆）**不得影响本轮回答已产出的流**；记忆提取可用 `asyncio.create_task` 后台执行或 try/except 隔离。
3. `save_turn` 必须成功（短期记忆是核心），失败则本轮可重试语义。
4. `stream_chat` 为异步生成器，token 逐个 `yield`。

## API Dependencies

- 无（供 API-01 调用）

## Data Dependencies

- 会话 / 摘要 / 记忆三表（经各 service）

## Permission

- 无鉴权要求。

## Error Handling

- 路由解析失败 → 降级 default 继续回答。
- LLM 回答失败 → 向上抛，API 层转错误响应。
- post-process 摘要/记忆失败 → 记录日志，不中断已完成的流。

## Subtask 拆分

- S1：主流程串联（route → context → answer）
- S2：流式输出 + 回答累计
- S3：post-process 三件套
- S4：异常降级路径

## Acceptance Criteria

- 一次 `stream_chat` 完整产出回答 token
- 流结束后 messages 表新增 human+ai 两条
- 达阈值会话触发摘要更新
- 记忆提取后台执行，响应不等待
- 记忆/摘要失败不影响回答输出

## Test Requirements

- mock LLM：全链路（路由→回答→存消息→摘要→记忆）。
- 降级路径：路由失败仍回答、摘要失败仍回答。
- 消息落库断言（human + ai 各一条）。