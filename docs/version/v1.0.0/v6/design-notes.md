# V6 Architecture 设计说明（补充：关键取舍记录）

> 本文记录设计过程中的关键决策与被否方案，供实现期对照。

## 1. 为什么 Intention 是独立链而不是扩展 TurnAnalysis

- 主体相反：turn_analysis 回答"用户发生了什么"，intention 回答"角色想做什么"。
- 降级语义不同：turn_analysis 失败降级为默认分析（用户侧），intention 失败降级为 continue_topic（角色侧）——混在一个 Schema 里无法独立降级。
- 迭代节奏不同：intention prompt 会随目标体系频繁调优，独立文件独立 golden。

## 2. 为什么 Goal 不进 turn_analysis 的输出

- Goal 生命周期是**跨轮**的，turn_analysis 是**单轮**的；让单轮 LLM 决定 Goal 生死会引入动机震荡（每轮重新生成目标 = 没有目标）。
- Goal 创建/完成规则全部表驱动（goal-policy.md），LLM 只经 IntentionDecision 间接影响下一轮 review 的信号输入。

## 3. 为什么第一版不做三层 Goal

Persistent + Current 已覆盖"长期动机 + 情境目标"；Immediate 层与 Intention 完全重叠，建模成第三层只会造成"本轮目标 vs 本轮意图"的职责撕扯。若 V7 出现真实需求（如中期计划），在 Current 与 Intention 之间插入 MediumGoal，模型字段已预留 horizon 扩展位。

## 4. Prompt 注入顺序：目标段放关系段之后、记忆段之前

动机先于素材：LLM 先知道"我想做什么"，再筛选"哪些记忆相关"。若放记忆之后，记忆段的关联性判断失去动机锚点。场景段仍在其后（当下情境最后校准）。

## 5. Intentions 与 V2 Behavior 并存而非替换

V2 behavior 是被验证过的表达层资产（BEHAVIOR_INSTRUCTIONS 映射 + 测试），替换成本高且无收益。V6 让 intention 做主、behavior 做辅，两者在 answer prompt 中各占一段；V7 再评估收敛。

## 6. 时延论证（SSE 零退化）

现有 gather 3 链并行、answer 等待全部结果——加入第 4 条并行链不增加 wall time。goals 查询为 1 次索引 SELECT（10 次前台查询变 11 次）。后台 goal_review 是注册表追加步骤，独立容错。

## 7. 安全边界重申

- 用户语言不可直接创建/修改 persistent goal（goal-policy.md §5）——防"你应该喜欢我"式操纵。
- IntentionPolicy 对表达类意图设置状态门槛（affection 需 intimacy、distance 需 tension）——防意图越级。
- reason 仅结构化单句（≤60 字），无思维链——防不可审计的隐藏推理。
- Goal 不回写 Memory/Scene——单向依赖，V4/V5 管线零感知。
