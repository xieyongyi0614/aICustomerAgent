# Phase 6 Tasks — Advanced Autonomy

## AUT-001 Goal 层级与存储扩展

- **Priority**: P0
- **Goal**: goals 支持层级与域分类
- **Scope**: 扩列 parent_goal_id/layer/domain/failure_reason；goal_plans 表（Sub-Goal 树 + 完成判据）；goal_service 层级查询
- **Dependencies**: 无（可提前开发，启用依赖 P5）
- **Input**: architecture（README §核心能力 1）
- **Output**: 表结构 + 服务扩展
- **Implementation Boundary**: 既有 4 类 goal 语义不变，向后兼容
- **Acceptance Criteria**: 旧 goal 行为回归不变；层级查询正确
- **Testing**: 迁移 + 回归
- **Risk**: 无

## AUT-002 Planning 执行器

- **Priority**: P0
- **Goal**: Goal → Sub-Goal 树的可执行规划
- **Scope**: Planning Prompt（目标 + 能力清单 + World/Development 约束）；可执行性校验（Capability 对齐）；深度/数量封顶
- **Dependencies**: AUT-001, P5（Life Loop 提供执行）
- **Input**: goal
- **Output**: goal_plans + Sub-Goals
- **Implementation Boundary**: LLM 低频（创建/受阻/重规划）；产出必须过校验才入库
- **Acceptance Criteria**: 规划产物 100% 通过可执行校验；LLM 频率 ≤ 每 goal 3 次
- **Testing**: 规划回归集 + 校验拦截测试
- **Risk**: 规划不切实际 → 校验闸 + 能力清单约束

## AUT-003 观察与调整

- **Priority**: P0
- **Goal**: Sub-Goal 执行被观察、被调整
- **Scope**: Life Loop 周期内检查完成判据（Action 结果 + World 状态）；调整规则（顺序/拆分/放弃）；失败计数
- **Dependencies**: AUT-002, LIFE-002
- **Input**: plan 执行状态
- **Output**: Sub-Goal 状态迁移 + 调整 trace
- **Implementation Boundary**: 常规调整纯规则；重规划才调 LLM
- **Acceptance Criteria**: 判据达成自动推进；连续失败触发 failed 而非无限重试
- **Testing**: 判据与失败路径测试
- **Risk**: 判据不可自动判定 → 要求规划期产出可判定判据（校验闸负责）

## AUT-004 Goal 冲突与生命周期管理

- **Priority**: P1
- **Goal**: Priority/Conflict/Persistence/Failure/Completion/Abandonment 六语义落地
- **Scope**: 仲裁器（优先级 + Development/Relationship 调制）；suspended/failed/abandoned 状态机；Goal Trace
- **Dependencies**: AUT-001, P3 DEV-003
- **Input**: goals + 调制参数
- **Output**: 仲裁结果 + 全程 trace
- **Implementation Boundary**: 仲裁不删除行；abandonment 需置信判定
- **Acceptance Criteria**: 冲突目标仅一个 active 且可追溯；六状态转换全覆盖测试
- **Testing**: 状态机全路径测试
- **Risk**: abandonment 误判 → 阈值保守 + 用户可见（对话中可自然提及）

## AUT-005 评估与回归

- **Priority**: P1
- **Goal**: Goal Consistency 可测
- **Scope**: Evaluation 新增 goal 规则集（一致性/完成失败语义/规划质量 Judge）；跨会话剧情离线测试集
- **Dependencies**: AUT-003, AUT-004
- **Input**: goal 全生命周期数据
- **Output**: 评估报告 + regression-checklist
- **Implementation Boundary**: 只读旁路
- **Acceptance Criteria**: 目标不无故消失/翻转（一致性指标达标）
- **Testing**: 剧情集
- **Risk**: 无
