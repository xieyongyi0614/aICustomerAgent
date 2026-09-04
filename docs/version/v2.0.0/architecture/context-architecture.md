# v2.0.0 Context Architecture

> 核心问题：**当前这一轮对话，角色真正需要知道什么？** v1 的答案是「全装进来再裁剪」（12000 字符预算 + 分段裁剪）；v2 的答案是五策略。

## 1. Context 分层

```text
Character Context（装配结果）
├── P0 身份与人格           Persona 静态段（基本不变，可缓存）
├── P0 当前 State           mood/energy/inner_state（≤120 字符，v1 沿用）
├── P1 当前意图/目标         Decision 输出 + active Goal（≤150 字符）
├── P1 关系切片             stage + 关键维度 + 最近里程碑（≤150 字符，v1 沿用）
├── P1 World 切片           时间/地点/环境/待决事件（≤600 字符，v1 沿用）
├── P2 Working Memory       最近 N 条消息 + 本轮结构化信号
├── P2 Long-term Memory     检索结果（P1 Phase 上线后语义排序）
├── P2 Development          高置信 Insight 摘要（≤100 字符，P3 后）
└── P3 表现指令             BehaviorStrategy/ActionBudget/Mode（v6.5 沿用）
```

优先级即裁剪顺序：预算不足时先砍 P3→P2，P0 永不砍。

## 2. 五策略

| 策略 | 规则 | 实现 |
|---|---|---|
| **Selection** | 每段先问「这轮对话用得上吗」：Memory 按 query 相关性检索（向量+结构混合），Goal 只取 top-3 active，World 只取当前切片 + 24h 内 due 事件 | context_builder 扩展 |
| **Priority** | 上表 P0–P3 分级；同段内按 salience 排序 | 装配器 |
| **Budget** | 继承总量 12000 与分段预算；新增：检索类内容（Memory/Insight）合并预算 800，超限按分数截断 | prompts/builder 沿用 `_fit_variable_parts` |
| **Compression** | 超预算的内容压缩而非丢弃：Working Memory 旧段→滚动 Summary（v1 已有）；Long-term Memory 每条已是一句话事实（设计上天然压缩）；Working Memory 中与本轮意图无关的机器人动作行可折叠 | 沿用 summary_chain |
| **Freshness** | 每条注入内容带新鲜度：Memory 注入 last_reinforced_at/recency 权重；被用户纠正过的记忆 24h 内不重复注入（防反复说错）；Insight 超过 supersede 立即出上下文 | Memory 域检索排序 |

## 3. 每轮装配算法（伪流程，不写代码）

```text
1. 固定段：Persona(P0) + State(P0)            —— 缓存命中
2. 动态段：意图/目标/关系/世界(P1)              —— 规则查询
3. 检索段：query = 用户消息 + 本轮意图
   Memory.retrieve(query, k=5, 混合打分)       —— P1 上线后走向量+结构
   Insight 高置信注入(P3 后)
4. Working Memory：最近 N 条(预算内) + Summary
5. 预算裁定：总 12000 → 超限从 P3 开始压缩/截断
6. 输出 sections + 每段实际 token 记入 prompt_snapshots（v1 已有）
```

## 4. 禁止事项

- 禁止把「所有长期记忆」全量塞入——检索是唯一入口（防 Context 无限增长）。
- 禁止 Reflection/Development 全量注入——只进 top 置信度且当前相关条目。
- 禁止绕过 Context Architect 直改 prompt（编排层外不允许拼 prompt）。
- 禁止注入未验证 Insight（confidence < 阈值或 invalidated）。

## 5. 可观测

prompt_snapshots 继续记录每段实际内容与裁剪情况；新增记录「检索段为何入选」（memory trace 的 context 部分回答：为什么召回这条/为什么没召回那条）。
