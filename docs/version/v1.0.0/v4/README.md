# Roleplay V4：Long-term Memory System

> 状态：规划完成，待实现
> 前置：V2（角色状态）已完成；V3（场景状态与行为连续性）按计划进行中，V4 依赖其中仅有的两个稳定点：`agent_service` 后处理模式与 `scene_state` 持久化模式。

## 一句话定义

让角色记住"过去发生过什么"：跨会话长期记忆的提取、策略过滤、冲突管理、召回与注入——但绝不变成无限增长的聊天记录数据库。

## V3 → V4 的接续

```text
V2：亚丝娜应该怎么说话？
V3：亚丝娜现在正在做什么？   ← Scene State + Pending Action
V4：亚丝娜记得我们以前发生过什么？ ← Long-term Memory
V5：亚丝娜和用户现在是什么关系、什么情绪？
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 现状分析、整体架构、V2/V3 边界 |
| [memory-model.md](memory-model.md) | Memory 分类、Candidate 数据结构、绑定层级决策 |
| [memory-extraction.md](memory-extraction.md) | Memory Extractor（升级现有 extractor_chain） |
| [memory-policy.md](memory-policy.md) | 保存/丢弃策略、禁止 AI 猜测入库 |
| [memory-retrieval.md](memory-retrieval.md) | 结构化召回（无 Vector DB） |
| [memory-context.md](memory-context.md) | 记忆注入 Prompt 的数量/排序/去重/膨胀控制 |
| [memory-update.md](memory-update.md) | 更新管线（后台异步，不阻塞 SSE） |
| [memory-conflict.md](memory-conflict.md) | update / supersede / invalidate 机制 |
| [privacy.md](privacy.md) | 删除、纠正、"不要记住" |
| [testing.md](testing.md) | 10 项测试设计 |
| [tasks.md](tasks.md) | 任务注册表（开发入口） |

## 核心决策记录

1. **升级而非重建**：V1 已有 `memories` 表 + extractor + 检索；V4 在其上增量扩展（source/confidence/status 字段、策略层、冲突层、隐私层），废弃字符级 `_tokenize` 检索打分。
2. **绑定层级：user + character**，不绑 session/conversation（理由见 memory-model.md）。
3. **4 类记忆**：user_preference / user_fact / important_event / relationship_event（旧 5 类映射迁移）。
4. **AI 推测永不入库**：Candidate 必须 source ∈ {user_stated, user_derived}，`ai_inferred` 一律丢弃。
5. **第一版不用 Vector DB / RAG / Embedding**：结构化召回（相关性 + importance + recency + type 权重）已满足当前规模（单用户记忆 ≤ 数百条）。
6. **软失效不硬删**：冲突旧记忆置 `superseded`/`invalidated`；只有用户明确要求删除才硬删。
7. **不碰 V3**：Memory 不写入 Scene State，不参与 PendingAction 迁移。

## 验收判据

V4 完成后：
1. 角色能跨会话引用用户长期偏好/事实（"你上次说不喜欢咖啡"）。
2. 冲突信息自动 supersede 旧记忆，不产生两条矛盾记忆。
3. 用户说"不要记住这件事"时，记忆不保存/被删除。
4. 单用户记忆条数有界（上限 + 失效回收），普通闲聊零入库。
5. 记忆全链路后台执行，SSE 首 token 时延不受影响。
