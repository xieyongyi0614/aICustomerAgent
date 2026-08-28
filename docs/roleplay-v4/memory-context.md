# Memory Context

## 1. 背景

V1 将 `memories` 以列表形式进入 ConversationState，注入格式无排序/去重/预算控制。

## 2. 注入规则

| 规则 | 设计 |
|---|---|
| 每轮最多注入 | 5 条（settings.memory_top_k），字符预算 400（超出截断丢弃低分记忆） |
| 排序 | 召回 score 降序（相关性优先，其次 importance、recency 已在 score 中） |
| Prompt 格式 | `【你记得关于用户的事】` + 每条一行 `- (类型) 内容`，不暴露 confidence/source/status 给模型 |
| 去重 | 注入前按 content 精确去重 + 包含去重（沿用 exists_similar 逻辑），同一轮只出现一次 |
| 冲突记忆 | status 机制保证只有 active 记忆被召回，superseded/invalidated 天然不冲突；active 记忆间若字面矛盾（提取层已由 Conflict Resolver 阻止），此处不再二次处理 |
| 过期记忆 | expires_at < now 不召回 |
| 防重复念叨 | last_accessed_at 参与打分：刚被引用过的记忆 recency 上升反而可能重复出现——通过在 Prompt 段附加规则"已提到过的事不要复述，除非用户问起"约束表达层；V4 不做"本轮已用记忆"状态跟踪（P2） |

## 3. 组装路径

```text
Memory Retriever → list[UserMemoryV4]
  → context_builder.build() 写入 ConversationState.memories
  → PromptBuilder memory 段渲染（沿用现有分节机制）
```

- `ConversationState.memories` 类型升级为 V4 模型（含 status/source 内部字段，序列化给 Prompt 前过滤）。
- 空 memories → memory 段整体省略，与 V1 兼容。

## 4. Prompt 膨胀控制

- 硬预算：5 条 × 50 字 ≈ 400 字上限。
- 记忆是"背景资料"不是"剧情素材"：Prompt 段标注"仅在自然相关时引用，不要主动罗列"。
- 与 summary / scene 段职责互斥：短期上下文归 summary，当下归 scene，记忆只放跨会话长期信息。

## 5. 验收标准

- 注入条数/字符数上限被强制执行。
- 无记忆时输出与 V1 逐字节一致（兼容测试）。
- superseded/invalidated 记忆在任何 Prompt 中不可见。
