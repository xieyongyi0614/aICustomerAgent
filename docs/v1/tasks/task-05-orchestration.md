# Task 5 — 完整编排 + 端到端

> Context Builder 完整拼装 + LCEL 流水线 + 流式返回 + 错误处理，串联 Task 1-4。
> 架构参考：`docs/v1/v1-architecture.md` §7、§8 Task 5

## 目标

- Context Builder 完整组装（Memory + Summary + Recent + Input）
- 主 Agent 流水线统一为 LCEL（RunnablePassthrough / RunnableLambda）
- 流式输出回传前端 + 异常处理
- 一条请求跑通全链路

## 涉及文件

| 操作 | 文件 |
|---|---|
| 新建 | `app/services/context_builder.py` |
| 新建 | `app/chains/answer_chain.py` |
| 修改 | `app/services/agent_service.py` |
| 修改 | `app/api/v1/chat.py` |

## 实现步骤

1. `services/context_builder.py`：`build(session_id, user_input, memories, summary, messages) -> ConversationState`，统一 DTO。
2. `chains/answer_chain.py`：`PromptBuilder.build(mode, state) | llm`。主流水线：

   ```python
   agent_pipeline = (
       RunnablePassthrough()
       | RunnableLambda(load_context)                        # DB 读取：历史+摘要+长期记忆
       | RunnablePassthrough.assign(role_mode=router_chain)  # 路由挂载
       | RunnableLambda(PromptBuilder.build)                 # 模块化组装 prompt
       | llm                                                 # 流式
   )
   ```

3. `services/agent_service.py` 编排：
   ```
   load_context → router → astream → 流结束后：
   a. 保存 Human/AI 消息
   b. 消息数达阈值 → summary 滚动更新
   c. extractor 提取长期记忆
   ```
4. `api/v1/chat.py`：session_id 校验、流式分块响应（`StreamingResponse`）、异常转 HTTP 500 + 日志。
5. 全链路联调 Task 1-4。

## 验收标准

- 一条请求完整走通：路由 → 记忆 → 上下文 → 流式回答 → 存消息 → 摘要 → 记忆提取
- 无 session 时自动新建；异常时返回结构化错误而非裸 500
- 首 token 尽快返回（记忆/路由不阻塞流式管线）
- `pylint` 通过