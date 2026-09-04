# Phase 3 Regression Checklist — Character Development

## Golden 行为（绝对不许变化）

1. Flag OFF（或 development_state 为空）：BehaviorPolicy/ResponseStyle/Goal 行为与 v1 **字节级一致**。
2. V6.5 行为策略、V5 情绪衰减、V8.5 关系数学本体零改动（version-boundary Preserve 断言）。
3. P1/P2 全部 golden 不回退。
4. Persona 静态资产文件 hash 不变。

## 必须重跑的旧版本回归

| 来源 | 范围 | 触发条件 |
|---|---|---|
| V6.5 Behavior checklist | 行为域读取叠加层不破坏 | DEV-003 |
| V6 Goal checklist | goal_service 权重调制不破坏 | DEV-003 |
| P1/P2 Eval Gate | 上游不回退 | 每灰度推进 |
| V7.5 checklist | evaluation 扩展 | DEV-005 |

## 执行步骤

```text
1. 空数据 golden（叠加层为空 = v1）
2. V6.5/V6 checklist
3. 静态资产 hash 断言 + 数值公式断言测试
4. 结果记录附录
```
