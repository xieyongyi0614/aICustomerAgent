# Phase 2 Regression Checklist — Reflection

## Golden 行为（绝对不许变化）

1. Flag OFF：无任何 reflection 调度/trace/LLM 调用，v1 行为逐字节一致。
2. P2 期间 P1 Memory 全部 golden 不回退（V4 checklist）。
3. 反思为纯后台：前台延迟零影响。
4. Insight 不直写 State/Relationship（依赖矩阵断言测试）。

## 必须重跑的旧版本回归

| 来源 | 范围 | 触发条件 |
|---|---|---|
| V4 memory checklist | REF 读写 Memory 均为只读，行为不回退 | REF-002/004 |
| P1 全部 Eval Gate | 上游能力不回退 | 每灰度推进 |
| V7.5/V7.8 checklist | 评估与 trace 平面扩展不破坏 | REF-006 |

## 执行步骤

```text
1. Flag OFF 全量 pytest + golden
2. Flag ON 影子：P1 Eval Gate 复跑 + REF-002~005 场景集
3. 依赖矩阵断言（跨域直写静态检查）
4. 结果记录附录
```
