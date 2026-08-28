# Relationship Stage

## 1. 结论：需要 Stage，且必须代码计算

Stage 是"人格表现档位"的压缩信号（Prompt 中的关系描述、称呼、语气都按 stage 切换），有存在价值。但 **绝不让 LLM 每轮宣布"我们现在是 close relationship"**——那会瞬间跳变且不可审计。

## 2. 沿用 V2 四级，不采纳 5 级建议

V2 已有：`stranger / friend / close_friend / partner` + 阈值 + 迟滞（`state_engine.next_stage`）+ `STAGE_DESCRIPTIONS` prompt 资产。

| 题设建议 | 决策 |
|---|---|
| stranger / acquaintance / familiar / trusted / close | **不采纳**。 acquaintance≈stranger、trusted≈close_friend、familiar≈friend——5 级相对 V2 4 级无新增表达力，却要重写阈值、迟滞、prompt 描述与全部测试 |

**V2 stage 体系原样保留，V5 仅做一处扩展：tension 冻结。**

## 3. V5 扩展：tension 冻结升级

```text
升级判定前检查：tension > 0.5 → 本轮禁止升级（防"吵完架立刻升级关系"的荒谬跳变）
降级不受冻结影响（关系破裂仍可下降）
tension 回落到 ≤ 0.3 后解除冻结
```

## 4. 计算规则（保持 V2，重申防跳变语义）

- 升级：所有维度满足该级阈值（settings.stage_*）。
- 降级：当前级要求全部跌破 `threshold - hysteresis`（迟滞，防边界震荡）。
- 每轮最多迁移一级（`next_stage` 现有实现保证）。

## 5. Prompt 呈现

- 沿用 `STAGE_LABELS` / `STAGE_DESCRIPTIONS`（角色资产，非 LLM 生成）。
- 新增 tension 描述档（"相处自然 / 略有尴尬 / 气氛紧张"三档，按 0.3/0.5 分界）。

## 6. 验收标准

- Case 11：阈值跨越 → stage 升级；阈值回落 → 迟滞防震荡；tension > 0.5 时升级被冻结。
- Stage 输出永远是 4 值之一，且来自代码而非 LLM。
