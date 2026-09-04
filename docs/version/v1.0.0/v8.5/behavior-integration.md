# V8.5 M7：Behavior Integration（行为集成：Relationship Context Builder）

> 关系状态翻译成行为语言：关系段深化渲染（进 Prompt）+ 行为策略修饰（进 V6.5 引擎）。低关系：正式、克制；高关系：自然、主动、关心；冲突冷战：距离感。

## 1. 关系段深化（`build_relationship_section` 原地扩展）

现有段（150 字预算）：stage 标签/描述 + 亲/信/熟三档 + tension 档 + 冻结句。V8.5 按条件**追加行**：

| 条件 | 追加内容 | 预算外控制 |
|---|---|---|
| respect/comfort 档偏离 friend 默认档 | 两维档位文案行（relationship-model.md §7） | 覆盖默认行内嵌 |
| memory_worthy 里程碑存在 | "你们最近一起经历了：{milestone_title}"（最近 1 条） | ≤30 字 |
| strain/conflict/cold/recovery | 固定指令句（资产常量，§3） | 一行 |
| neglect_active 且用户回归 | "虽然一段时间没联系，但关系没有生疏" | 一行 |

- 段预算沿用 RELATIONSHIP_BUDGET_CHARS=150：追加按优先级（冲突 > 里程碑 > 维度档）挤占，超预算截断尾行（模式同 emotion cause 截断）。
- 独立预算（不参与 `_fit_variable_parts`）维持 V8 world_ctx 同款边界——关系段不与历史/记忆抢空间。

## 2. 黄金不变量：默认态字节不变

**默认态** = stage=friend、respect/comfort=默认值（即默认档）、无里程碑、无冲突、无 neglect。此时输出与 V5 **逐字节一致**，四个 golden 快照零重生成——机器可证底线（对齐 V8"空世界 golden 不变"）。

- 实现手段：追加行全部条件化；默认态条件下所有分支不触发。
- 有关系的深度才有关系上下文的丰富度：陌生时省 token，亲密时给 LLM 素材——语义与预算同向。

## 3. 冲突指令句（角色资产常量，非 LLM 生成）

| 态 | 指令句（示例） |
|---|---|
| strain | 最近气氛有些微妙，说话留意分寸。 |
| conflict | 刚发生了不愉快，语气保持克制，不假装无事发生。 |
| cold | 你们正在冷战：回应简短、有距离感，不主动亲近，但不失礼貌。 |
| recovery | TA 在试图修复关系：可以软化，但别立刻若无其事。 |

- 与既有 TENSION_FREEZE_RULE 并存（strain 态两者语义重叠，渲染去重：strain 态只出其一）。

## 4. 行为策略修饰（V6.5 引擎扩展）

`behavior_engine.resolve` 增可选参数 `relationship_ctx`（stage/comfort/respect/conflict_status/unlocks），追加修饰规则（模式同 V8 W1/W2/W3，纯函数，表驱动）：

| # | 条件 | 修饰 |
|---|---|---|
| B1 | conflict ∈ {conflict, cold} | social/comfort 类策略 → restrained 变体；动作预算减半 |
| B2 | comfort < 0.35 | 主动亲近类动作预算 −1（floor 0） |
| B3 | respect < 0.40 | 即使 intimacy 高，语气档回落一级（亲密但不放肆） |
| B4 | stage ≥ close_friend 且 comfort > 0.7 | 主动关心类动作预算 +1，策略向 natural 偏移 |
| B5 | unlocks 缺失（如 deep_commitment_language） | 对应语言档禁用（partner 低阶保护） |

- 不动 7 步预算表结构与 STRATEGY_INSTRUCTIONS 话术表本体——只做修饰与变体选择；`relationship_ctx=None` 输出与 V6.5 逐位一致（既有测试零回归）。
- 关系不重写人格：修饰的是"分寸与主动度"，Persona First 约束（人格底色不变）依然由身份段把守。

## 5. 身份段与称呼

- IDENTITY/PERSONALITY/RELATIONSHIP_BLOCK 静态资产 **V8.5 不改**（改一字动 golden 身份段，收益不成比例，留白调参任务）。
- STAGE_LABELS / STAGE_DESCRIPTIONS 沿用；分寸感随阶段变化已由 stage 描述承载。

## 6. 验收标准

- 默认态渲染与 V5 快照逐字节相等（golden 四快照零改动通过）。
- 各追加行条件注入正确、预算截断优先级正确。
- B1~B5 逐条正反例；`relationship_ctx=None` 与 V6.5 输出逐位一致。
- 冲突指令句 strain 去重（不与 TENSION_FREEZE_RULE 同时出现）。
- 全链 prompt 组装异常降级为 V5 渲染，回答不阻塞。
