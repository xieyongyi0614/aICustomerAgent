# v2.0.0 Architecture Risk Register

> 格式：Risk / Cause / Impact / Mitigation。设计期识别，实现期每 Phase 复核。

| # | Risk | Cause | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **LLM 调用总量上升** | 反思/记忆判定/规划叠加在 v1 的 8–10 次/轮之上 | 成本与延迟失控 | 任务清单逐项裁决（llm-orchestration.md）；规则预筛 + 小模型分层 + 批处理 + 每日预算熔断；Phase 交付时调用数不得超基线 ×1.2 |
| R2 | **Token 爆炸** | Memory/Insight/Shared Experience 越积越多进 context | Prompt 超长、费用、质量下降 | Context 五策略 + 检索是唯一入口 + 合并预算 800 字符 + prompt_snapshots 监控 |
| R3 | **Memory 污染** | Roleplay/假设/玩笑/错误信息被存为事实 | 角色记忆失真，用户体验崩坏 | Candidate 源标记（user_stated/user_derived/hypothetical）；hypothetical 直接拦截；低置信候选门槛；显式 forget 全通道清除 |
| R4 | **Memory 冲突处理错误** | 矛盾陈述并存、或误删正确记忆 | 角色「又记错」 | supersede 保留链条可追溯；merge 需同主题高相似；冲突时保守保留两者并标记 pending；评估集覆盖 |
| R5 | **False Memory** | LLM 抽取阶段编造 | 角色相信没发生的事 | source 必须回指消息 id；ai_inferred 无证据硬丢弃（沿 V4 铁律）；Judge 抽查虚构记忆（V7.5 已有） |
| R6 | **Reflection 幻觉写入真相** | LLM 从零星证据跳到强结论 | 错误认知永久影响行为 | 三闸：证据数量门槛 + confidence 阈值 + 结论类型约束；Insight 可 invalidated/superseded；禁止直写 State/Relationship 数值 |
| R7 | **Relationship ↔ Memory 循环依赖** | 关系读记忆、记忆又读关系 | 级联更新、不可重放 | 依赖矩阵单向（Relationship→Memory）；Memory 域禁止 import relationship 数值 |
| R8 | **Autonomy / Life Loop 无限运行** | 触发器互相唤醒、周期任务自触发 | 消息风暴、成本失控 | Trigger 去重 + Cooldown + 每日 Action 上限（v1 沿用）+ Idle 判定 + 周期任务禁止再排周期任务 |
| R9 | **Life Loop 成本失控** | while true + LLM | 破产 | 预算熔断（全局日配额）+ 每周期记账 + Idle 零调用 + 周期 LLM 仅 Decision 命中时 |
| R10 | **数据库写放大** | last_accessed/reinforce/snapshot 每轮写 | IO 瓶颈 | 读路径写回改批 flush；快照降频；embedding 攒批 |
| R11 | **Vector DB 依赖错位** | 把 pgvector 当 SoT 或强依赖 | 检索空窗、数据"丢失"错觉 | SoT=业务表；embedding NULL 允许（降级结构化检索）；全量重建脚本 |
| R12 | **Context 无限增长** | 新域都想注入 | R2 同因 | 预算硬顶不分版本上调；新增注入段必须申报预算并挤占既有段 |
| R13 | **v1→v2 迁移破坏数据** | 改列义/硬删/一次性切换 | 历史记忆丢失 | 只增列不改义；迁移脚本 dry-run+回滚；Flag 灰度；双读窗口（见 migration/v1-to-v2.md） |
| R14 | **单进程后台天花板** | asyncio 单进程既跑前台又跑周期 | 周期任务饿死前台 | Job 表协议化（P1）；量级触发重审阈值：日活>100 或周期任务 P95 延迟>30s 时抽离 Worker 进程（表协议不变） |
| R15 | **概念债复发** | 新版本再造第五种「动作」 | 架构退回 v1 混乱 | domain-boundaries.md 概念债表为评审清单；新概念入域需更新该文档 |
