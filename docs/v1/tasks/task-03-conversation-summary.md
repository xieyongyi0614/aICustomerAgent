# Task 3 — 对话摘要（长期聊天不爆窗）

> 历史消息超过阈值后触发滚动摘要，prompt 中注入 summary，解决 Context Window 无限增长问题。
> 架构参考：`docs/v1/v1-architecture.md` §8 Task 3

## 目标

- 超过阈值（默认 40 条 = 20 轮）触发摘要生成
- 摘要采用滚动压缩：old_summary + new_messages → new_summary
- summary 进入 Prompt，使早期内容不丢失

## 涉及文件

| 操作 | 文件 |
|---|---|
| 新建 | `app/repositories/summary_repository.py` |
| 新建 | `app/services/summary_service.py` |
| 新建 | `app/chains/summary_chain.py` |
| 新建 | `app/prompts/summary.py` |
| 新建 | `app/models/summary.py` |
| 修改 | `app/core/db.py`（增加 conversation_summaries 表） |
| 修改 | `app/services/context_builder.py`、`app/prompts/builder.py`（注入 summary 段） |

## 实现步骤

1. `core/db.py`：增加 `conversation_summaries` 表（conversation_id 主键，一对话一行）。
2. `models/summary.py`：`ConversationSummary(conversation_id, summary, updated_at)`。
3. `repositories/summary_repository.py`：`get_summary(conv_id)`、`upsert_summary(conv_id, summary)`。
4. `prompts/summary.py`：滚动压缩模板，占位符 `{old_summary}`、`{new_messages}`。
5. `chains/summary_chain.py`：`ChatPromptTemplate | llm`（非结构化输出）。
6. `services/summary_service.py`：
   - `should_summarize(message_count, threshold)` 判断是否触发
   - `generate(old_summary, new_messages)` 调用 summary_chain
   - 触发器：`conversation_service.save_message` 后检查消息总数
7. `context_builder.py`：state 中携带 `summary`；`prompts/builder.py` 组装 Summary 段（在 Memory 段之后、Recent 之前）。

## 验收标准

- 20 轮（40 条）后自动触发摘要，结果正确概括早期内容
- 摘要滚动更新：新摘要 = 旧摘要 + 新消息的压缩，而非每次从头重算
- 超长对话的 prompt 长度不再随轮数无限增长
- 无摘要时（未达阈值）state.summary 为 None，prompt 跳过该段