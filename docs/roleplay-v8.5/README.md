# Roleplay V8.5：Relationship Evolution System（关系演化系统）

> 状态：**设计完成，待实现**。任务入口 tasks.md。前置：V1~V7.8 全部完成；与 V8（World State System，设计完成待实现）**相互独立、无实现依赖**，可任意先后实现。
> 定位：**V8.5 不是推倒 V5，而是 V5 关系域的深化**——V5 已把关系"事件化"（LLM 判定事件 + 查表 delta + 三级限速 + 同事务账本 + 阶段滞回），V8.5 补齐它没有的：更完整的维度、演化动力学、里程碑、冲突生命周期、关系记忆、关系上下文、评估护栏与版本化。

## 1. V8.5 解决什么问题

用户对关系系统的四问，V5 只答了一半：

| 问题 | V5 现状 | V8.5 补齐 |
|---|---|---|
| 为什么变化？ | 有（LLM 事件判定 + 查表 delta，禁止无因加分） | 不变，信号语义更细 |
| 什么时候变化？ | 有（回合后 state_update 步骤） | 不变，时间演化补齐（疏远检测、张力消退） |
| 什么事件导致变化？ | 粗（9 种事件类型 + 三档强度） | InteractionSignal：互动类型 × 质量 × 显著度 × 新颖度（14 种互动类型） |
| 变化是否合理？ | **无**（限速只是防跳变，不是合理性审计） | Relationship Evaluation：跳变 / 无因变化 / 超限 / 非法迁移四类护栏 |

除此之外，V5 还有五块结构性缺失：

1. **维度不全**：只有 intimacy/trust/familiarity/tension，缺 respect（尊重）与 comfort（自在）——"敬佩"与"相处累不累"无法表达。
2. **动力学缺失**：delta 与当前状态无关——0.90 的 trust 和 0.40 的 trust 涨同样的分；同一种好被重复一百次效果不变；没有信任"升慢降快"的不对称。
3. **无里程碑**：第一次袒露心事、第一次兑现承诺、第一次和解——这些"关系编年史"只留下匿名的事件行。
4. **无冲突生命周期**：tension 是标量不是状态机；久不联系（neglect）完全不可见；没有道歉→修复→原谅的语义。
5. **消费端隐式**：行为与自主只查 stage 和两个标量，没有"关系上下文"把关系状态翻译成行为语言。

## 2. 设计原则（不可妥协）

- **原则 1：Relationship ≠ Emotion。** 情绪是分钟~小时级状态，关系是天~周级积累。今天开心不会立即加 trust；两者是同一检测器的两个输出，各走各的表，禁止换算（V5 口径重申）。
- **原则 2：变化必须有因。** 状态的每一次变化都必须能追溯到信号 → 事件/里程碑/冲突结算/显式漂移四类"因"之一；无账本对应的变化是评估体系里的 fail 级问题（无因不变量）。
- **原则 3：代码独占演化权。** LLM 只负责"发生了什么"（信号识别），delta 计算、动力学修饰、限速、阶段、持久化全部是代码纯函数——LLM 全程无分数修改权（V5 口径重申）。
- **原则 4：默认态零渲染变化。** 默认关系状态（新维度取默认值、无里程碑、无冲突）下 Prompt 与 V5 逐字节一致，golden 快照零重生成——"默认关系 golden 不变"是机器可证底线（对齐 V8 的"空世界 golden 不变"）。
- **原则 5：确定性优先、失败只降级。** 演化是纯函数（同一事件流重放 = 同一状态时间线，这是回滚的基础）；LLM 信号通道失败走启发式兜底；里程碑/冲突检测失败跳过当轮；一切新逻辑异常不阻塞回合。
- **原则 6：热路径零新增。** 全部演化逻辑在回合后 state_update 步骤内（STEP_HANDLERS 不变），P0 零新增 LLM 调用（只扩展现有 TurnAnalysis 输出字段）。

## 3. 硬边界（V8.5 明确不做）

- **不实现 Multi Character / 真实社交平台 / Voice / Tool Calling**（用户约束，整体沿用）。
- **不重命名 intimacy**：题设 affection ≡ intimacy，沿用既有列名与字段名（V5 不采纳 closeness 的同一决策），文档记录映射。
- **不改阶段体系**：四级 stage + 阈值 + 滞回 + tension 冻结原样保留（V5 已论证 5 级无增益）；新维度不参与阶段阈值判定。
- **不做关系间自动换算**：维度之间的联动只通过显式规则（冲突拉低 comfort、尊重影响语气档），不引入隐式矩阵。
- **不实现 LLM 关系 judge**：评估护栏全部确定性规则，LLM judge 留白。
- **不消费 V8 World**：世界事实（共同经历佐证、场景互动）作为未来可选信号源留白，V8.5 核心闭环不依赖 V8 实现。

## 4. 核心设计一览

| 模块 | 职责 | 核心载体 | 落点 |
|---|---|---|---|
| M1 Relationship Model | 5+1 维状态模型、派生指标、阶段语义冻结 | RelationshipState（扩列） | `app/models/relationship.py` + 迁移 |
| M2 Interaction Analyzer | 互动信号识别（启发式 + 既有 LLM 字段扩展） | InteractionSignal / EvidenceWindow | turn_analysis_chain 扩展 + `app/services/relationship_signal.py` |
| M3 Evolution Engine | 信号→事件→动力学→限速→同事务落账 | evolve 纯函数 + EvolutionOutcome | `app/services/relationship_evolution.py` |
| M4 Milestone System | 关系编年史：一次性事件、奖励、解锁 | MilestoneSpec 注册表 + 表 | `app/services/relationship_milestone.py` |
| M5 Conflict System | 冲突状态机、疏远检测、张力消退 | 状态迁移纯函数 + 表 | `app/services/relationship_conflict.py` |
| M6 Memory Integration | 关系记忆路由边界表 + 素材投递 | to_memory_candidates | `app/services/relationship_memory.py` |
| M7 Behavior Integration | 关系上下文进 Prompt + 行为风格修饰 | build_relationship_section 深化 | `app/prompts/builder.py` + behavior_engine 修饰 |
| M8 Autonomy Integration | 关系门控主动行为（R1~R5 规则） | PolicySnapshot 扩展 | autonomy_policy 追加纯函数 |
| M9 Persistence & Timeline | 版本化、关键帧快照、回滚、时间线 | 迁移 + 4 表 + /debug 端点 | `migrations/` + relationship_*_repository |

一条纪律贯穿全程：**信号升格为事件，事件决定 delta，delta 受动力学与限速约束，一切变化同事务落账本——账本即真相，状态只是账本当前投影。**

## 5. 与既有系统的边界（最容易混淆的三对）

| 概念 | 域 | 时间尺度 | 例子 |
|---|---|---|---|
| Emotion（V5） | 角色状态 | 分钟~小时 | "被夸了，开心（强度 0.7）" |
| Relationship（V5/V8.5） | 用户域长期 | 天~周 | "信任 0.55，最近有点紧张" |
| Milestone（V8.5 新） | 关系编年史 | 一次性 | "第一次在角色低谷时支持了她" |

- Emotion 不直接改关系分数（V5 既有边界不变）；情绪语境只作为信号的上下文输入（低谷期支持 → 信号显著度更高）。
- V8 World 是平行外部世界层，对 Character 状态零写回；V8.5 在 Character 域内深化关系系统，两者挂载点互不重叠。
- V4 记忆记录"关于用户的事实/事件"；V8.5 关系记忆是它的 relationship_event 子类的供给方之一（路由边界见 memory-integration.md）。

## 6. 文档导航

- [architecture.md](architecture.md) — 总体架构、挂载点清单、兼容契约、失败降级矩阵（先读这篇）
- [relationship-model.md](relationship-model.md) — M1：维度语义、默认值、派生指标、阶段冻结
- [interaction-analysis.md](interaction-analysis.md) — M2：信号模型、启发式词表、映射矩阵、证据窗
- [evolution-engine.md](evolution-engine.md) — M3：动力学修饰器、限速扩展、评估护栏（M3 附属）
- [milestone-system.md](milestone-system.md) — M4：里程碑目录、检测、奖励、解锁
- [conflict-system.md](conflict-system.md) — M5：冲突状态机、疏远检测、张力消退、原谅
- [memory-integration.md](memory-integration.md) — M6：路由边界表、投递、去重、模板
- [behavior-integration.md](behavior-integration.md) — M7：关系段深化渲染、默认态不变量、风格修饰
- [autonomy-integration.md](autonomy-integration.md) — M8：R1~R5 门控规则、解锁权限
- [persistence.md](persistence.md) — 表结构、版本/时间线、回滚、迁移
- [testing.md](testing.md) — 测试分层 + `tests/v8.5/` 套件 + 回归底线
- [tasks.md](tasks.md) — 任务注册表（V8.5-001 ~ 008）

## 7. 关键架构事实

```text
1. V8.5 全部挂载点是加法：turn_analysis_chain 只扩可选字段、post_process 的 STEP_HANDLERS
   不变（演化逻辑在既有 state_update 步骤内展开）、评估走既有 Rule 注册表、policy 只加可选
   参数与追加规则——默认态下 prompt 字节、policy 输出、V5 行为三者全部不变。
2. 新增持久化只有三张新表 + relationship_state 扩列；账本（relationship_events）结构
   基本不动（仅事件类型枚举扩 2 值 + source 扩 1 值，需迁移更新约束）。
3. 信号不落库：证据窗是内存结构（从账本近 N 行可重建），落库的只有升格后的事件、
   里程碑、冲突与关键帧快照——四类"因"全部有表可查，无因变化在评估中 fail。
4. P0 零新增 LLM 调用：信号识别复用既有 turn_analysis_chain 输出 + 确定性词表启发式；
   采样增强链仅留配置与接口，默认关（V8 解释器同款成本纪律）。
5. 演化纯函数可重放：回滚 = 关键帧 + 其后账本事件重放（前向修正，不删历史）。
6. 一切阈值与开关进 settings rel_* 组（沿用 V5 前缀续号）；全量既有测试（1069+）零回归
   是每个 Task 的底线。
```
