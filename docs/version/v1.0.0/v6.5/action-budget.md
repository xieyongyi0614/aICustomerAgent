# Action Budget

## 1. 问题与现状

真实测试中每轮回复出现 4~6 个 `*动作描写*`（脸颊泛红/握住手/整理衣领/温柔地看着你），角色退化为「小说旁白生成器」。

现状约束只有两处，且都是**静态全文**：

- `BEHAVIOR_BLOCK`：「不每句话使用动作描写」（无量化）
- `RHYTHM_BLOCK`（V3）：「0~2 个角色动作」——仅当场景段存在时注入，且不随 mode/stage/mood/策略变化

## 2. 架构约束：预算只能事前注入

关键事实：answer_chain 是 **NDJSON 流式透传**，回复 token 直接下发前端，post_process 不拦截 reply。因此：

- **预算的唯一生效手段是事前 Prompt 约束**（生成前注入预算短句）。
- 输出侧只能做**事后统计**（违规计数进 trace，用于调参），无法拦截已发出的流。统计器属 P2（V6.5-011），不作为预算的执行机制。

这与 V3 response-rhythm.md §5「不做输出侧自动重写/过滤」的既有决策一致并延续。

## 3. 预算模型

```python
# app/models/behavior_strategy.py
class ActionBudget(BaseModel):
    max_action_desc: int = 1                      # 本轮 *动作描写* 上限（0~2）
    allow_action_desc: bool = True                # professional 下 False
    physical_contact: PhysicalContactLevel = "none"  # 身体接触上限
    emotion_expression: Literal["subtle", "natural", "rich"] = "natural"
    action_desc_factor: float = 1.0               # mood 乘数（渲染用，非注入项）
```

`emotion_expression` 语义：subtle=只通过语气流露；natural=可有一处显式情绪表达；rich=沉浸模式允许多处。

## 4. 计算规则（纯函数预算表）

```text
compute_budget(mode, stage_params, mood_modifier, strategy, scene, intensity) → ActionBudget
```

按序应用（后一步只收紧或微调，不越过前一步的硬上限）：

| 步骤 | 输入 | 规则 |
|---|---|---|
| 1. Mode 基线 | mode | professional → (0, False)；default → (1, True)；immersive → (2, True) |
| 2. Stage 修正 | stage_params.action_desc_max | 取 min(mode 基线, stage 上限)——stranger 档沉浸模式也只有 1 |
| 3. Mood 乘数 | mood_modifier.action_desc_factor | `max_desc = round(min(基线 × 因子, 基线))`——乘数只降不升（上限仍为基线），excited 1.2 保持、worried/tired/angry 0.5 减半 |
| 4. Strategy 修正 | strategy | quiet_companion / reserved_distance / sincere_repair → max=0（这些方式不需要动作）；affectionate_expression → physical_contact = stage 档值；其余不变 |
| 5. Activity 修正 | scene.current_activity 非空 | max_action_desc = max(0, max−1)——当前活动本身占用动作（正在切西瓜时无需额外动作描写） |
| 6. 强情绪 | intensity ≥ 0.8 | max_action_desc = 0（强情绪用语言，不堆动作） |
| 7. 场景硬约束 | scene_intent / directive | correct_scene 轮不额外收紧（V3 rhythm 已接管本轮全部叙事） |

physical_contact 全链取 `min(policy stage 档, strategy 允许)`；mode=professional 恒 none。

计算结果随 BehaviorDirective 进 trace（含每步 rule 归因），turn_meta 携带最终值供前端调试。

## 5. Prompt 渲染

预算渲染进【表现方式】段（response-controller.md），短句化示例：

```text
【表现方式】
这一轮：先安静陪着，不急着给建议。
本轮动作描写：0 个；情绪通过语气流露，不做显式动作。
```

- 预算行只在**偏离默认值**或**为 0** 时渲染强制句，默认放行时不渲染（减少 token 噪声）：`max=0` → 「本轮不做动作描写」；`max=1` → 「最多 1 个动作描写，放在最关键处」；`max=2` 且 immersive → 「动作描写不超过 2 处，不连续堆叠」。
- 身体接触非 none 时渲染：「可以有轻度的身体动作（如递东西、整理衣角），不做更亲密的接触」。
- 与 RHYTHM_BLOCK 的收口：RHYTHM「0~2 个角色动作」行在 Budget 存在时由 Budget 值替换渲染（同一约束不出现两个数字），RHYTHM 其余规则（不替用户行动/不虚构用户心理等）保留不动。

## 6. 测试要点

- 预算表矩阵：mode × stage × mood × strategy × activity 关键组合断言（testing.md §Action Budget）。
- 渲染断言：professional 场景不含动作预算句但有 allow_action_desc=False 硬句；RHYTHM 替换不重复计数。
- 回归：V3 rhythm 现有测试不受影响（替换后语义等价）。
