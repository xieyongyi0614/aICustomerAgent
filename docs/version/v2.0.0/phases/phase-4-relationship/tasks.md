# Phase 4 Tasks — Long-term Relationship

## REL-001 真相源统一（转写通道）

- **Priority**: P0
- **Goal**: 消除关系事实双真相源
- **Scope**: 里程碑/冲突解决/重要关系事件 → 经 P1 ingest 通道转写为 relationship_fact 记忆（source_ref 回指账本行）；v1 遗留 relationship_event 类型记忆的数据迁移映射为 relationship_fact
- **Dependencies**: P1 MEM-002/005
- **Input**: relationship_events/milestones/conflicts 状态变更
- **Output**: relationship_fact 记忆 + 迁移脚本
- **Implementation Boundary**: 账本仍是数值唯一真相；Memory 只存叙事；禁止 Relationship 域直写 memories 表（走 ingest）
- **Acceptance Criteria**: 每条重要关系事件在账本与记忆中各司其职且可互相溯源；旧类型记忆迁移后检索语义不变
- **Testing**: 迁移前后检索对比；双写一致性测试
- **Risk**: 迁移遗漏 → dry-run 报告 + 双读校验窗口

## REL-002 Shared Experience 投影

- **Priority**: P0
- **Goal**: 「共同经历」可查询、可注入
- **Scope**: 只读投影服务（experience + relationship_fact + 完结 world_events 中双人参与项）；Context 新增 shared experience 段（预算内、Freshness 排序）
- **Dependencies**: REL-001
- **Input**: Memory + events
- **Output**: 共同经历列表（时间序）+ Context 段
- **Implementation Boundary**: 零新表（视图/服务投影）；投影可重算
- **Acceptance Criteria**: 投影结果与源数据一致（对账测试）；Context 段 ≤ 预算
- **Testing**: 对账 + 检索注入测试
- **Risk**: 投影查询慢 → 索引 + 结果短缓存

## REL-003 Relationship Patterns 接入

- **Priority**: P1
- **Goal**: 关系模式（来自 Development）影响关系行为
- **Scope**: 读取 development patterns(scope=relationship) → 注入关系 Context 段与 AutonomyPolicy 参考（只读调制）
- **Dependencies**: REL-001, P3 DEV-003
- **Input**: development_state
- **Output**: Context 关系段扩展 + 闸门参考
- **Implementation Boundary**: 不写任何数值；不改 v8.5 闸门结构
- **Acceptance Criteria**: Pattern 变化在 Context 段可见；Flag 关闭时无注入
- **Testing**: 端到端注入测试
- **Risk**: Pattern 噪声 → 只取 strength ≥ 阈值条目

## REL-004 叙事里程碑与评估

- **Priority**: P1
- **Goal**: Insight 驱动的里程碑 + 关系域评估
- **Scope**: 高置信 relationship 类 Insight 达到叙事里程碑条件 → milestone 落账本 + 转写记忆；Evaluation 新增 relationship 一致性规则（账本重放对账 + 真相源审计）
- **Dependencies**: REL-002, P2 REF-004
- **Input**: insights + milestones
- **Output**: 新里程碑 + 评估报告
- **Implementation Boundary**: 数值里程碑判定逻辑不动；叙事里程碑只增不改
- **Acceptance Criteria**: V8.5 数值回归字节级一致；每条里程碑可回答来源
- **Testing**: V8.5 regression-checklist 重跑 + 新增场景
- **Risk**: 里程碑泛滥 → 叙事里程碑白名单类型 + 频控
