# Phase 2 Tasks — Reflection

## REF-001 Insight 存储与生命周期

- **Priority**: P0
- **Goal**: insights / reflection_runs / evidence_links 三表 + 生命周期状态机
- **Scope**: alembic 迁移；supersede/invalidated 转换；与 memory_links 风格一致的链式追溯
- **Dependencies**: 无（可与 P1 并行开发，启用依赖 P1）
- **Input**: design（见 architecture.md §1）
- **Output**: 表 + lifecycle 服务
- **Implementation Boundary**: 不接入任何消费方（P3 才接）
- **Acceptance Criteria**: 状态转换全部留痕（invalidated_reason 必填）；downgrade 干净
- **Testing**: 状态机单测
- **Risk**: 无

## REF-002 Evidence Window 聚合

- **Priority**: P0
- **Goal**: 从 Memory 检索聚合出合格证据组
- **Scope**: 按主题向量聚类分组（同 embedding 邻域 + 关键词混合）；窗口默认 30 天；输出组统计（数量/跨度/来源类型/印证度）
- **Dependencies**: P1 MEM-006（语义检索）
- **Input**: memories（active，非 hypothetical）
- **Output**: Evidence 候选组
- **Implementation Boundary**: 纯规则 0 LLM；单条记忆不得成组
- **Acceptance Criteria**: 构造场景「5 次说累」聚为一组且跨度/来源合规；孤立记忆不成组
- **Testing**: 构造数据集
- **Risk**: 聚类阈值敏感 → 阈值进 settings + 离线集校准

## REF-003 触发器

- **Priority**: P0
- **Goal**: 周期 + 事件两种反思触发，门槛前置
- **Scope**: 每日调度（background_jobs）；同主题 reinforce 计数达阈值事件触发；当日额度控制
- **Dependencies**: REF-001, REF-002, P1 MEM-009
- **Input**: 时钟、reinforce 事件流
- **Output**: 反思任务入队
- **Implementation Boundary**: 门槛检查在入队前（0 LLM）；每用户每日 ≤1 次
- **Acceptance Criteria**: 无证据日 0 调用；证据爆发日最多 1 次 LLM 反思
- **Testing**: 调度与额度测试
- **Risk**: 事件风暴 → 计数器带冷却窗口

## REF-004 反思执行器（Reflector）

- **Priority**: P0
- **Goal**: LLM Reasoning 调用与产出校准
- **Scope**: 反思 Prompt（证据组 + 类型约束 + 反例要求）；结构化输出解析；confidence 代码校准（按证据强度折算，LLM 给参考值）；三闸复检
- **Dependencies**: REF-002, REF-003
- **Input**: Evidence 组
- **Output**: insights 行 + evidence_links + reflection_runs
- **Implementation Boundary**: LLM 只产候选；终值与入库由代码决定；禁止写其他域
- **Acceptance Criteria**: 产出 100% 带 ≥门槛数证据引用；confidence 与证据强度单调一致
- **Testing**: Prompt 回归集；幻觉注入测试（证据被篡改时结论必须降级或拒绝）
- **Risk**: LLM 过度概括 → 反例字段强制 + Judge 抽查

## REF-005 反驳与失效通道

- **Priority**: P1
- **Goal**: 用户可推翻 Insight
- **Scope**: 澄清类用户话语识别（复用记忆冲突通道风格）→ invalidated；新反思结论与旧 Insight 冲突 → superseded
- **Dependencies**: REF-001, REF-004
- **Input**: 用户话语 / 新 Insight
- **Output**: 状态迁移 + trace
- **Implementation Boundary**: 不删除行（审计保留）
- **Acceptance Criteria**: 「其实我最近不累」→ 对应 Insight invalidated 且当轮退出 Context
- **Testing**: 反驳表述变体集
- **Risk**: 误失效正确 Insight → 需高匹配度 + 保守阈值

## REF-006 Reflection Trace 与评估接入

- **Priority**: P1
- **Goal**: 「为什么形成这个 Reflection」可答；质量可测
- **Scope**: reflection_* trace 步骤；Evaluation 新增 reflection 规则集 + Judge 维度；离线误报率场景
- **Dependencies**: REF-004
- **Input**: 反思全链路事件
- **Output**: trace + 评估报告
- **Implementation Boundary**: 只读旁路
- **Acceptance Criteria**: 噪声场景误报率 0；每条 Insight 可回溯完整证据链
- **Testing**: evaluation.md Reflection 指标
- **Risk**: 无
