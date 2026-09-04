# Phase 3 Tasks — Character Development

## DEV-001 Development Aggregate 存储

- **Priority**: P0
- **Goal**: development_state / development_changes 两表 + 读写服务
- **Scope**: alembic 迁移；aggregate.py；status 语义（active/superseded/retired）
- **Dependencies**: P2 REF-001（结构风格一致，可并行开发）
- **Input**: architecture.md §1
- **Output**: 表 + 服务
- **Implementation Boundary**: 不接消费方
- **Acceptance Criteria**: 变更必留 before/after；downgrade 干净
- **Testing**: 迁移与单测
- **Risk**: 无

## DEV-002 DevPolicy 编译器

- **Priority**: P0
- **Goal**: Insight → 行为参数调制的确定性编译
- **Scope**: 三类 Insight 的调制规则；强度封顶；参数注入层（不改 v6.5 资产表本体）；矛盾仲裁
- **Dependencies**: DEV-001, P2 REF-004
- **Input**: active insights
- **Output**: development_state 变更 + 调制参数
- **Implementation Boundary**: 纯函数 0 LLM；不修改 BehaviorEngine 公式本体
- **Acceptance Criteria**: 同一 Insight 输入多次编译输出幂等；矛盾 Insight 只有一个生效且败者留痕
- **Testing**: 编译规则表驱动单测 + 幂等测试
- **Risk**: 调制幅度失衡 → 封顶参数进 settings + 离线校准

## DEV-003 行为接线（Behavior / ResponseStyle / Goal）

- **Priority**: P0
- **Goal**: 调制参数被运行时真实消费
- **Scope**: BehaviorEngine/ResponseStyleController/goal_service 读取叠加层；Flag 门控
- **Dependencies**: DEV-002
- **Input**: development_state
- **Output**: 行为可见变化
- **Implementation Boundary**: 只加读取层；golden 行为在无 development 数据时不变
- **Acceptance Criteria**: trace 可见 before/after 与 insight 溯源；Flag 关闭时叠加层为空
- **Testing**: 端到端行为对比测试
- **Risk**: 叠加层拖慢读取 → 内存缓存 + 变更时失效

## DEV-004 回退与重放

- **Priority**: P1
- **Goal**: Insight 失效后调制自动回退；全量可重放
- **Scope**: invalidated 事件订阅；按 key 重放调制历史；audit.py 重放工具
- **Dependencies**: DEV-002, P2 REF-005
- **Input**: Insight 状态变更
- **Output**: 回退后的 development_state
- **Implementation Boundary**: 重放不改原始审计行
- **Acceptance Criteria**: 用户反驳后行为参数回到失效前基线；重放结果与在线结果一致
- **Testing**: 重放一致性测试
- **Risk**: 无

## DEV-005 Trace 与评估接入

- **Priority**: P1
- **Goal**: Development 一致性与归因可测
- **Scope**: development_* trace 步骤；Evaluation 新增 development 规则集（归因完整率/一致性）
- **Dependencies**: DEV-003
- **Input**: 变更事件
- **Output**: trace + 评估报告
- **Implementation Boundary**: 只读旁路
- **Acceptance Criteria**: development_changes 100% 可追溯 insight_id（评估指标）
- **Testing**: evaluation.md Development 指标
- **Risk**: 无
