# Phase 1 — Memory 2.0

> Flag：`v2_memory_enabled`（总闸）+ `v2_memory_vector_enabled`（语义检索子闸）
> 依赖：无（v2 起点）｜后续：Reflection / Relationship / Life Loop 的地基

## 目标

把 v1 的「扁平抽取器」升级为**双层记忆系统**：

- **Working Memory**：每轮重建（最近消息 + 本轮结构化信号 + 活跃 Scene/Action），不落长期表。
- **Long-term Memory**：完整生命周期 + 语义检索 + 混合排序。

## 解决的问题（对应 v1 审计）

1. 检索是字符级 Jaccard，同义改述就召回失败 → 语义检索。
2. 无生命周期：无 reinforce/merge/decay，只有 TTL → 完整状态机。
3. forget 是硬 DELETE → 软删 + 保留期。
4. 五种摄取源各自为政 → 统一 MemoryCandidate 通道。
5. Roleplay/假设内容误存 → 源标记 + 拦截。

## 核心能力清单

1. 记忆类型体系（7 类封顶）与类型裁决。
2. Candidate 摄取 → 评估（规则优先，LLM 兜底）→ 转正。
3. 生命周期状态机：active → reinforced → merged/superseded/invalidated → decayed → forgotten。
4. pgvector 语义检索 + 结构化加权混合排序（pgvector 是索引，SoT 是业务表）。
5. 用户显式 remember / forget 命令通道。
6. Memory Trace（为什么记住/没记住/为什么召回这条）。

## 文档

- [architecture.md](architecture.md) —— 模块结构、数据流、接口边界
- [design.md](design.md) —— 数据模型、生命周期规则、检索算法、类型裁决、技术选型论证
- [tasks.md](tasks.md) —— MEM-001 ~ MEM-010

## 完成标准（验收）

1. Flag 关闭时行为与 v1 字节级一致（golden 不变）。
2. 跨会话语义召回：改述表达仍可召回（离线标注集 recall ≥ 0.8）。
3. 显式记住/忘记立即生效且全通道不可见（含向量）。
4. 生命周期全链路有 trace；candidate 摄取幂等（重复源不重复转正）。
5. 前台 LLM 调用数不高于 v1 基线；后台新增调用全部规则预筛过。
