# Phase 6 Tasks — Advanced Autonomy

> Schema 与分层约定同 [phase-1](../phase-1-memory/tasks.md)。依赖图见 [../../dependency-graph.md](../../dependency-graph.md)。

## Capability Map

```text
Foundation:   AUT-001 Goal 层级与存储扩展
Core:         AUT-002 Planning 执行器 / AUT-003 观察与调整
Integration:  AUT-004 Goal 冲突与生命周期管理
Observability+Evaluation: AUT-005
预算硬顶（任务书 §十四）: Sub-Goal 深度 ≤2、数量 ≤5/树、Planning LLM ≤3 次/goal 生命周期、Sub-Goal 连续失败阈值后转 failed 禁止无限重试、单 goal 最长执行周期可配
并行声明: AUT-001 可提前开发；AUT-002~004 开发可提前（启用依赖 P5）
```

## AUT-001 Goal 层级与存储扩展（Foundation）

- **Priority**: P0
- **Objective**: goals 支持层级与域分类（short/long × personal/relationship/world）
- **Problem**: v1 Goal 是扁平 4 类规则列表（v1 审计），无层级则无法表达长期追求；无 domain 则 Personal Goal 无从 Development 供给
- **Scope**: 扩列 parent_goal_id/layer/domain/failure_reason；goal_plans 表（Sub-Goal 树+完成判据）；goal_service 层级查询
- **Non-Scope**: 既有 4 类 conversation/scene goal 语义不变向后兼容；不做 Planning；不迁移旧 goal 为层级
- **Inputs**: [../phase-6-autonomy README](README.md) §核心能力 1
- **Outputs**: 表结构 + 服务扩展
- **Dependencies**: 无（可提前开发；启用依赖 P5）
- **Architecture References**: README §核心能力；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §1 Goal 行
- **Domain Boundary**: Goal（只写本域表；不写 Scene/World；不被 Memory 反向写）
- **Data Changes**: goals 扩 4 列（旧行 layer/domain 默认空=走 v1 路径）；新表 goal_plans；downgrade 干净
- **Runtime Flow**: 无运行时行为（存储层）
- **LLM Usage**: NONE
- **State Machine**: 旧状态机不变；新状态（suspended/failed/abandoned）在 AUT-004 定义
- **Idempotency**: 迁移幂等
- **Feature Flag**: `v2_autonomy_advanced_enabled` 定义 default=false
- **Error/Failure**: 迁移往返兜底
- **Observability**: 表级字段
- **Testing**: Unit=层级查询；Integration=迁移+旧 goal 回归
- **Acceptance Criteria**: 给定 v1 旧 goal 行，当升级后运行，那么行为与 v1 一致（层级字段空走旧路径）；给定层级查询，那么父子关系正确
- **Regression**: V6 goal checklist
- **Evaluation**: 无（供 AUT-005 依赖）
- **Risk**: 无

## AUT-002 Planning 执行器（Core）

- **Priority**: P0
- **Objective**: Goal → Sub-Goal 树的可执行规划（Plan Validation 前置）
- **Problem**: 任务书 §十四：禁止「LLM 随便生成任务然后无限执行」——规划必须过可执行性校验才入库
- **Scope**: Planning Prompt（目标+能力清单+World/Development 约束）；可执行性校验（Capability 对齐、判据可判定）；深度≤2/数量≤5/LLM≤3 次·goal 封顶
- **Non-Scope**: 执行调度归 Life Loop（P5）；常规调整不调 LLM；规划不直接执行任何 Action
- **Inputs**: goal、capability registry、World/Development 约束
- **Outputs**: goal_plans + Sub-Goals（每步有完成判据）
- **Dependencies**: AUT-001, P5 LIFE-002（执行底座）
- **Architecture References**: README §核心能力 3；[../../architecture/llm-orchestration.md](../../architecture/llm-orchestration.md) §1 Goal Planning 行
- **Domain Boundary**: Goal（只写本域；对 World 的影响只能通过 Action）
- **Data Changes**: goal_plans 写入
- **Runtime Flow**: 目标创建/受阻/重规划 → 组装 Planning 输入 → LLM 规划 → 校验闸 → [通过→入库 | 拒绝→降级或放弃+trace]
- **LLM Usage**: main 档；触发=创建/受阻/重规划；≤3 次/goal 生命周期（可配）；重试 1 次（解析失败）；fallback=放弃规划并 trace；禁止前台
- **State Machine**: plan: draft→validated→active|rejected
- **Idempotency**: 同 goal 同版本规划幂等（重规划产生新版本，旧版留痕）
- **Feature Flag**: `v2_autonomy_advanced_enabled`，OFF=v1 扁平 goal 路径
- **Error/Failure**: LLM 失败→重试 1 次后放弃；校验拒绝→trace 原因，不静默降级执行
- **Observability**: goal_planning trace（输入约束/原始规划/校验结果）——「为什么这么拆」可答
- **Testing**: Unit=校验闸；Integration=规划回归集；FailureInjection=LLM 失败与不切实际规划
- **Acceptance Criteria**: 给定规划产物，那么 100% 通过可执行性校验且判据可自动判定；给定同一 goal 第 4 次规划请求，那么被拒绝并 trace
- **Regression**: Flag OFF golden
- **Evaluation**: [evaluation.md](evaluation.md) E-AUT-01
- **Risk**: 规划不切实际→校验闸+能力清单约束

## AUT-003 观察与调整（Core / Observation · Progress · Adjustment）

- **Priority**: P0
- **Objective**: Sub-Goal 执行被观察、被调整；完成/失败语义落地
- **Problem**: 无观察调整则规划是一次性的，Goal 无法「追求」只算「存在」（§十四 Observation→Adjustment 缺口）
- **Scope**: Life Loop 周期内检查完成判据（Action 结果+World 状态）；调整规则（顺序/拆分/放弃，纯规则）；失败计数（连续失败达阈值→failed，禁止无限重试）；单 goal 最长执行周期封顶
- **Non-Scope**: 常规调整纯规则（重规划才调 LLM→AUT-002 通道）；不改 Action/World 引擎
- **Inputs**: plan 执行状态、Action 结果、World 状态
- **Outputs**: Sub-Goal 状态迁移 + 调整 trace
- **Dependencies**: AUT-002, LIFE-002
- **Architecture References**: README §核心能力 3；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §1 Goal「不能做什么」
- **Domain Boundary**: Goal 域（观察读 Action/World 投影；推进只写 goal/goal_plans）
- **Data Changes**: goals 状态/计数；goal_plans 进度
- **Runtime Flow**: 周期 → 判据检查 → [达成→推进/完成 | 未达成→失败计数→调整或 failed]
- **LLM Usage**: NONE（调整规则全确定性）
- **State Machine**: sub_goal: pending→in_progress→done|failed；goal: active→completed|failed|abandoned（见 AUT-004）；failed 后仅允许一次重规划
- **Idempotency**: 判据检查幂等；失败计数按事件幂等
- **Feature Flag**: `v2_autonomy_advanced_enabled`
- **Error/Failure**: 判据异常→该步跳过+trace；连续异常→goal 转 failed 不无限重试
- **Observability**: goal_observation trace（判据/结果/计数）——「为什么推进/为什么失败」可答
- **Testing**: Unit=判据与失败阈值；Integration=完成与失败路径
- **Acceptance Criteria**: 给定判据达成，当周期检查，那么自动推进不调 LLM；给定 Sub-Goal 连续失败达阈值，那么 goal 转 failed 且记录 failure_reason，不再重试
- **Regression**: Flag OFF golden
- **Evaluation**: [evaluation.md](evaluation.md) E-AUT-02
- **Risk**: 判据不可自动判定→规划期校验闸负责拦截

## AUT-004 Goal 冲突与生命周期管理（Integration）

- **Priority**: P1
- **Objective**: Priority/Conflict/Persistence/Failure/Completion/Abandonment 六语义落地
- **Problem**: 任务书 §二十三要求全部六语义裁决；缺冲突仲裁则多目标互相打架，缺 abandonment 则僵尸目标永久占预算
- **Scope**: 仲裁器（显式优先级 + Development/Relationship 调制）；同域冲突取高优先级 active 另一 suspended 留痕；abandonment 需置信判定（长期无进展+低相关）+trace
- **Non-Scope**: 仲裁不删除行；Goal 不写 Scene/Memory/World；调制读 P3/P4 只读参数
- **Inputs**: goals + 调制参数（DEV/REL 只读）
- **Outputs**: 仲裁结果 + 全程 trace
- **Dependencies**: AUT-001, P3 DEV-003
- **Architecture References**: README §核心能力 2 表；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §1 Goal 行
- **Domain Boundary**: Goal（读 Dev/Rel 只读参数；写本域）
- **Data Changes**: goals.status/仲裁留痕字段
- **Runtime Flow**: 目标集合变更/周期 → 优先级仲裁 → [冲突→suspended 留痕 | 无冲突→active] → abandonment 检查 → trace
- **LLM Usage**: NONE（abandonment 置信为规则计算）
- **State Machine**: active↔suspended；active→completed|failed|abandoned（终态）；非法转换拒绝
- **Idempotency**: 仲裁幂等（同输入同结果）
- **Feature Flag**: `v2_autonomy_advanced_enabled`
- **Error/Failure**: 仲裁异常→维持当前态+告警
- **Observability**: goal_arbitration trace（冲突双方/优先级来源/结果）——「为什么这个目标暂停/放弃」可答
- **Testing**: Unit=状态机全路径；Integration=冲突/放弃场景
- **Acceptance Criteria**: 给定同域冲突两目标，当仲裁，那么仅一个 active 且另一 suspended 可溯；给定长期无进展低相关 goal，那么按阈值 abandoned 且用户对话中可自然可见
- **Regression**: Flag OFF golden
- **Evaluation**: [evaluation.md](evaluation.md) E-AUT-03
- **Risk**: abandonment 误判→阈值保守+用户可见

## AUT-005 Goal 评估与回归（Observability / Evaluation）

- **Priority**: P1
- **Objective**: Goal Consistency 可测；P6 验收闭环
- **Problem**: 「目标不无故消失/翻转」必须量化，否则追求行为不可信
- **Scope**: Evaluation 新增 goal 规则集（一致性/完成失败语义/规划质量 Judge）；跨会话剧情离线测试集；v2.0.0 autonomy regression-checklist
- **Non-Scope**: 只读旁路
- **Inputs**: goal 全生命周期数据、剧情集
- **Outputs**: 评估报告 + regression-checklist
- **Dependencies**: AUT-003, AUT-004
- **Architecture References**: [../../architecture/evaluation.md](../../architecture/evaluation.md) §1 Goal 行
- **Domain Boundary**: 横切质量平面
- **Data Changes**: 无
- **Runtime Flow**: 剧情/数据 → 指标 → 报告
- **LLM Usage**: Judge 采样（规划质量）
- **State Machine**: 无
- **Idempotency**: 可重复执行
- **Feature Flag**: ON/OFF 双态执行
- **Error/Failure**: Judge 失败→skipped 重跑
- **Observability**: 即本 Task
- **Testing**: 即测试本身
- **Acceptance Criteria**: 给定剧情集，当评估，那么目标不无故消失/翻转且规划质量 Judge 达标；给定 Flag OFF，那么与 v1 字节级一致
- **Regression**: V6/V7 checklist + 本目录 regression-checklist
- **Evaluation**: E-AUT-01~03 汇总
- **Risk**: 无

---

## Phase 6 Milestone（交付序）

```text
M1 Foundation:  AUT-001（可提前）
M2 Core:        AUT-002 → AUT-003（等 P5）
M3 Integration: AUT-004
M4 Acceptance:  AUT-005 → Eval Gate + Regression Gate（含跨会话剧情）→ 申请开启 v2_autonomy_advanced_enabled → v2.0.0 全量
```

